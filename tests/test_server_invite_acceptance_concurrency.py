from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import (
    Server,
    ServerBan,
    ServerInvite,
    ServerMember,
    ServerMemberRole,
    ServerAuditLog,
    User,
)
from app.services.server_invite_service import (
    accept_server_invite,
    create_server_invite,
    hash_server_invite_token,
    revoke_server_invite,
)
from app.services.server_member_service import leave_server
from app.schemas import ServerBanResponse, ServerInviteCreatedResponse, ServerInviteMembershipResponse
from app.services.server_moderation_service import ban_server_member, kick_server_member, unban_server_member
from conftest import test_engine


def _persistent_context(*, target_active=False, max_uses=1):
    suffix = uuid4().hex[:10]
    token = f"invite-concurrency-{suffix}"
    with Session(test_engine) as db:
        owner = User(
            username=f"invite_owner_{suffix}",
            email=f"invite_owner_{suffix}@example.com",
            password_hash="synthetic-test-hash",
            is_active=True,
        )
        target = User(
            username=f"invite_target_{suffix}",
            email=f"invite_target_{suffix}@example.com",
            password_hash="synthetic-test-hash",
            is_active=True,
        )
        second = User(
            username=f"invite_second_{suffix}",
            email=f"invite_second_{suffix}@example.com",
            password_hash="synthetic-test-hash",
            is_active=True,
        )
        db.add_all([owner, target, second])
        db.flush()
        server = Server(owner_id=owner.id, name=f"Convite concorrente {suffix}")
        db.add(server)
        db.flush()
        owner_member = ServerMember(server_id=server.id, user_id=owner.id)
        target_member = ServerMember(
            server_id=server.id,
            user_id=target.id,
            status="ACTIVE" if target_active else "LEFT",
            left_at=None if target_active else datetime.now(timezone.utc),
        )
        db.add_all([owner_member, target_member])
        invite = ServerInvite(
            server_id=server.id,
            created_by=owner.id,
            token_hash=hash_server_invite_token(token),
            max_uses=max_uses,
            uses_count=0,
        )
        db.add(invite)
        db.commit()
        return owner.id, target.id, second.id, target_member.id, server.id, invite.id, token


def _cleanup(context):
    owner_id, target_id, second_id, _member_id, server_id, _invite_id, _token = context
    with Session(test_engine) as db:
        db.execute(ServerAuditLog.__table__.delete().where(ServerAuditLog.server_id == server_id))
        db.execute(ServerBan.__table__.delete().where(ServerBan.server_id == server_id))
        db.execute(ServerInvite.__table__.delete().where(ServerInvite.server_id == server_id))
        db.execute(ServerMemberRole.__table__.delete().where(ServerMemberRole.server_id == server_id))
        db.execute(ServerMember.__table__.delete().where(ServerMember.server_id == server_id))
        db.execute(Server.__table__.delete().where(Server.id == server_id))
        db.execute(User.__table__.delete().where(User.id.in_([owner_id, target_id, second_id])))
        db.commit()


def _run_concurrently(operation_a, operation_b):
    barrier = Barrier(2)

    def run(operation):
        with Session(test_engine) as db:
            barrier.wait(timeout=10)
            try:
                operation(db)
                return "ok"
            except HTTPException as exc:
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(run, operation_a), executor.submit(run, operation_b)]
        return [future.result(timeout=30) for future in futures]


def _write(db, operation, context):
    owner, target, _, _, server, _, token = context
    if operation == "create":
        return create_server_invite(db, server, owner, max_uses=2)
    if operation == "accept":
        return accept_server_invite(db, server, token, target)
    return ban_server_member(db, server, target, owner)


@pytest.mark.parametrize("operation", ["create", "accept", "ban"])
def test_write_response_survives_later_transaction_without_sql(operation):
    context = _persistent_context(target_active=operation == "ban")
    owner, target, _, member_id, server, _, _ = context
    try:
        with test_engine.connect() as conn, Session(conn, expire_on_commit=True) as writer:
            committed = False
            post_commit_sql = []

            @event.listens_for(writer, "after_commit")
            def mark_commit(session):
                nonlocal committed
                committed = True

            @event.listens_for(conn, "before_cursor_execute")
            def record_sql(conn, cursor, statement, parameters, context, executemany):
                if committed:
                    post_commit_sql.append(statement)

            response = _write(writer, operation, context)
            assert committed
            with Session(test_engine) as other:
                if operation == "create":
                    assert isinstance(response, ServerInviteCreatedResponse)
                    revoke_server_invite(other, server, response.id, owner)
                    assert other.get(ServerInvite, response.id).revoked_at is not None
                    body = response.model_dump(mode="json")
                    assert body["revoked_at"] is None
                    assert body["token"] and "token_hash" not in body
                elif operation == "accept":
                    assert isinstance(response, ServerInviteMembershipResponse)
                    kick_server_member(other, server, target, owner)
                    assert other.get(ServerMember, member_id).status == "LEFT"
                    body = response.model_dump(mode="json")
                    assert body["status"] == "ACTIVE" and body["left_at"] is None
                else:
                    assert isinstance(response, ServerBanResponse)
                    unban_server_member(other, server, response.id, owner)
                    assert other.get(ServerBan, response.id).is_active is False
                    body = response.model_dump(mode="json")
                    assert body["is_active"] is True
                    assert body["revoked_at"] is None and body["revoked_by"] is None
            assert post_commit_sql == []
    finally:
        _cleanup(context)


@pytest.mark.parametrize("operation", ["create", "accept", "ban"])
def test_failed_commit_returns_error_and_rolls_back(operation):
    context = _persistent_context(target_active=operation == "ban")
    _, _, _, member_id, server, invite_id, _ = context
    try:
        with Session(test_engine, expire_on_commit=True) as writer:
            @event.listens_for(writer, "before_commit")
            def fail_commit(session):
                raise SQLAlchemyError("Falha de commit simulada")

            with pytest.raises(HTTPException) as failure:
                _write(writer, operation, context)
            assert failure.value.status_code == 500
            assert not writer.in_transaction()

        with Session(test_engine) as reader:
            invites = reader.scalars(select(ServerInvite).where(ServerInvite.server_id == server)).all()
            assert [(item.id, item.uses_count) for item in invites] == [(invite_id, 0)]
            member = reader.get(ServerMember, member_id)
            assert member.status == ("ACTIVE" if operation == "ban" else "LEFT")
            assert (member.left_at is None) == (operation == "ban")
            assert reader.scalar(select(ServerBan.id).where(ServerBan.server_id == server)) is None
            assert reader.scalar(select(ServerAuditLog.id).where(ServerAuditLog.server_id == server)) is None
    finally:
        _cleanup(context)


def test_concurrent_acceptance_consumes_limited_invite_once():
    context = _persistent_context(max_uses=1)
    _owner_id, target_id, second_id, member_id, server_id, invite_id, token = context
    try:
        outcomes = _run_concurrently(
            lambda db: accept_server_invite(db, server_id, token, target_id),
            lambda db: accept_server_invite(db, server_id, token, second_id),
        )
        assert outcomes.count("ok") == 1
        assert outcomes.count(409) == 1
        with Session(test_engine) as db:
            invite = db.get(ServerInvite, invite_id)
            memberships = db.scalars(
                select(ServerMember).where(
                    ServerMember.server_id == server_id,
                    ServerMember.status == "ACTIVE",
                    ServerMember.user_id.in_([target_id, second_id]),
                )
            ).all()
        assert invite.uses_count == 1
        assert len(memberships) == 1
    finally:
        _cleanup(context)


def test_acceptance_racing_with_ban_never_consumes_invite_after_ban():
    context = _persistent_context(target_active=True)
    owner_id, target_id, _second_id, member_id, server_id, invite_id, token = context
    try:
        outcomes = _run_concurrently(
            lambda db: accept_server_invite(db, server_id, token, target_id),
            lambda db: ban_server_member(db, server_id, target_id, owner_id),
        )
        assert outcomes.count("ok") == 1
        assert any(value in {403, 409} for value in outcomes)
        with Session(test_engine) as db:
            membership = db.get(ServerMember, member_id)
            invite = db.get(ServerInvite, invite_id)
            active_ban = db.scalar(
                select(ServerBan.id).where(
                    ServerBan.server_id == server_id,
                    ServerBan.user_id == target_id,
                    ServerBan.is_active.is_(True),
                )
            )
        assert membership.status == "LEFT"
        assert active_ban is not None
        assert invite.uses_count == 0
    finally:
        _cleanup(context)


def test_acceptance_racing_with_voluntary_leave_preserves_serial_outcome():
    context = _persistent_context(target_active=True)
    _owner_id, target_id, _second_id, member_id, server_id, invite_id, token = context
    try:
        outcomes = _run_concurrently(
            lambda db: accept_server_invite(db, server_id, token, target_id),
            lambda db: leave_server(db, db.get(User, target_id), server_id),
        )
        assert outcomes.count("ok") == 2 or (
            outcomes.count("ok") == 1 and outcomes.count(409) == 1
        )
        with Session(test_engine) as db:
            membership = db.get(ServerMember, member_id)
            invite = db.get(ServerInvite, invite_id)
        if membership.status == "ACTIVE":
            assert invite.uses_count == 1
            assert membership.left_at is None
        else:
            assert membership.status == "LEFT"
            assert invite.uses_count == 0
            assert membership.left_at is not None
    finally:
        _cleanup(context)
