from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import (
    Server,
    ServerAuditLog,
    ServerBan,
    ServerConfigHistory,
    ServerMember,
    User,
)
from app.services.server_authorization_service import resolve_server_permissions
from app.services.server_service import transfer_server_ownership
from conftest import test_engine


def _create_server(client, owner, auth_headers):
    response = client.post(
        "/servers/",
        json={"name": "Servidor para transferência"},
        headers=auth_headers(owner),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _add_member(db_session, server_id: int, user_id: int, *, status="ACTIVE"):
    membership = ServerMember(
        server_id=server_id,
        user_id=user_id,
        status=status,
    )
    if status == "LEFT":
        from datetime import datetime, timezone

        membership.left_at = datetime.now(timezone.utc)
    db_session.add(membership)
    db_session.flush()
    return membership


def test_owner_transfers_to_active_unbanned_member_and_audits_atomically(
    client, db_session, create_user, auth_headers
):
    owner = create_user()
    recipient = create_user()
    server = _create_server(client, owner, auth_headers)
    _add_member(db_session, server["id"], recipient["id"])

    response = client.post(
        f"/servers/{server['id']}/transfer-ownership",
        json={"new_owner_id": recipient["id"]},
        headers=auth_headers(owner),
    )

    assert response.status_code == 200, response.text
    assert response.json()["owner_id"] == recipient["id"]
    db_session.expire_all()
    assert db_session.get(Server, server["id"]).owner_id == recipient["id"]
    memberships = db_session.scalars(
        select(ServerMember).where(ServerMember.server_id == server["id"])
    ).all()
    assert {member.user_id: member.status for member in memberships} == {
        owner["id"]: "ACTIVE",
        recipient["id"]: "ACTIVE",
    }

    audit = db_session.scalar(
        select(ServerAuditLog).where(
            ServerAuditLog.server_id == server["id"],
            ServerAuditLog.event_type == "OWNERSHIP_TRANSFERRED",
        )
    )
    history = db_session.scalar(
        select(ServerConfigHistory).where(
            ServerConfigHistory.server_id == server["id"],
            ServerConfigHistory.setting_name == "owner_id",
        )
    )
    assert audit is not None
    assert audit.actor_user_id == owner["id"]
    assert audit.target_user_id == recipient["id"]
    assert audit.ban_id is None
    assert audit.role_snapshot is None
    assert history is not None
    assert history.changed_by == owner["id"]
    assert history.old_value == str(owner["id"])
    assert history.new_value == str(recipient["id"])
    assert resolve_server_permissions(
        db_session, server["id"], recipient["id"]
    ).is_owner is True
    assert resolve_server_permissions(
        db_session, server["id"], owner["id"]
    ).is_owner is False

    audit_response = client.get(
        f"/servers/{server['id']}/audit-logs",
        params={"event_type": "OWNERSHIP_TRANSFERRED"},
        headers=auth_headers(recipient),
    )
    assert audit_response.status_code == 200, audit_response.text
    assert [item["id"] for item in audit_response.json()] == [audit.id]


def test_non_owner_cannot_transfer_ownership(
    client, db_session, create_user, auth_headers
):
    owner = create_user()
    actor = create_user()
    recipient = create_user()
    server = _create_server(client, owner, auth_headers)
    _add_member(db_session, server["id"], actor["id"])
    _add_member(db_session, server["id"], recipient["id"])

    response = client.post(
        f"/servers/{server['id']}/transfer-ownership",
        json={"new_owner_id": recipient["id"]},
        headers=auth_headers(actor),
    )

    assert response.status_code == 403
    assert db_session.get(Server, server["id"]).owner_id == owner["id"]
    assert db_session.scalar(
        select(ServerAuditLog.id).where(
            ServerAuditLog.server_id == server["id"],
            ServerAuditLog.event_type == "OWNERSHIP_TRANSFERRED",
        )
    ) is None


def test_missing_or_foreign_recipient_cannot_receive_ownership(
    client, db_session, create_user, auth_headers
):
    owner = create_user()
    foreign_owner = create_user()
    foreign_member = create_user()
    server = _create_server(client, owner, auth_headers)
    foreign_server = _create_server(client, foreign_owner, auth_headers)
    _add_member(db_session, foreign_server["id"], foreign_member["id"])

    for recipient_id in (999_999_999, foreign_member["id"]):
        response = client.post(
            f"/servers/{server['id']}/transfer-ownership",
            json={"new_owner_id": recipient_id},
            headers=auth_headers(owner),
        )
        assert response.status_code == 404
        assert db_session.get(Server, server["id"]).owner_id == owner["id"]


def test_left_recipient_cannot_receive_ownership(
    client, db_session, create_user, auth_headers
):
    owner = create_user()
    recipient = create_user()
    server = _create_server(client, owner, auth_headers)
    _add_member(db_session, server["id"], recipient["id"], status="LEFT")

    response = client.post(
        f"/servers/{server['id']}/transfer-ownership",
        json={"new_owner_id": recipient["id"]},
        headers=auth_headers(owner),
    )

    assert response.status_code == 409
    assert db_session.get(Server, server["id"]).owner_id == owner["id"]


def test_recipient_with_active_ban_cannot_receive_ownership(
    client, db_session, create_user, auth_headers
):
    owner = create_user()
    recipient = create_user()
    server = _create_server(client, owner, auth_headers)
    _add_member(db_session, server["id"], recipient["id"])
    db_session.add(
        ServerBan(
            server_id=server["id"],
            user_id=recipient["id"],
            banned_by=owner["id"],
            target_highest_role_position=0,
        )
    )
    db_session.flush()

    response = client.post(
        f"/servers/{server['id']}/transfer-ownership",
        json={"new_owner_id": recipient["id"]},
        headers=auth_headers(owner),
    )

    assert response.status_code == 409
    assert db_session.get(Server, server["id"]).owner_id == owner["id"]


def test_transfer_requires_auth_and_strict_valid_body(client, create_user, auth_headers):
    owner = create_user()
    recipient = create_user()
    server = _create_server(client, owner, auth_headers)
    path = f"/servers/{server['id']}/transfer-ownership"

    assert client.post(path, json={"new_owner_id": recipient["id"]}).status_code == 401
    assert client.post(
        path,
        json={"new_owner_id": True},
        headers=auth_headers(owner),
    ).status_code == 422
    assert client.post(
        path,
        json={"new_owner_id": recipient["id"], "owner_id": recipient["id"]},
        headers=auth_headers(owner),
    ).status_code == 422


def test_old_owner_can_leave_after_transfer_and_new_owner_remains_owner(
    client, db_session, create_user, auth_headers
):
    owner = create_user()
    recipient = create_user()
    server = _create_server(client, owner, auth_headers)
    _add_member(db_session, server["id"], recipient["id"])

    transfer = client.post(
        f"/servers/{server['id']}/transfer-ownership",
        json={"new_owner_id": recipient["id"]},
        headers=auth_headers(owner),
    )
    leave = client.post(
        f"/servers/{server['id']}/leave",
        headers=auth_headers(owner),
    )

    assert transfer.status_code == 200
    assert leave.status_code == 204
    db_session.expire_all()
    assert db_session.get(Server, server["id"]).owner_id == recipient["id"]
    old_membership = db_session.scalar(
        select(ServerMember).where(
            ServerMember.server_id == server["id"],
            ServerMember.user_id == owner["id"],
        )
    )
    assert old_membership.status == "LEFT"


def test_audit_failure_rolls_back_owner_update_and_config_history(
    client, db_session, create_user, auth_headers
):
    owner = create_user()
    recipient = create_user()
    server = _create_server(client, owner, auth_headers)
    _add_member(db_session, server["id"], recipient["id"])

    def fail_when_audit_is_pending(session, _flush_context, _instances):
        if any(isinstance(item, ServerAuditLog) for item in session.new):
            raise SQLAlchemyError("simulated audit persistence failure")

    event.listen(db_session, "before_flush", fail_when_audit_is_pending)
    try:
        response = client.post(
            f"/servers/{server['id']}/transfer-ownership",
            json={"new_owner_id": recipient["id"]},
            headers=auth_headers(owner),
        )
    finally:
        event.remove(db_session, "before_flush", fail_when_audit_is_pending)

    assert response.status_code == 500
    db_session.expire_all()
    assert db_session.get(Server, server["id"]).owner_id == owner["id"]
    assert db_session.scalar(
        select(ServerAuditLog.id).where(
            ServerAuditLog.server_id == server["id"],
            ServerAuditLog.event_type == "OWNERSHIP_TRANSFERRED",
        )
    ) is None
    assert db_session.scalar(
        select(ServerConfigHistory.id).where(
            ServerConfigHistory.server_id == server["id"],
            ServerConfigHistory.setting_name == "owner_id",
        )
    ) is None


def _persistent_concurrent_context():
    suffix = uuid4().hex[:8]
    with Session(test_engine) as db:
        users = [
            User(
                username=f"own{suffix}",
                email=f"own{suffix}@example.com",
                password_hash="test-only-hash",
                is_active=True,
            ),
            User(
                username=f"n1{suffix}",
                email=f"n1{suffix}@example.com",
                password_hash="test-only-hash",
                is_active=True,
            ),
            User(
                username=f"n2{suffix}",
                email=f"n2{suffix}@example.com",
                password_hash="test-only-hash",
                is_active=True,
            ),
        ]
        db.add_all(users)
        db.flush()
        server = Server(owner_id=users[0].id, name=f"Transferência {suffix}")
        db.add(server)
        db.flush()
        db.add_all(
            [
                ServerMember(server_id=server.id, user_id=user.id, status="ACTIVE")
                for user in users
            ]
        )
        db.commit()
        return server.id, [user.id for user in users]


def _cleanup_persistent_context(context):
    server_id, user_ids = context
    with Session(test_engine) as db:
        db.execute(
            ServerAuditLog.__table__.delete().where(
                ServerAuditLog.server_id == server_id
            )
        )
        db.execute(
            ServerConfigHistory.__table__.delete().where(
                ServerConfigHistory.server_id == server_id
            )
        )
        db.execute(
            ServerBan.__table__.delete().where(ServerBan.server_id == server_id)
        )
        db.execute(
            ServerMember.__table__.delete().where(
                ServerMember.server_id == server_id
            )
        )
        db.execute(Server.__table__.delete().where(Server.id == server_id))
        db.execute(User.__table__.delete().where(User.id.in_(user_ids)))
        db.commit()


def test_concurrent_transfers_serialize_and_only_current_owner_can_win():
    context = _persistent_concurrent_context()
    server_id, user_ids = context
    owner_id, recipient_a_id, recipient_b_id = user_ids
    barrier = Barrier(2)

    def transfer(recipient_id):
        with Session(test_engine) as db:
            barrier.wait(timeout=10)
            try:
                transfer_server_ownership(
                    db,
                    server_id=server_id,
                    actor_user_id=owner_id,
                    new_owner_id=recipient_id,
                )
                return "ok"
            except HTTPException as exc:
                return exc.status_code

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(transfer, recipient_a_id),
                executor.submit(transfer, recipient_b_id),
            ]
            outcomes = [future.result(timeout=30) for future in futures]

        assert outcomes.count("ok") == 1
        assert outcomes.count(403) == 1
        with Session(test_engine) as db:
            server = db.get(Server, server_id)
            events = db.scalars(
                select(ServerAuditLog).where(
                    ServerAuditLog.server_id == server_id,
                    ServerAuditLog.event_type == "OWNERSHIP_TRANSFERRED",
                )
            ).all()
            histories = db.scalars(
                select(ServerConfigHistory).where(
                    ServerConfigHistory.server_id == server_id,
                    ServerConfigHistory.setting_name == "owner_id",
                )
            ).all()
        assert server.owner_id in {recipient_a_id, recipient_b_id}
        assert len(events) == 1
        assert len(histories) == 1
        assert events[0].actor_user_id == owner_id
        assert events[0].target_user_id == server.owner_id
    finally:
        _cleanup_persistent_context(context)
