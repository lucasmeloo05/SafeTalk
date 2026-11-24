from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import event, select
from sqlalchemy.exc import SQLAlchemyError

from app.models import (
    Server,
    ServerAuditLog,
    ServerBan,
    ServerMember,
    ServerMemberRole,
    ServerRole,
)
from app.services.server_moderation_service import (
    ban_server_member,
    kick_server_member,
    unban_server_member,
)


def _server(db_session, create_user, *, name="Servidor de moderação"):
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
    return owner, server, owner_membership


def _member(db_session, server, user, *, member_status="ACTIVE"):
    membership = ServerMember(
        server_id=server.id,
        user_id=user["id"],
        status=member_status,
        left_at=(
            datetime.now(timezone.utc) if member_status == "LEFT" else None
        ),
    )
    db_session.add(membership)
    db_session.flush()
    return membership


def _role(db_session, server, *, name, position, permissions=None):
    role = ServerRole(
        server_id=server.id,
        name=name,
        position=position,
        permissions=permissions or {},
        is_default=False,
        is_system_role=False,
    )
    db_session.add(role)
    db_session.flush()
    return role


def _assign(db_session, owner, membership, role):
    assignment = ServerMemberRole(
        server_id=membership.server_id,
        member_id=membership.id,
        role_id=role.id,
        assigned_by=owner["id"],
    )
    db_session.add(assignment)
    db_session.flush()
    return assignment


def _manager(
    db_session,
    create_user,
    owner,
    server,
    *,
    position=10,
    permissions=None,
):
    manager = create_user()
    membership = _member(db_session, server, manager)
    role = _role(
        db_session,
        server,
        name=f"Cargo gestor {manager['id']}",
        position=position,
        permissions=(
            permissions
            if permissions is not None
            else {"kick_members": True}
        ),
    )
    _assign(db_session, owner, membership, role)
    return manager, membership, role


def _target_with_role(db_session, create_user, owner, server, *, position=2):
    target = create_user()
    membership = _member(db_session, server, target)
    role = _role(
        db_session,
        server,
        name=f"Cargo alvo {target['id']}",
        position=position,
        permissions={"mention_everyone": True},
    )
    assignment = _assign(db_session, owner, membership, role)
    return target, membership, role, assignment


def _assert_http_error(call, expected_status):
    with pytest.raises(HTTPException) as error:
        call()
    assert error.value.status_code == expected_status


def _audit_rows(db_session, server_id, event_type):
    return db_session.scalars(
        select(ServerAuditLog).where(
            ServerAuditLog.server_id == server_id,
            ServerAuditLog.event_type == event_type,
        )
    ).all()


def test_owner_kicks_member_and_audits_snapshot_without_creating_ban(
    db_session, create_user
):
    owner, server, _owner_member = _server(db_session, create_user)
    target, target_member, role, assignment = _target_with_role(
        db_session, create_user, owner, server
    )

    audit = kick_server_member(
        db_session, server.id, target["id"], owner["id"], "Motivo opcional"
    )

    db_session.expire_all()
    assert db_session.get(ServerMember, target_member.id).status == "LEFT"
    assert db_session.get(ServerMember, target_member.id).left_at is not None
    assert db_session.get(ServerMemberRole, assignment.id) is None
    assert db_session.scalar(
        select(ServerBan.id).where(ServerBan.server_id == server.id)
    ) is None
    assert audit.event_type == "MEMBER_KICKED"
    assert audit.actor_user_id == owner["id"]
    assert audit.target_user_id == target["id"]
    assert audit.reason == "Motivo opcional"
    assert audit.ban_id is None
    assert audit.role_snapshot[0]["role"] == {
        "id": role.id,
        "server_id": server.id,
        "name": role.name,
        "description": role.description,
        "position": role.position,
        "permissions": role.permissions,
        "is_default": role.is_default,
        "is_system_role": role.is_system_role,
        "created_at": role.created_at.isoformat(),
    }
    assert audit.role_snapshot[0]["assignment"]["assigned_at"] == (
        assignment.assigned_at.isoformat()
    )


@pytest.mark.parametrize(
    "permissions,actor_position,target_position,expected_status",
    [
        ({}, 10, 2, 403),
        ({"kick_members": True}, 2, 2, 403),
        ({"kick_members": True}, 2, 5, 403),
        ({"kick_members": True}, 10, 2, None),
    ],
)
def test_kick_requires_independent_permission_and_strict_hierarchy(
    db_session,
    create_user,
    permissions,
    actor_position,
    target_position,
    expected_status,
):
    owner, server, _ = _server(db_session, create_user)
    manager, _manager_member, _manager_role = _manager(
        db_session,
        create_user,
        owner,
        server,
        position=actor_position,
        permissions=permissions,
    )
    target, _target_member, _target_role, _assignment = _target_with_role(
        db_session,
        create_user,
        owner,
        server,
        position=target_position,
    )
    db_session.commit()

    call = lambda: kick_server_member(
        db_session, server.id, target["id"], manager["id"]
    )
    if expected_status is None:
        result = call()
        assert result.event_type == "MEMBER_KICKED"
    else:
        _assert_http_error(call, expected_status)
        assert db_session.scalar(
            select(ServerMemberRole.id).where(
                ServerMemberRole.member_id == _target_member.id
            )
        ) is not None
        assert _audit_rows(db_session, server.id, "MEMBER_KICKED") == []


@pytest.mark.parametrize("operation", ["kick", "ban"])
def test_moderation_cannot_target_actor_or_owner(
    db_session, create_user, operation
):
    owner, server, _ = _server(db_session, create_user)
    manager, _membership, _role = _manager(db_session, create_user, owner, server)
    target, _member_row, _role_row, _assignment = _target_with_role(
        db_session, create_user, owner, server
    )
    service = kick_server_member if operation == "kick" else ban_server_member
    db_session.commit()

    _assert_http_error(
        lambda: service(db_session, server.id, manager["id"], manager["id"]),
        403,
    )
    _assert_http_error(
        lambda: service(db_session, server.id, owner["id"], manager["id"]),
        403,
    )
    assert db_session.scalar(
        select(ServerMember.status).where(
            ServerMember.server_id == server.id,
            ServerMember.user_id == target["id"],
        )
    ) == "ACTIVE"


@pytest.mark.parametrize("operation", ["kick", "ban"])
def test_kick_or_ban_rejects_missing_server_target_left_target_and_left_actor(
    db_session, create_user, operation
):
    owner, server, _ = _server(db_session, create_user)
    actor, actor_membership, _role = _manager(
        db_session,
        create_user,
        owner,
        server,
        permissions={f"{operation}_members": True},
    )
    active_target = create_user()
    _member(db_session, server, active_target)
    left_target_user = create_user()
    _member(db_session, server, left_target_user, member_status="LEFT")
    service = kick_server_member if operation == "kick" else ban_server_member
    db_session.commit()

    _assert_http_error(
        lambda: service(db_session, server.id + 99999, active_target["id"], actor["id"]),
        404,
    )
    _assert_http_error(
        lambda: service(db_session, server.id, 999999, actor["id"]), 404
    )
    _foreign_owner, foreign_server, _ = _server(
        db_session, create_user, name="Outro servidor"
    )
    foreign_target = create_user()
    _member(db_session, foreign_server, foreign_target)
    db_session.commit()
    _assert_http_error(
        lambda: service(
            db_session, server.id, foreign_target["id"], actor["id"]
        ),
        404,
    )
    _assert_http_error(
        lambda: service(
            db_session, server.id, left_target_user["id"], actor["id"]
        ),
        409,
    )

    actor_membership.status = "LEFT"
    actor_membership.left_at = datetime.now(timezone.utc)
    db_session.flush()
    db_session.commit()
    _assert_http_error(
        lambda: service(
            db_session, server.id, active_target["id"], actor["id"]
        ),
        404,
    )


def test_owner_bans_member_without_roles_using_zero_snapshot(
    db_session, create_user
):
    owner, server, _ = _server(db_session, create_user)
    target = create_user()
    target_membership = _member(db_session, server, target)

    ban = ban_server_member(
        db_session, server.id, target["id"], owner["id"], "Banimento"
    )

    db_session.expire_all()
    assert ban.server_id == server.id
    assert ban.user_id == target["id"]
    assert ban.banned_by == owner["id"]
    assert ban.is_active is True
    assert ban.reason == "Banimento"
    assert db_session.get(ServerBan, ban.id).target_highest_role_position == 0
    assert db_session.get(ServerMember, target_membership.id).status == "LEFT"
    assert db_session.get(ServerMember, target_membership.id).left_at is not None
    audits = _audit_rows(db_session, server.id, "MEMBER_BANNED")
    assert len(audits) == 1
    assert audits[0].ban_id == ban.id
    assert audits[0].role_snapshot == []


def test_ban_captures_highest_position_and_full_role_assignment_snapshot(
    db_session, create_user
):
    owner, server, _ = _server(db_session, create_user)
    target = create_user()
    membership = _member(db_session, server, target)
    first_role = _role(
        db_session,
        server,
        name="Primeiro",
        position=3,
        permissions={"mention_everyone": True},
    )
    highest_role = _role(
        db_session,
        server,
        name="Mais alto",
        position=8,
        permissions={"kick_members": True, "ban_members": False},
    )
    first_assignment = _assign(db_session, owner, membership, first_role)
    highest_assignment = _assign(db_session, owner, membership, highest_role)

    ban = ban_server_member(db_session, server.id, target["id"], owner["id"])
    audit = db_session.scalar(
        select(ServerAuditLog).where(
            ServerAuditLog.server_id == server.id,
            ServerAuditLog.event_type == "MEMBER_BANNED",
        )
    )

    assert db_session.get(ServerBan, ban.id).target_highest_role_position == 8
    assert len(audit.role_snapshot) == 2
    assert [entry["role"]["position"] for entry in audit.role_snapshot] == [3, 8]
    assert {entry["assignment"]["id"] for entry in audit.role_snapshot} == {
        first_assignment.id,
        highest_assignment.id,
    }
    assert all(
        entry["role"]["permissions"]
        for entry in audit.role_snapshot
    )
    assert db_session.scalars(
        select(ServerMemberRole).where(
            ServerMemberRole.server_id == server.id,
            ServerMemberRole.member_id == membership.id,
        )
    ).all() == []


def test_common_member_needs_ban_members_and_strict_hierarchy(
    db_session, create_user
):
    owner, server, _ = _server(db_session, create_user)
    actor, _actor_member, _actor_role = _manager(
        db_session,
        create_user,
        owner,
        server,
        position=3,
        permissions={"kick_members": True},
    )
    target, _target_member, _target_role, _assignment = _target_with_role(
        db_session, create_user, owner, server, position=3
    )
    db_session.commit()

    _assert_http_error(
        lambda: ban_server_member(db_session, server.id, target["id"], actor["id"]),
        403,
    )
    actor_role = _role(
        db_session,
        server,
        name="Grant de ban",
        position=3,
        permissions={"ban_members": True},
    )
    actor_membership = db_session.scalar(
        select(ServerMember).where(
            ServerMember.server_id == server.id,
            ServerMember.user_id == actor["id"],
        )
    )
    _assign(db_session, owner, actor_membership, actor_role)
    db_session.commit()
    _assert_http_error(
        lambda: ban_server_member(db_session, server.id, target["id"], actor["id"]),
        403,
    )
    assert _audit_rows(db_session, server.id, "MEMBER_BANNED") == []


def test_common_member_can_ban_with_permission_and_higher_hierarchy(
    db_session, create_user
):
    owner, server, _ = _server(db_session, create_user)
    manager, _membership, _role_row = _manager(
        db_session,
        create_user,
        owner,
        server,
        position=9,
        permissions={"ban_members": True},
    )
    target, _target_member, _target_role, _assignment = _target_with_role(
        db_session, create_user, owner, server, position=2
    )

    ban = ban_server_member(db_session, server.id, target["id"], manager["id"])

    assert ban.is_active is True
    assert ban.banned_by == manager["id"]
    assert db_session.get(ServerBan, ban.id).target_highest_role_position == 2
    assert len(_audit_rows(db_session, server.id, "MEMBER_BANNED")) == 1


def test_duplicate_active_ban_is_conflict_and_does_not_audit_twice(
    db_session, create_user
):
    owner, server, _ = _server(db_session, create_user)
    target = create_user()
    target_membership = _member(db_session, server, target)
    existing = ServerBan(
        server_id=server.id,
        user_id=target["id"],
        banned_by=owner["id"],
        target_highest_role_position=0,
    )
    db_session.add(existing)
    db_session.flush()
    db_session.commit()

    _assert_http_error(
        lambda: ban_server_member(
            db_session, server.id, target["id"], owner["id"]
        ),
        409,
    )
    db_session.expire_all()
    assert db_session.get(ServerMember, target_membership.id).status == "ACTIVE"
    assert len(
        db_session.scalars(
            select(ServerBan).where(
                ServerBan.server_id == server.id,
                ServerBan.user_id == target["id"],
                ServerBan.is_active.is_(True),
            )
        ).all()
    ) == 1
    assert _audit_rows(db_session, server.id, "MEMBER_BANNED") == []


def _active_ban_for_unban(db_session, owner, server, target, *, position):
    return ServerBan(
        server_id=server.id,
        user_id=target["id"],
        banned_by=owner["id"],
        is_active=True,
        target_highest_role_position=position,
    )


def test_owner_unbans_without_reactivating_or_restoring_roles(
    db_session, create_user
):
    owner, server, _ = _server(db_session, create_user)
    target, target_membership, role, assignment = _target_with_role(
        db_session, create_user, owner, server
    )
    ban = ban_server_member(db_session, server.id, target["id"], owner["id"])
    ban_id = ban.id

    result = unban_server_member(
        db_session, server.id, ban_id, owner["id"], "Revogação"
    )

    db_session.expire_all()
    stored_ban = db_session.get(ServerBan, ban_id)
    assert stored_ban.is_active is False
    assert stored_ban.revoked_by == owner["id"]
    assert stored_ban.revoked_at is not None
    assert result.id == ban_id
    assert db_session.get(ServerMember, target_membership.id).status == "LEFT"
    assert db_session.get(ServerMemberRole, assignment.id) is None
    audit = _audit_rows(db_session, server.id, "MEMBER_UNBANNED")
    assert len(audit) == 1
    assert audit[0].ban_id == ban_id
    assert audit[0].target_user_id == target["id"]
    assert audit[0].reason == "Revogação"
    assert audit[0].role_snapshot is None
    assert role.id not in [entry.get("role_id") for entry in audit[0].role_snapshot or []]


@pytest.mark.parametrize(
    "actor_position,target_snapshot,expected_status",
    [(9, 8, None), (8, 8, 403), (7, 8, 403)],
)
def test_common_unban_permission_uses_historical_position(
    db_session,
    create_user,
    actor_position,
    target_snapshot,
    expected_status,
):
    owner, server, _ = _server(db_session, create_user)
    actor, _actor_member, _actor_role = _manager(
        db_session,
        create_user,
        owner,
        server,
        position=actor_position,
        permissions={"unban_members": True},
    )
    target = create_user()
    _member(db_session, server, target, member_status="LEFT")
    ban = _active_ban_for_unban(
        db_session, owner, server, target, position=target_snapshot
    )
    db_session.add(ban)
    db_session.flush()
    db_session.commit()

    call = lambda: unban_server_member(
        db_session, server.id, ban.id, actor["id"]
    )
    if expected_status is None:
        result = call()
        assert result.is_active is False
        assert result.revoked_by == actor["id"]
    else:
        _assert_http_error(call, expected_status)
        assert db_session.get(ServerBan, ban.id).is_active is True
        assert _audit_rows(db_session, server.id, "MEMBER_UNBANNED") == []


def test_unban_uses_ban_snapshot_after_target_roles_are_gone(
    db_session, create_user
):
    owner, server, _ = _server(db_session, create_user)
    manager, manager_membership, _manager_role = _manager(
        db_session,
        create_user,
        owner,
        server,
        position=6,
        permissions={"unban_members": True},
    )
    target = create_user()
    _member(db_session, server, target, member_status="LEFT")
    ban = _active_ban_for_unban(
        db_session, owner, server, target, position=5
    )
    db_session.add(ban)
    db_session.flush()
    higher_current_role = _role(
        db_session,
        server,
        name="Alteração posterior do alvo",
        position=999,
    )
    target_member = db_session.scalar(
        select(ServerMember).where(
            ServerMember.server_id == server.id,
            ServerMember.user_id == target["id"],
        )
    )
    _assign(db_session, owner, target_member, higher_current_role)
    db_session.commit()

    result = unban_server_member(db_session, server.id, ban.id, manager["id"])

    assert result.is_active is False
    assert result.target_highest_role_position == 5
    assert db_session.get(ServerMember, manager_membership.id).status == "ACTIVE"


@pytest.mark.parametrize("ban_state,expected_status", [("missing", 404), ("revoked", 409)])
def test_unban_rejects_missing_or_already_revoked_cycle(
    db_session, create_user, ban_state, expected_status
):
    owner, server, _ = _server(db_session, create_user)
    target = create_user()
    _member(db_session, server, target, member_status="LEFT")
    if ban_state == "missing":
        ban_id = 999999
    else:
        ban = _active_ban_for_unban(db_session, owner, server, target, position=0)
        ban.is_active = False
        ban.revoked_at = datetime.now(timezone.utc)
        ban.revoked_by = owner["id"]
        db_session.add(ban)
        db_session.flush()
        ban_id = ban.id
    db_session.commit()

    _assert_http_error(
        lambda: unban_server_member(db_session, server.id, ban_id, owner["id"]),
        expected_status,
    )
    assert _audit_rows(db_session, server.id, "MEMBER_UNBANNED") == []


def test_unban_requires_active_actor_and_owner_exception_is_separate(
    db_session, create_user
):
    owner, server, _ = _server(db_session, create_user)
    actor = create_user()
    _member(db_session, server, actor, member_status="LEFT")
    target = create_user()
    _member(db_session, server, target, member_status="LEFT")
    ban = _active_ban_for_unban(db_session, owner, server, target, position=0)
    db_session.add(ban)
    db_session.flush()
    db_session.commit()

    _assert_http_error(
        lambda: unban_server_member(db_session, server.id, ban.id, actor["id"]),
        404,
    )
    assert unban_server_member(db_session, server.id, ban.id, owner["id"]).is_active is False


@pytest.mark.parametrize("operation", ["kick", "ban"])
def test_moderation_rolls_back_member_roles_and_audit_on_audit_failure(
    db_session, create_user, operation
):
    owner, server, _ = _server(db_session, create_user)
    target, membership, _role_row, assignment = _target_with_role(
        db_session, create_user, owner, server
    )
    service = kick_server_member if operation == "kick" else ban_server_member
    # Persist setup separately so service rollback only undoes the operation.
    db_session.commit()
    connection = db_session.connection()

    def fail_audit_insert(conn, cursor, statement, parameters, context, executemany):
        if "insert into server_audit_logs" in statement.lower():
            raise SQLAlchemyError("simulated moderation audit failure")

    event.listen(connection, "before_cursor_execute", fail_audit_insert)
    try:
        _assert_http_error(
            lambda: service(db_session, server.id, target["id"], owner["id"]),
            500,
        )
    finally:
        event.remove(connection, "before_cursor_execute", fail_audit_insert)

    db_session.expire_all()
    assert db_session.get(ServerMember, membership.id).status == "ACTIVE"
    assert db_session.get(ServerMemberRole, assignment.id) is not None
    assert db_session.scalar(
        select(ServerBan.id).where(ServerBan.server_id == server.id)
    ) is None
    assert _audit_rows(db_session, server.id, "MEMBER_KICKED") == []
    assert _audit_rows(db_session, server.id, "MEMBER_BANNED") == []


def test_unban_rolls_back_ban_revocation_when_audit_fails(
    db_session, create_user
):
    owner, server, _ = _server(db_session, create_user)
    target = create_user()
    _member(db_session, server, target, member_status="LEFT")
    ban = _active_ban_for_unban(db_session, owner, server, target, position=0)
    db_session.add(ban)
    db_session.flush()
    ban_id = ban.id
    db_session.commit()
    connection = db_session.connection()

    def fail_audit_insert(conn, cursor, statement, parameters, context, executemany):
        if "insert into server_audit_logs" in statement.lower():
            raise SQLAlchemyError("simulated unban audit failure")

    event.listen(connection, "before_cursor_execute", fail_audit_insert)
    try:
        _assert_http_error(
            lambda: unban_server_member(db_session, server.id, ban_id, owner["id"]),
            500,
        )
    finally:
        event.remove(connection, "before_cursor_execute", fail_audit_insert)

    db_session.expire_all()
    assert db_session.get(ServerBan, ban_id).is_active is True
    assert db_session.get(ServerBan, ban_id).revoked_at is None
    assert _audit_rows(db_session, server.id, "MEMBER_UNBANNED") == []
