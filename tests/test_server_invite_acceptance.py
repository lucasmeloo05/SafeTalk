from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import event, select
from sqlalchemy.exc import SQLAlchemyError

from app.models import (
    Server,
    ServerBan,
    ServerInvite,
    ServerMember,
    ServerMemberRole,
    ServerRole,
    User,
)
from app.services.server_invite_service import (
    accept_server_invite,
    create_server_invite,
    hash_server_invite_token,
    revoke_server_invite,
)
from app.services.server_member_service import leave_server
from app.services.server_moderation_service import (
    ban_server_member,
    kick_server_member,
    unban_server_member,
)


def _server(db_session, create_user, *, name="Servidor de entrada"):
    owner = create_user()
    server = Server(owner_id=owner["id"], name=name)
    db_session.add(server)
    db_session.flush()
    db_session.add(
        ServerMember(
            server_id=server.id,
            user_id=owner["id"],
            status="ACTIVE",
        )
    )
    db_session.flush()
    return owner, server


def _member(db_session, server, user, *, status="ACTIVE", joined_at=None):
    member = ServerMember(
        server_id=server.id,
        user_id=user["id"],
        status=status,
        joined_at=joined_at or datetime.now(timezone.utc),
        left_at=(datetime.now(timezone.utc) if status == "LEFT" else None),
    )
    db_session.add(member)
    db_session.flush()
    return member


def _assert_http_error(call, expected_status):
    with pytest.raises(HTTPException) as error:
        call()
    assert error.value.status_code == expected_status


def _membership_id(db, response):
    return db.scalars(select(ServerMember.id).where(
        ServerMember.server_id == response.server_id,
        ServerMember.user_id == response.user_id,
        ServerMember.status == response.status,
    )).one()


def _seed_invite(
    db_session,
    server,
    owner,
    token,
    *,
    expires_at=None,
    max_uses=None,
    uses_count=0,
    revoked_at=None,
    created_at=None,
):
    invite = ServerInvite(
        server_id=server.id,
        created_by=owner["id"],
        token_hash=hash_server_invite_token(token),
        expires_at=expires_at,
        max_uses=max_uses,
        uses_count=uses_count,
        revoked_at=revoked_at,
        created_at=created_at or datetime.now(timezone.utc),
    )
    db_session.add(invite)
    db_session.flush()
    return invite


def test_first_invite_entry_creates_active_membership_and_consumes_use(
    db_session, create_user
):
    owner, server = _server(db_session, create_user)
    entrant = create_user()
    invite = create_server_invite(
        db_session, server.id, owner["id"], max_uses=2
    )

    membership = accept_server_invite(
        db_session, server.id, invite.token, entrant["id"]
    )

    assert membership.server_id == server.id
    assert membership.user_id == entrant["id"]
    assert membership.status == "ACTIVE"
    assert membership.left_at is None
    assert membership.joined_at is not None
    assert db_session.get(ServerInvite, invite.id).uses_count == 1
    assert db_session.scalars(
        select(ServerMemberRole).where(
            ServerMemberRole.server_id == server.id,
            ServerMemberRole.member_id == _membership_id(db_session, membership),
        )
    ).all() == []


def test_reentry_after_voluntary_leave_reuses_row_and_updates_joined_at(
    db_session, create_user
):
    owner, server = _server(db_session, create_user)
    user = create_user()
    old_joined_at = datetime.now(timezone.utc) - timedelta(days=10)
    membership = _member(
        db_session, server, user, joined_at=old_joined_at
    )
    db_session.commit()
    leave_server(db_session, db_session.get(User, user["id"]), server.id)
    invite = create_server_invite(db_session, server.id, owner["id"])

    rejoined = accept_server_invite(db_session, server.id, invite.token, user["id"])

    assert _membership_id(db_session, rejoined) == membership.id
    assert rejoined.status == "ACTIVE"
    assert rejoined.left_at is None
    assert rejoined.joined_at > old_joined_at
    assert db_session.get(ServerInvite, invite.id).uses_count == 1


def test_reentry_after_kick_is_allowed_without_ban(db_session, create_user):
    owner, server = _server(db_session, create_user)
    target = create_user()
    membership = _member(db_session, server, target)
    db_session.commit()
    kick_server_member(db_session, server.id, target["id"], owner["id"])
    invite = create_server_invite(db_session, server.id, owner["id"])

    rejoined = accept_server_invite(db_session, server.id, invite.token, target["id"])

    assert _membership_id(db_session, rejoined) == membership.id
    assert rejoined.status == "ACTIVE"
    assert rejoined.left_at is None
    assert db_session.get(ServerInvite, invite.id).uses_count == 1
    assert db_session.scalar(
        select(ServerBan.id).where(
            ServerBan.server_id == server.id,
            ServerBan.user_id == target["id"],
            ServerBan.is_active.is_(True),
        )
    ) is None


def test_active_ban_blocks_entry_without_consuming_invite(db_session, create_user):
    owner, server = _server(db_session, create_user)
    target = create_user()
    membership = _member(db_session, server, target)
    db_session.commit()
    invite = create_server_invite(
        db_session, server.id, owner["id"], max_uses=3
    )
    ban_server_member(db_session, server.id, target["id"], owner["id"])

    _assert_http_error(
        lambda: accept_server_invite(
            db_session, server.id, invite.token, target["id"]
        ),
        403,
    )

    db_session.expire_all()
    assert db_session.get(ServerMember, membership.id).status == "LEFT"
    assert db_session.get(ServerInvite, invite.id).uses_count == 0


def test_entry_is_allowed_after_unban_without_restoring_roles(
    db_session, create_user
):
    owner, server = _server(db_session, create_user)
    target = create_user()
    old_joined_at = datetime.now(timezone.utc) - timedelta(days=3)
    membership = _member(
        db_session, server, target, joined_at=old_joined_at
    )
    db_session.commit()
    invite = create_server_invite(db_session, server.id, owner["id"])
    ban = ban_server_member(db_session, server.id, target["id"], owner["id"])
    unban_server_member(db_session, server.id, ban.id, owner["id"])

    rejoined = accept_server_invite(db_session, server.id, invite.token, target["id"])

    assert _membership_id(db_session, rejoined) == membership.id
    assert rejoined.status == "ACTIVE"
    assert rejoined.left_at is None
    assert rejoined.joined_at > old_joined_at
    assert db_session.get(ServerInvite, invite.id).uses_count == 1
    assert db_session.scalars(
        select(ServerMemberRole).where(
            ServerMemberRole.server_id == server.id,
            ServerMemberRole.member_id == membership.id,
        )
    ).all() == []


def test_reentry_clears_residual_role_assignments_instead_of_restoring_them(
    db_session, create_user
):
    owner, server = _server(db_session, create_user)
    user = create_user()
    membership = _member(
        db_session,
        server,
        user,
        status="LEFT",
        joined_at=datetime.now(timezone.utc) - timedelta(days=4),
    )
    role = ServerRole(
        server_id=server.id,
        name="Atribuição residual",
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
    invite = create_server_invite(db_session, server.id, owner["id"])

    rejoined = accept_server_invite(db_session, server.id, invite.token, user["id"])

    assert rejoined.status == "ACTIVE"
    assert db_session.scalars(
        select(ServerMemberRole).where(
            ServerMemberRole.server_id == server.id,
            ServerMemberRole.member_id == membership.id,
        )
    ).all() == []
    assert db_session.get(ServerInvite, invite.id).uses_count == 1


@pytest.mark.parametrize(
    "failure_kind",
    ["missing", "invalid", "foreign", "expired", "revoked", "exhausted"],
)
def test_unusable_invites_do_not_change_membership_or_usage(
    db_session, create_user, failure_kind
):
    owner, server = _server(db_session, create_user)
    user = create_user()
    membership = _member(db_session, server, user, status="LEFT")
    token = f"invite-token-{failure_kind}"
    expected_status = 404 if failure_kind in {"missing", "invalid", "foreign"} else 409

    if failure_kind == "missing":
        presented = token
    elif failure_kind == "invalid":
        _seed_invite(db_session, server, owner, token)
        presented = "different-token"
    elif failure_kind == "foreign":
        other_owner, other_server = _server(
            db_session, create_user, name="Outro servidor"
        )
        _seed_invite(db_session, other_server, other_owner, token)
        presented = token
    elif failure_kind == "expired":
        created_at = datetime.now(timezone.utc) - timedelta(days=2)
        _seed_invite(
            db_session,
            server,
            owner,
            token,
            created_at=created_at,
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        presented = token
    elif failure_kind == "revoked":
        _seed_invite(
            db_session,
            server,
            owner,
            token,
            revoked_at=datetime.now(timezone.utc),
        )
        presented = token
    else:
        _seed_invite(
            db_session,
            server,
            owner,
            token,
            max_uses=1,
            uses_count=1,
        )
        presented = token

    db_session.commit()
    _assert_http_error(
        lambda: accept_server_invite(
            db_session, server.id, presented, user["id"]
        ),
        expected_status,
    )
    db_session.expire_all()
    assert db_session.get(ServerMember, membership.id).status == "LEFT"
    if failure_kind not in {"missing", "invalid", "foreign"}:
        stored = db_session.scalar(
            select(ServerInvite).where(
                ServerInvite.server_id == server.id,
                ServerInvite.token_hash == hash_server_invite_token(token),
            )
        )
        assert stored.uses_count == (1 if failure_kind == "exhausted" else 0)


def test_active_member_cannot_consume_invite_again(db_session, create_user):
    owner, server = _server(db_session, create_user)
    member_user = create_user()
    membership = _member(db_session, server, member_user)
    invite = create_server_invite(db_session, server.id, owner["id"])

    _assert_http_error(
        lambda: accept_server_invite(
            db_session, server.id, invite.token, member_user["id"]
        ),
        409,
    )

    assert db_session.get(ServerMember, membership.id).status == "ACTIVE"
    assert db_session.get(ServerInvite, invite.id).uses_count == 0


def test_acceptance_rolls_back_member_creation_and_invite_use_on_failure(
    db_session, create_user
):
    owner, server = _server(db_session, create_user)
    entrant = create_user()
    invite = create_server_invite(
        db_session, server.id, owner["id"], max_uses=2
    )
    db_session.commit()
    connection = db_session.connection()

    def fail_invite_update(conn, cursor, statement, parameters, context, executemany):
        if "update server_invites" in statement.lower():
            raise SQLAlchemyError("simulated invite consumption failure")

    event.listen(connection, "before_cursor_execute", fail_invite_update)
    try:
        _assert_http_error(
            lambda: accept_server_invite(
                db_session, server.id, invite.token, entrant["id"]
            ),
            500,
        )
    finally:
        event.remove(connection, "before_cursor_execute", fail_invite_update)

    db_session.expire_all()
    assert db_session.scalar(
        select(ServerMember.id).where(
            ServerMember.server_id == server.id,
            ServerMember.user_id == entrant["id"],
        )
    ) is None
    assert db_session.get(ServerInvite, invite.id).uses_count == 0
