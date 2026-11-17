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
from app.schemas import ServerRoleUpdate
from app.services.server_authorization_service import (
    get_effective_server_permissions,
)
from app.services.server_role_service import update_server_role


def _create_server(db_session, create_user, *, name="Servidor de cargos"):
    owner = create_user()
    server = Server(owner_id=owner["id"], name=name)
    db_session.add(server)
    db_session.flush()
    owner_member = ServerMember(
        server_id=server.id,
        user_id=owner["id"],
        status="ACTIVE",
    )
    db_session.add(owner_member)
    db_session.flush()
    return owner, server, owner_member


def _add_member(db_session, server, user, *, status="ACTIVE"):
    member = ServerMember(
        server_id=server.id,
        user_id=user["id"],
        status=status,
        left_at=(datetime.now(timezone.utc) if status == "LEFT" else None),
    )
    db_session.add(member)
    db_session.flush()
    return member


def _add_role(
    db_session,
    server,
    *,
    name,
    position,
    permissions=None,
    is_system_role=False,
    is_default=False,
):
    role = ServerRole(
        server_id=server.id,
        name=name,
        position=position,
        permissions=permissions or {},
        is_system_role=is_system_role,
        is_default=is_default,
    )
    db_session.add(role)
    db_session.flush()
    return role


def _assign(db_session, server, member, role, assigned_by):
    db_session.add(
        ServerMemberRole(
            server_id=server.id,
            member_id=member.id,
            role_id=role.id,
            assigned_by=assigned_by,
        )
    )
    db_session.flush()


def _update(**values):
    return ServerRoleUpdate.model_validate(values)


def _manager_context(db_session, create_user):
    owner, server, _ = _create_server(db_session, create_user)
    actor = create_user()
    actor_member = _add_member(db_session, server, actor)
    actor_role = _add_role(
        db_session,
        server,
        name="Gerência",
        position=10,
        permissions={"manage_roles": True, "kick_members": True},
    )
    _assign(db_session, server, actor_member, actor_role, owner["id"])
    target_role = _add_role(
        db_session,
        server,
        name="Cargo editável",
        position=5,
        permissions={"kick_members": False},
    )
    return owner, actor, server, actor_member, target_role


def test_owner_updates_common_role_without_manage_roles_or_position_limit(
    db_session, create_user
):
    owner, server, _ = _create_server(db_session, create_user)
    role = _add_role(
        db_session,
        server,
        name="Comum",
        position=15,
        permissions={},
        is_default=True,
    )

    updated = update_server_role(
        db_session,
        server.id,
        role.id,
        owner["id"],
        _update(name="Atualizado", position=20),
    )

    assert updated.name == "Atualizado"
    assert updated.position == 20
    assert updated.is_default is True
    assert updated.is_system_role is False


def test_active_manager_updates_role_below_own_position(db_session, create_user):
    _, actor, server, _, role = _manager_context(db_session, create_user)

    updated = update_server_role(
        db_session,
        server.id,
        role.id,
        actor["id"],
        _update(name="Cargo revisado", position=8),
    )

    assert updated.name == "Cargo revisado"
    assert updated.position == 8


def test_member_without_manage_roles_cannot_update_role(db_session, create_user):
    _, server, _ = _create_server(db_session, create_user)
    member = create_user()
    _add_member(db_session, server, member)
    role = _add_role(db_session, server, name="Comum", position=1)

    with pytest.raises(HTTPException) as error:
        update_server_role(
            db_session, server.id, role.id, member["id"], _update(name="X")
        )

    assert error.value.status_code == 403
    assert role.name == "Comum"


@pytest.mark.parametrize("membership_status", ["LEFT", "MISSING"])
def test_inactive_or_missing_actor_cannot_update_role(
    db_session, create_user, membership_status
):
    _, server, _ = _create_server(db_session, create_user)
    actor = create_user()
    if membership_status == "LEFT":
        _add_member(db_session, server, actor, status="LEFT")
    role = _add_role(db_session, server, name="Comum", position=1)

    with pytest.raises(HTTPException) as error:
        update_server_role(
            db_session, server.id, role.id, actor["id"], _update(name="X")
        )

    assert error.value.status_code == 404


def test_nonexistent_role_returns_not_found(db_session, create_user):
    owner, server, _ = _create_server(db_session, create_user)

    with pytest.raises(HTTPException) as error:
        update_server_role(
            db_session,
            server.id,
            2_147_483_647,
            owner["id"],
            _update(name="X"),
        )

    assert error.value.status_code == 404


def test_role_from_another_server_returns_not_found(db_session, create_user):
    owner, server, _ = _create_server(db_session, create_user)
    other_owner, other_server, _ = _create_server(
        db_session, create_user, name="Outro servidor"
    )
    other_role = _add_role(
        db_session, other_server, name="Privado", position=1
    )

    with pytest.raises(HTTPException) as error:
        update_server_role(
            db_session,
            server.id,
            other_role.id,
            owner["id"],
            _update(name="Vazado"),
        )

    assert error.value.status_code == 404
    assert other_role.name == "Privado"
    assert other_owner["id"] != owner["id"]


@pytest.mark.parametrize("is_owner", [False, True])
def test_system_role_is_immutable_including_for_owner(
    db_session, create_user, is_owner
):
    owner, server, _ = _create_server(db_session, create_user)
    if is_owner:
        actor_id = owner["id"]
    else:
        actor = create_user()
        _add_member(db_session, server, actor)
        actor_id = actor["id"]
    role = _add_role(
        db_session,
        server,
        name="Reservado",
        position=1,
        is_system_role=True,
    )

    with pytest.raises(HTTPException) as error:
        update_server_role(
            db_session, server.id, role.id, actor_id, _update(name="Alterado")
        )

    assert error.value.status_code == 403
    assert role.name == "Reservado"


@pytest.mark.parametrize("target_position", [10, 11])
def test_manager_cannot_edit_role_at_or_above_own_position(
    db_session, create_user, target_position
):
    owner, actor, server, actor_member, _ = _manager_context(
        db_session, create_user
    )
    role = _add_role(
        db_session,
        server,
        name="Cargo alto",
        position=target_position,
    )

    with pytest.raises(HTTPException) as error:
        update_server_role(
            db_session,
            server.id,
            role.id,
            actor["id"],
            _update(description="Bloqueado"),
        )

    assert error.value.status_code == 403
    assert role.description is None
    assert owner["id"] != actor["id"]
    assert actor_member.status == "ACTIVE"


@pytest.mark.parametrize("new_position", [10, 11])
def test_manager_cannot_move_role_to_or_above_own_position(
    db_session, create_user, new_position
):
    _, actor, server, _, role = _manager_context(db_session, create_user)

    with pytest.raises(HTTPException) as error:
        update_server_role(
            db_session,
            server.id,
            role.id,
            actor["id"],
            _update(position=new_position),
        )

    assert error.value.status_code == 403
    assert role.position == 5


def test_manager_cannot_grant_permission_they_do_not_have(db_session, create_user):
    _, actor, server, _, role = _manager_context(db_session, create_user)

    with pytest.raises(HTTPException) as error:
        update_server_role(
            db_session,
            server.id,
            role.id,
            actor["id"],
            _update(permissions={"ban_members": True}),
        )

    assert error.value.status_code == 403
    assert role.permissions == {"kick_members": False}


def test_manager_can_grant_owned_permission_to_lower_active_assignees(
    db_session, create_user
):
    owner, actor, server, _, role = _manager_context(db_session, create_user)
    target = create_user()
    target_member = _add_member(db_session, server, target)
    _assign(db_session, server, target_member, role, owner["id"])

    updated = update_server_role(
        db_session,
        server.id,
        role.id,
        actor["id"],
        _update(permissions={"kick_members": True}),
    )

    assert updated.permissions == {"kick_members": True}
    assert "kick_members" in get_effective_server_permissions(
        db_session, server.id, target["id"]
    )


def test_new_manage_roles_grant_cannot_authorize_its_own_edit(
    db_session, create_user
):
    _, server, _ = _create_server(db_session, create_user)
    actor = create_user()
    actor_member = _add_member(db_session, server, actor)
    higher_role = _add_role(
        db_session,
        server,
        name="Superior sem gestão",
        position=10,
        permissions={"kick_members": True},
    )
    _assign(db_session, server, actor_member, higher_role, server.owner_id)
    own_target_role = _add_role(
        db_session,
        server,
        name="Cargo do próprio ator",
        position=5,
        permissions={},
    )
    _assign(db_session, server, actor_member, own_target_role, server.owner_id)

    with pytest.raises(HTTPException) as error:
        update_server_role(
            db_session,
            server.id,
            own_target_role.id,
            actor["id"],
            _update(permissions={"manage_roles": True}),
        )

    assert error.value.status_code == 403
    assert own_target_role.permissions == {}


@pytest.mark.parametrize("target_position", [10, 11])
def test_manager_cannot_update_role_held_by_equal_or_higher_member(
    db_session, create_user, target_position
):
    owner, actor, server, _, target_role = _manager_context(
        db_session, create_user
    )
    target = create_user()
    target_member = _add_member(db_session, server, target)
    _assign(db_session, server, target_member, target_role, owner["id"])
    other_role = _add_role(
        db_session,
        server,
        name="Hierarquia do alvo",
        position=target_position,
    )
    _assign(db_session, server, target_member, other_role, owner["id"])

    with pytest.raises(HTTPException) as error:
        update_server_role(
            db_session,
            server.id,
            target_role.id,
            actor["id"],
            _update(description="Não permitido"),
        )

    assert error.value.status_code == 403
    assert target_role.description is None


def test_omitted_fields_remain_unchanged(db_session, create_user):
    owner, server, _ = _create_server(db_session, create_user)
    role = _add_role(
        db_session,
        server,
        name="Original",
        position=3,
        permissions={"ban_members": True},
    )
    role.description = "Preservada"
    db_session.flush()

    updated = update_server_role(
        db_session,
        server.id,
        role.id,
        owner["id"],
        _update(name="Novo nome"),
    )

    assert updated.name == "Novo nome"
    assert updated.description == "Preservada"
    assert updated.position == 3
    assert updated.permissions == {"ban_members": True}


def test_description_null_clears_existing_value(db_session, create_user):
    owner, server, _ = _create_server(db_session, create_user)
    role = _add_role(db_session, server, name="Cargo", position=1)
    role.description = "Descrição existente"
    db_session.flush()

    updated = update_server_role(
        db_session,
        server.id,
        role.id,
        owner["id"],
        _update(description=None),
    )

    assert updated.description is None


def test_permissions_replace_whole_object_and_preserve_union(
    db_session, create_user
):
    owner, server, owner_member = _create_server(db_session, create_user)
    server.everyone_permissions = {"kick_members": True}
    role = _add_role(
        db_session,
        server,
        name="Cargo",
        position=1,
        permissions={"kick_members": True, "ban_members": True},
    )
    _assign(db_session, server, owner_member, role, owner["id"])

    updated = update_server_role(
        db_session,
        server.id,
        role.id,
        owner["id"],
        _update(permissions={"kick_members": False}),
    )

    assert updated.permissions == {"kick_members": False}
    assert get_effective_server_permissions(
        db_session, server.id, owner["id"]
    ) == frozenset({"kick_members"})


def test_empty_permissions_object_removes_role_grants(db_session, create_user):
    owner, server, owner_member = _create_server(db_session, create_user)
    role = _add_role(
        db_session,
        server,
        name="Cargo",
        position=1,
        permissions={"ban_members": True},
    )
    _assign(db_session, server, owner_member, role, owner["id"])

    updated = update_server_role(
        db_session,
        server.id,
        role.id,
        owner["id"],
        _update(permissions={}),
    )

    assert updated.permissions == {}
    assert get_effective_server_permissions(
        db_session, server.id, owner["id"]
    ) == frozenset()


def test_duplicate_name_returns_conflict(db_session, create_user):
    owner, server, _ = _create_server(db_session, create_user)
    role = _add_role(db_session, server, name="Cargo A", position=1)
    _add_role(db_session, server, name="Cargo B", position=2)
    db_session.commit()

    with pytest.raises(HTTPException) as error:
        update_server_role(
            db_session,
            server.id,
            role.id,
            owner["id"],
            _update(name="Cargo B"),
        )

    assert error.value.status_code == 409
    db_session.expire_all()
    persisted_role = db_session.scalar(
        select(ServerRole).where(ServerRole.id == role.id)
    )
    assert persisted_role.name == "Cargo A"


def test_audit_records_only_changed_fields_atomically(db_session, create_user):
    owner, server, _ = _create_server(db_session, create_user)
    role = _add_role(
        db_session,
        server,
        name="Cargo antigo",
        position=1,
        permissions={"kick_members": False},
    )

    update_server_role(
        db_session,
        server.id,
        role.id,
        owner["id"],
        _update(name="Cargo novo", description="Atualizado"),
    )

    audit = db_session.scalar(
        select(ServerConfigHistory).where(
            ServerConfigHistory.server_id == server.id,
            ServerConfigHistory.changed_by == owner["id"],
            ServerConfigHistory.setting_name == f"server_role:{role.id}",
        )
    )
    assert audit is not None
    assert json.loads(audit.old_value) == {"name": "Cargo antigo", "description": None}
    assert json.loads(audit.new_value) == {
        "name": "Cargo novo",
        "description": "Atualizado",
    }
    assert audit.changed_at is not None


def test_noop_update_does_not_create_empty_audit_record(db_session, create_user):
    owner, server, _ = _create_server(db_session, create_user)
    role = _add_role(
        db_session,
        server,
        name="Cargo",
        position=1,
        permissions={"kick_members": False},
    )

    update_server_role(
        db_session,
        server.id,
        role.id,
        owner["id"],
        _update(name="Cargo", permissions={"kick_members": False}),
    )

    assert db_session.scalar(
        select(ServerConfigHistory).where(
            ServerConfigHistory.server_id == server.id,
            ServerConfigHistory.setting_name == f"server_role:{role.id}",
        )
    ) is None


def test_failure_writing_audit_rolls_back_role_update(
    db_session, create_user, monkeypatch
):
    owner, server, _ = _create_server(db_session, create_user)
    role = _add_role(db_session, server, name="Original", position=1)
    db_session.commit()
    original_flush = db_session.flush
    flush_calls = 0

    def fail_audit_flush(*args, **kwargs):
        nonlocal flush_calls
        flush_calls += 1
        if flush_calls == 2:
            raise SQLAlchemyError("falha simulada ao persistir auditoria")
        return original_flush(*args, **kwargs)

    monkeypatch.setattr(db_session, "flush", fail_audit_flush)
    with pytest.raises(HTTPException) as error:
        update_server_role(
            db_session,
            server.id,
            role.id,
            owner["id"],
            _update(name="Alterado"),
        )
    monkeypatch.undo()

    assert error.value.status_code == 500
    db_session.expire_all()
    persisted_role = db_session.scalar(
        select(ServerRole).where(ServerRole.id == role.id)
    )
    assert persisted_role.name == "Original"
    assert db_session.scalar(
        select(ServerConfigHistory).where(
            ServerConfigHistory.server_id == server.id,
            ServerConfigHistory.setting_name == f"server_role:{role.id}",
        )
    ) is None


def test_update_acquires_server_membership_role_locks_in_order(
    db_session, create_user
):
    owner, _, server, _, role = _manager_context(db_session, create_user)
    connection = db_session.connection()
    statements = []

    def capture_sql(conn, cursor, statement, parameters, context, executemany):
        if "for update" in statement.lower():
            statements.append(statement.lower())

    event.listen(connection, "before_cursor_execute", capture_sql)
    try:
        update_server_role(
            db_session,
            server.id,
            role.id,
            owner["id"],
            _update(name="Lock verificado"),
        )
    finally:
        event.remove(connection, "before_cursor_execute", capture_sql)

    assert len(statements) >= 3
    assert "from servers" in statements[0]
    assert "from server_members" in statements[1]
    assert "from server_roles" in statements[2]
