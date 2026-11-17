import json
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import event, select
from sqlalchemy.exc import SQLAlchemyError

from app.models import (
    Server,
    ServerConfigHistory,
    ServerMember,
    ServerMemberRole,
    ServerRole,
)
from app.services.server_authorization_service import resolve_server_permissions
from app.services.server_role_service import (
    assign_server_role_to_member,
    remove_server_role_from_member,
)


def _server(db_session, create_user):
    owner = create_user()
    server = Server(owner_id=owner["id"], name="Servidor de atribuições")
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


def _role(
    db_session,
    server,
    *,
    name,
    position,
    permissions=None,
    is_default=False,
    is_system_role=False,
):
    role = ServerRole(
        server_id=server.id,
        name=name,
        position=position,
        permissions=permissions or {},
        is_default=is_default,
        is_system_role=is_system_role,
    )
    db_session.add(role)
    db_session.flush()
    return role


def _assign(db_session, server, membership, role, assigned_by):
    assignment = ServerMemberRole(
        server_id=server.id,
        member_id=membership.id,
        role_id=role.id,
        assigned_by=assigned_by,
    )
    db_session.add(assignment)
    db_session.flush()
    return assignment


def _manager(db_session, create_user, owner, server, *, position=10):
    manager = create_user()
    membership = _member(db_session, server, manager)
    manager_role = _role(
        db_session,
        server,
        name=f"Gestor {manager['id']}",
        position=position,
        permissions={"manage_roles": True},
    )
    _assign(db_session, server, membership, manager_role, owner["id"])
    return manager, membership, manager_role


def _assert_http_error(call, expected_status):
    with pytest.raises(HTTPException) as error:
        call()
    assert error.value.status_code == expected_status


def _audit_rows(db_session, server_id, member_id, role_id):
    return db_session.scalars(
        select(ServerConfigHistory).where(
            ServerConfigHistory.server_id == server_id,
            ServerConfigHistory.setting_name
            == f"server_member_role:{member_id}:{role_id}",
        )
    ).all()


def test_owner_assigns_normal_role_and_audit_contains_authenticated_actor(
    db_session, create_user
):
    owner, server, owner_membership = _server(db_session, create_user)
    target = create_user()
    target_membership = _member(db_session, server, target)
    role = _role(
        db_session,
        server,
        name="Padrão marcado",
        position=1,
        is_default=True,
    )

    assign_server_role_to_member(
        db_session, server.id, target["id"], role.id, owner["id"]
    )

    assignment = db_session.scalar(
        select(ServerMemberRole).where(
            ServerMemberRole.server_id == server.id,
            ServerMemberRole.member_id == target_membership.id,
            ServerMemberRole.role_id == role.id,
        )
    )
    assert assignment is not None
    assert assignment.assigned_by == owner["id"]
    assert assignment.member_id != owner_membership.id
    audit = _audit_rows(db_session, server.id, target_membership.id, role.id)
    assert len(audit) == 1
    assert audit[0].changed_by == owner["id"]
    assert json.loads(audit[0].old_value) is None
    assert json.loads(audit[0].new_value) == {
        "server_id": server.id,
        "member_id": target_membership.id,
        "role_id": role.id,
        "assigned_at": assignment.assigned_at.isoformat(),
        "assigned_by": owner["id"],
    }


def test_manager_assigns_lower_role_to_member_below_hierarchy(
    db_session, create_user
):
    owner, server, _ = _server(db_session, create_user)
    manager, _, _ = _manager(db_session, create_user, owner, server)
    target = create_user()
    target_membership = _member(db_session, server, target)
    role = _role(db_session, server, name="Cargo inferior", position=5)

    assign_server_role_to_member(
        db_session, server.id, target["id"], role.id, manager["id"]
    )

    assert db_session.scalar(
        select(ServerMemberRole.id).where(
            ServerMemberRole.server_id == server.id,
            ServerMemberRole.member_id == target_membership.id,
            ServerMemberRole.role_id == role.id,
        )
    ) is not None


def test_manager_without_manage_roles_is_forbidden(db_session, create_user):
    owner, server, _ = _server(db_session, create_user)
    actor = create_user()
    _member(db_session, server, actor)
    target = create_user()
    _member(db_session, server, target)
    role = _role(db_session, server, name="Cargo", position=1)

    _assert_http_error(
        lambda: assign_server_role_to_member(
            db_session, server.id, target["id"], role.id, actor["id"]
        ),
        403,
    )


@pytest.mark.parametrize("manager_position", [5, 4])
def test_manager_must_be_strictly_above_role(
    db_session, create_user, manager_position
):
    owner, server, _ = _server(db_session, create_user)
    manager, _, _ = _manager(
        db_session, create_user, owner, server, position=manager_position
    )
    target = create_user()
    _member(db_session, server, target)
    role = _role(db_session, server, name="Cargo", position=5)

    _assert_http_error(
        lambda: assign_server_role_to_member(
            db_session, server.id, target["id"], role.id, manager["id"]
        ),
        403,
    )


def test_left_actor_cannot_assign_role(db_session, create_user):
    owner, server, _ = _server(db_session, create_user)
    actor = create_user()
    _member(db_session, server, actor, member_status="LEFT")
    target = create_user()
    _member(db_session, server, target)
    role = _role(db_session, server, name="Cargo", position=1)

    _assert_http_error(
        lambda: assign_server_role_to_member(
            db_session, server.id, target["id"], role.id, actor["id"]
        ),
        404,
    )


@pytest.mark.parametrize("target_status", ["LEFT", "MISSING"])
def test_inactive_or_missing_target_cannot_receive_role(
    db_session, create_user, target_status
):
    owner, server, _ = _server(db_session, create_user)
    target = create_user()
    if target_status == "LEFT":
        _member(db_session, server, target, member_status="LEFT")
    role = _role(db_session, server, name="Cargo", position=1)

    _assert_http_error(
        lambda: assign_server_role_to_member(
            db_session, server.id, target["id"], role.id, owner["id"]
        ),
        404,
    )


def test_foreign_server_role_is_not_revealed_or_assigned(
    db_session, create_user
):
    owner, server, _ = _server(db_session, create_user)
    _, other_server, _ = _server(db_session, create_user)
    target = create_user()
    _member(db_session, server, target)
    role = _role(db_session, other_server, name="Cargo alheio", position=1)

    _assert_http_error(
        lambda: assign_server_role_to_member(
            db_session, server.id, target["id"], role.id, owner["id"]
        ),
        404,
    )


def test_system_role_cannot_be_assigned_even_by_owner(db_session, create_user):
    owner, server, _ = _server(db_session, create_user)
    target = create_user()
    _member(db_session, server, target)
    role = _role(
        db_session,
        server,
        name="Sistema",
        position=1,
        is_system_role=True,
    )

    _assert_http_error(
        lambda: assign_server_role_to_member(
            db_session, server.id, target["id"], role.id, owner["id"]
        ),
        403,
    )


def test_common_member_cannot_assign_role_to_owner(db_session, create_user):
    owner, server, _ = _server(db_session, create_user)
    manager, _, _ = _manager(db_session, create_user, owner, server)
    role = _role(db_session, server, name="Cargo", position=1)

    _assert_http_error(
        lambda: assign_server_role_to_member(
            db_session, server.id, owner["id"], role.id, manager["id"]
        ),
        403,
    )


def test_self_assignment_of_lower_role_is_allowed(db_session, create_user):
    owner, server, _ = _server(db_session, create_user)
    manager, membership, _ = _manager(db_session, create_user, owner, server)
    role = _role(db_session, server, name="Cargo inferior", position=5)

    assign_server_role_to_member(
        db_session, server.id, manager["id"], role.id, manager["id"]
    )

    assert db_session.scalar(
        select(ServerMemberRole.id).where(
            ServerMemberRole.server_id == server.id,
            ServerMemberRole.member_id == membership.id,
            ServerMemberRole.role_id == role.id,
        )
    ) is not None


def test_assignment_cannot_grant_effective_permission_actor_lacks(
    db_session, create_user
):
    owner, server, _ = _server(db_session, create_user)
    manager, _, _ = _manager(db_session, create_user, owner, server)
    target = create_user()
    _member(db_session, server, target)
    role = _role(
        db_session,
        server,
        name="Banimento",
        position=5,
        permissions={"ban_members": True},
    )

    _assert_http_error(
        lambda: assign_server_role_to_member(
            db_session, server.id, target["id"], role.id, manager["id"]
        ),
        403,
    )


def test_existing_target_grant_from_another_role_is_not_revoked(
    db_session, create_user
):
    owner, server, _ = _server(db_session, create_user)
    manager, _, _ = _manager(db_session, create_user, owner, server)
    target = create_user()
    target_membership = _member(db_session, server, target)
    preexisting_role = _role(
        db_session,
        server,
        name="Grant existente",
        position=2,
        permissions={"ban_members": True},
    )
    _assign(db_session, server, target_membership, preexisting_role, owner["id"])
    role = _role(
        db_session,
        server,
        name="Mesmo grant",
        position=5,
        permissions={"ban_members": False},
    )

    assign_server_role_to_member(
        db_session, server.id, target["id"], role.id, manager["id"]
    )

    assert db_session.scalar(
        select(ServerMemberRole.id).where(
            ServerMemberRole.server_id == server.id,
            ServerMemberRole.member_id == target_membership.id,
            ServerMemberRole.role_id == role.id,
        )
    ) is not None
    assert "ban_members" in resolve_server_permissions(
        db_session, server.id, target["id"]
    ).permissions


def test_target_at_or_above_manager_hierarchy_cannot_receive_role(
    db_session, create_user
):
    owner, server, _ = _server(db_session, create_user)
    manager, _, _ = _manager(db_session, create_user, owner, server)
    target = create_user()
    target_membership = _member(db_session, server, target)
    target_role = _role(db_session, server, name="Alvo hierárquico", position=10)
    _assign(db_session, server, target_membership, target_role, owner["id"])
    role = _role(db_session, server, name="Cargo novo", position=5)

    _assert_http_error(
        lambda: assign_server_role_to_member(
            db_session, server.id, target["id"], role.id, manager["id"]
        ),
        403,
    )


def test_duplicate_assignment_is_idempotent_without_duplicate_audit(
    db_session, create_user
):
    owner, server, _ = _server(db_session, create_user)
    target = create_user()
    target_membership = _member(db_session, server, target)
    role = _role(db_session, server, name="Cargo", position=1)

    assign_server_role_to_member(
        db_session, server.id, target["id"], role.id, owner["id"]
    )
    assign_server_role_to_member(
        db_session, server.id, target["id"], role.id, owner["id"]
    )

    assert len(
        db_session.scalars(
            select(ServerMemberRole).where(
                ServerMemberRole.member_id == target_membership.id,
                ServerMemberRole.role_id == role.id,
            )
        ).all()
    ) == 1
    assert len(_audit_rows(db_session, server.id, target_membership.id, role.id)) == 1


def test_owner_removes_normal_role_and_audits_snapshot(db_session, create_user):
    owner, server, _ = _server(db_session, create_user)
    target = create_user()
    target_membership = _member(db_session, server, target)
    role = _role(db_session, server, name="Cargo", position=1)
    assignment = _assign(db_session, server, target_membership, role, owner["id"])
    expected_snapshot = {
        "server_id": server.id,
        "member_id": target_membership.id,
        "role_id": role.id,
        "assigned_at": assignment.assigned_at.isoformat(),
        "assigned_by": owner["id"],
    }

    remove_server_role_from_member(
        db_session, server.id, target["id"], role.id, owner["id"]
    )

    assert db_session.get(ServerMemberRole, assignment.id) is None
    audit = _audit_rows(db_session, server.id, target_membership.id, role.id)
    assert len(audit) == 1
    assert audit[0].changed_by == owner["id"]
    assert json.loads(audit[0].old_value) == expected_snapshot
    assert json.loads(audit[0].new_value) == {"removed": True}


def test_manager_removes_lower_role_from_lower_member(db_session, create_user):
    owner, server, _ = _server(db_session, create_user)
    manager, _, _ = _manager(db_session, create_user, owner, server)
    target = create_user()
    membership = _member(db_session, server, target)
    role = _role(db_session, server, name="Cargo inferior", position=5)
    assignment = _assign(db_session, server, membership, role, owner["id"])

    remove_server_role_from_member(
        db_session, server.id, target["id"], role.id, manager["id"]
    )

    assert db_session.get(ServerMemberRole, assignment.id) is None


def test_manager_without_permission_or_hierarchy_cannot_remove(
    db_session, create_user
):
    owner, server, _ = _server(db_session, create_user)
    actor = create_user()
    _member(db_session, server, actor)
    target = create_user()
    membership = _member(db_session, server, target)
    role = _role(db_session, server, name="Cargo", position=1)
    assignment = _assign(db_session, server, membership, role, owner["id"])
    existing_audit = ServerConfigHistory(
        server_id=server.id,
        changed_by=owner["id"],
        setting_name=(
            f"server_member_role:{membership.id}:{role.id}"
        ),
        old_value="null",
        new_value=json.dumps(
            {
                "server_id": server.id,
                "member_id": membership.id,
                "role_id": role.id,
                "assigned_at": assignment.assigned_at.isoformat(),
                "assigned_by": owner["id"],
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
    )
    db_session.add(existing_audit)
    db_session.commit()

    _assert_http_error(
        lambda: remove_server_role_from_member(
            db_session, server.id, target["id"], role.id, actor["id"]
        ),
        403,
    )
    db_session.expire_all()
    assert db_session.get(ServerMemberRole, assignment.id) is not None
    preserved_audits = _audit_rows(db_session, server.id, membership.id, role.id)
    assert len(preserved_audits) == 1
    assert preserved_audits[0].changed_by == owner["id"]
    assert preserved_audits[0].old_value == "null"
    assert json.loads(preserved_audits[0].new_value)["role_id"] == role.id


@pytest.mark.parametrize("manager_position", [1, 5])
def test_manager_cannot_remove_role_at_or_above_own_hierarchy(
    db_session, create_user, manager_position
):
    owner, server, _ = _server(db_session, create_user)
    manager, _, _ = _manager(
        db_session, create_user, owner, server, position=manager_position
    )
    target = create_user()
    membership = _member(db_session, server, target)
    role = _role(db_session, server, name="Cargo protegido", position=5)
    assignment = _assign(db_session, server, membership, role, owner["id"])
    db_session.commit()

    _assert_http_error(
        lambda: remove_server_role_from_member(
            db_session, server.id, target["id"], role.id, manager["id"]
        ),
        403,
    )
    assert db_session.get(ServerMemberRole, assignment.id) is not None


def test_left_target_cannot_be_modified(db_session, create_user):
    owner, server, _ = _server(db_session, create_user)
    target = create_user()
    target_membership = _member(db_session, server, target)
    role = _role(db_session, server, name="Cargo", position=1)
    assignment = _assign(db_session, server, target_membership, role, owner["id"])
    target_membership.status = "LEFT"
    target_membership.left_at = datetime.now(timezone.utc)
    db_session.commit()

    _assert_http_error(
        lambda: remove_server_role_from_member(
            db_session, server.id, target["id"], role.id, owner["id"]
        ),
        404,
    )
    assert db_session.get(ServerMemberRole, assignment.id) is not None


def test_system_role_cannot_be_removed_even_by_owner(db_session, create_user):
    owner, server, _ = _server(db_session, create_user)
    target = create_user()
    membership = _member(db_session, server, target)
    role = _role(
        db_session,
        server,
        name="Sistema",
        position=1,
        is_system_role=True,
    )
    assignment = _assign(db_session, server, membership, role, owner["id"])
    db_session.commit()

    _assert_http_error(
        lambda: remove_server_role_from_member(
            db_session, server.id, target["id"], role.id, owner["id"]
        ),
        403,
    )
    assert db_session.get(ServerMemberRole, assignment.id) is not None


def test_common_member_cannot_remove_owner_role(db_session, create_user):
    owner, server, owner_membership = _server(db_session, create_user)
    manager, _, _ = _manager(db_session, create_user, owner, server)
    role = _role(db_session, server, name="Cargo", position=1)
    assignment = _assign(db_session, server, owner_membership, role, owner["id"])
    db_session.commit()

    _assert_http_error(
        lambda: remove_server_role_from_member(
            db_session, server.id, owner["id"], role.id, manager["id"]
        ),
        403,
    )
    assert db_session.get(ServerMemberRole, assignment.id) is not None


def test_self_removal_is_allowed_and_absent_removal_is_idempotent(
    db_session, create_user
):
    owner, server, _ = _server(db_session, create_user)
    manager, membership, _ = _manager(db_session, create_user, owner, server)
    role = _role(db_session, server, name="Cargo inferior", position=5)
    assignment = _assign(db_session, server, membership, role, owner["id"])

    remove_server_role_from_member(
        db_session, server.id, manager["id"], role.id, manager["id"]
    )
    remove_server_role_from_member(
        db_session, server.id, manager["id"], role.id, manager["id"]
    )

    assert db_session.get(ServerMemberRole, assignment.id) is None
    assert len(_audit_rows(db_session, server.id, membership.id, role.id)) == 1


def test_audit_failure_rolls_back_assignment_and_removal(
    db_session, create_user, monkeypatch
):
    owner, server, _ = _server(db_session, create_user)
    target = create_user()
    membership = _member(db_session, server, target)
    role = _role(db_session, server, name="Cargo", position=1)
    db_session.commit()

    original_flush = db_session.flush
    flush_count = 0

    def fail_audit_flush(*args, **kwargs):
        nonlocal flush_count
        flush_count += 1
        if flush_count == 2:
            raise SQLAlchemyError("falha simulada ao gravar auditoria")
        return original_flush(*args, **kwargs)

    monkeypatch.setattr(db_session, "flush", fail_audit_flush)
    _assert_http_error(
        lambda: assign_server_role_to_member(
            db_session, server.id, target["id"], role.id, owner["id"]
        ),
        500,
    )
    monkeypatch.undo()
    db_session.expire_all()
    assert db_session.scalar(
        select(ServerMemberRole.id).where(
            ServerMemberRole.member_id == membership.id,
            ServerMemberRole.role_id == role.id,
        )
    ) is None
    assert _audit_rows(db_session, server.id, membership.id, role.id) == []

    assignment = _assign(db_session, server, membership, role, owner["id"])
    db_session.commit()
    original_flush = db_session.flush
    flush_count = 0

    def fail_remove_audit_flush(*args, **kwargs):
        nonlocal flush_count
        flush_count += 1
        if flush_count == 2:
            raise SQLAlchemyError("falha simulada ao gravar auditoria")
        return original_flush(*args, **kwargs)

    monkeypatch.setattr(db_session, "flush", fail_remove_audit_flush)
    _assert_http_error(
        lambda: remove_server_role_from_member(
            db_session, server.id, target["id"], role.id, owner["id"]
        ),
        500,
    )
    monkeypatch.undo()
    db_session.expire_all()
    assert db_session.get(ServerMemberRole, assignment.id) is not None
    assert _audit_rows(db_session, server.id, membership.id, role.id) == []


def test_failed_assignment_flush_does_not_leave_partial_state(
    db_session, create_user, monkeypatch
):
    owner, server, _ = _server(db_session, create_user)
    target = create_user()
    membership = _member(db_session, server, target)
    role = _role(db_session, server, name="Cargo", position=1)
    db_session.commit()

    def fail_flush(*args, **kwargs):
        raise SQLAlchemyError("falha simulada no flush")

    monkeypatch.setattr(db_session, "flush", fail_flush)
    _assert_http_error(
        lambda: assign_server_role_to_member(
            db_session, server.id, target["id"], role.id, owner["id"]
        ),
        500,
    )
    monkeypatch.undo()
    db_session.expire_all()

    assert db_session.scalar(
        select(ServerMemberRole.id).where(
            ServerMemberRole.member_id == membership.id,
            ServerMemberRole.role_id == role.id,
        )
    ) is None
    assert _audit_rows(db_session, server.id, membership.id, role.id) == []


def test_assignment_locks_server_actor_role_then_target(db_session, create_user):
    owner, server, _ = _server(db_session, create_user)
    target = create_user()
    _member(db_session, server, target)
    role = _role(db_session, server, name="Cargo", position=1)
    statements = []
    connection = db_session.connection()

    def capture_sql(conn, cursor, statement, parameters, context, executemany):
        if "for update" in statement.lower():
            statements.append(statement.lower())

    event.listen(connection, "before_cursor_execute", capture_sql)
    try:
        assign_server_role_to_member(
            db_session, server.id, target["id"], role.id, owner["id"]
        )
    finally:
        event.remove(connection, "before_cursor_execute", capture_sql)

    assert len(statements) >= 4
    assert "from servers" in statements[0]
    assert "from server_members" in statements[1]
    assert "from server_roles" in statements[2]
    assert "from server_members" in statements[3]
