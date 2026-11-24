from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import event, select
from sqlalchemy.exc import SQLAlchemyError

from app.models import (
    Server,
    ServerInvite,
    ServerMember,
    ServerMemberRole,
    ServerRole,
)
from app.services.server_invite_service import (
    create_server_invite,
    hash_server_invite_token,
    revoke_server_invite,
    verify_server_invite_token,
)


def _server(db_session, create_user, *, name="Servidor para convites"):
    owner = create_user()
    server = Server(owner_id=owner["id"], name=name)
    db_session.add(server)
    db_session.flush()
    owner_membership = ServerMember(
        server_id=server.id,
        user_id=owner["id"],
        status="ACTIVE",
    )
    db_session.add(owner_membership)
    db_session.flush()
    return owner, server


def _add_member(db_session, server, user):
    membership = ServerMember(
        server_id=server.id,
        user_id=user["id"],
        status="ACTIVE",
    )
    db_session.add(membership)
    db_session.flush()
    return membership


def _grant_manage_invites(db_session, server, owner, user):
    membership = _add_member(db_session, server, user)
    role = ServerRole(
        server_id=server.id,
        name=f"Gerenciador de convites {user['id']}",
        position=1,
        permissions={"manage_invites": True},
        is_default=False,
        is_system_role=False,
    )
    db_session.add(role)
    db_session.flush()
    db_session.add(
        ServerMemberRole(
            server_id=server.id,
            member_id=membership.id,
            role_id=role.id,
            assigned_by=owner["id"],
        )
    )
    db_session.flush()
    return membership, role


def _assert_http_error(call, expected_status):
    with pytest.raises(HTTPException) as error:
        call()
    assert error.value.status_code == expected_status


def test_owner_creates_invite_and_only_hash_is_persisted(
    db_session, create_user
):
    owner, server = _server(db_session, create_user)
    expiry = datetime.now(timezone.utc) + timedelta(days=2)

    invite = create_server_invite(
        db_session,
        server.id,
        owner["id"],
        expires_at=expiry,
        max_uses=4,
    )

    token = invite.token
    stored = db_session.get(ServerInvite, invite.id)
    assert invite.server_id == server.id
    assert stored.created_by == owner["id"]
    assert invite.created_at is not None
    assert invite.expires_at == expiry
    assert invite.max_uses == 4
    assert invite.uses_count == 0
    assert invite.revoked_at is None
    assert stored.token_hash == hash_server_invite_token(token)
    assert token not in stored.token_hash
    assert verify_server_invite_token(token, stored.token_hash)
    assert not verify_server_invite_token("different-token", stored.token_hash)
    assert db_session.scalar(
        select(ServerInvite.token_hash).where(ServerInvite.id == invite.id)
    ) == hash_server_invite_token(token)


def test_active_member_with_manage_invites_can_create_invite(
    db_session, create_user
):
    owner, server = _server(db_session, create_user)
    manager = create_user()
    _grant_manage_invites(db_session, server, owner, manager)

    invite = create_server_invite(db_session, server.id, manager["id"])

    assert invite.token
    assert db_session.get(ServerInvite, invite.id).created_by == manager["id"]
    assert invite.server_id == server.id


def test_member_without_manage_invites_cannot_create_invite(
    db_session, create_user
):
    owner, server = _server(db_session, create_user)
    member = create_user()
    _add_member(db_session, server, member)
    db_session.commit()

    _assert_http_error(
        lambda: create_server_invite(db_session, server.id, member["id"]),
        403,
    )


def test_user_without_active_membership_cannot_create_invite(
    db_session, create_user
):
    owner, server = _server(db_session, create_user)
    outsider = create_user()
    left_member = create_user()
    db_session.add(
        ServerMember(
            server_id=server.id,
            user_id=left_member["id"],
            status="LEFT",
            left_at=datetime.now(timezone.utc),
        )
    )
    db_session.commit()

    _assert_http_error(
        lambda: create_server_invite(db_session, server.id, outsider["id"]),
        404,
    )
    _assert_http_error(
        lambda: create_server_invite(
            db_session, server.id, left_member["id"]
        ),
        404,
    )


@pytest.mark.parametrize(
    "expires_at",
    [
        lambda: datetime.now(timezone.utc) - timedelta(seconds=1),
        lambda: datetime.now() + timedelta(days=1),
    ],
    ids=["expired", "naive-datetime"],
)
def test_invalid_expiration_is_rejected(db_session, create_user, expires_at):
    owner, server = _server(db_session, create_user)

    _assert_http_error(
        lambda: create_server_invite(
            db_session,
            server.id,
            owner["id"],
            expires_at=expires_at(),
        ),
        422,
    )
    assert db_session.scalars(select(ServerInvite)).all() == []


@pytest.mark.parametrize("max_uses", [0, -1, True, 1.5])
def test_invalid_max_uses_is_rejected(db_session, create_user, max_uses):
    owner, server = _server(db_session, create_user)

    _assert_http_error(
        lambda: create_server_invite(
            db_session, server.id, owner["id"], max_uses=max_uses
        ),
        422,
    )
    assert db_session.scalars(select(ServerInvite)).all() == []


def test_owner_can_revoke_invite_transactionally(db_session, create_user):
    owner, server = _server(db_session, create_user)
    invite = create_server_invite(db_session, server.id, owner["id"])

    revoked = revoke_server_invite(
        db_session, server.id, invite.id, owner["id"]
    )

    assert revoked.revoked_at is not None
    assert db_session.get(ServerInvite, invite.id).revoked_at is not None


def test_member_with_manage_invites_can_revoke_invite(db_session, create_user):
    owner, server = _server(db_session, create_user)
    manager = create_user()
    _grant_manage_invites(db_session, server, owner, manager)
    invite = create_server_invite(db_session, server.id, owner["id"])

    revoked = revoke_server_invite(
        db_session, server.id, invite.id, manager["id"]
    )

    assert revoked.revoked_at is not None


def test_member_without_manage_invites_cannot_revoke(db_session, create_user):
    owner, server = _server(db_session, create_user)
    member = create_user()
    _add_member(db_session, server, member)
    invite = create_server_invite(db_session, server.id, owner["id"])
    db_session.commit()

    _assert_http_error(
        lambda: revoke_server_invite(
            db_session, server.id, invite.id, member["id"]
        ),
        403,
    )
    assert db_session.get(ServerInvite, invite.id).revoked_at is None


def test_nonexistent_or_foreign_server_invite_is_not_revealed(
    db_session, create_user
):
    owner_a, server_a = _server(db_session, create_user)
    owner_b, server_b = _server(db_session, create_user, name="Outro servidor")
    invite = create_server_invite(
        db_session, server_b.id, owner_b["id"]
    )

    _assert_http_error(
        lambda: revoke_server_invite(
            db_session, server_a.id, invite.id, owner_a["id"]
        ),
        404,
    )
    _assert_http_error(
        lambda: revoke_server_invite(
            db_session, server_a.id, 999999, owner_a["id"]
        ),
        404,
    )


def test_repeated_invite_revocation_returns_conflict(db_session, create_user):
    owner, server = _server(db_session, create_user)
    invite = create_server_invite(db_session, server.id, owner["id"])
    revoke_server_invite(db_session, server.id, invite.id, owner["id"])

    _assert_http_error(
        lambda: revoke_server_invite(
            db_session, server.id, invite.id, owner["id"]
        ),
        409,
    )


def test_create_invite_rolls_back_when_insert_fails(db_session, create_user):
    owner, server = _server(db_session, create_user)
    db_session.commit()
    connection = db_session.connection()

    def fail_invite_insert(conn, cursor, statement, parameters, context, executemany):
        if "insert into server_invites" in statement.lower():
            raise SQLAlchemyError("simulated invite insertion failure")

    event.listen(connection, "before_cursor_execute", fail_invite_insert)
    try:
        _assert_http_error(
            lambda: create_server_invite(db_session, server.id, owner["id"]),
            500,
        )
    finally:
        event.remove(connection, "before_cursor_execute", fail_invite_insert)

    db_session.expire_all()
    assert db_session.scalars(select(ServerInvite)).all() == []


def test_revoke_invite_rolls_back_when_update_fails(db_session, create_user):
    owner, server = _server(db_session, create_user)
    invite = create_server_invite(db_session, server.id, owner["id"])
    invite_id = invite.id
    connection = db_session.connection()

    def fail_invite_update(conn, cursor, statement, parameters, context, executemany):
        if "update server_invites" in statement.lower():
            raise SQLAlchemyError("simulated invite update failure")

    event.listen(connection, "before_cursor_execute", fail_invite_update)
    try:
        _assert_http_error(
            lambda: revoke_server_invite(
                db_session, server.id, invite_id, owner["id"]
            ),
            500,
        )
    finally:
        event.remove(connection, "before_cursor_execute", fail_invite_update)

    db_session.expire_all()
    assert db_session.get(ServerInvite, invite_id).revoked_at is None
