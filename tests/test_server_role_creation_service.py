from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.models import (
    Server,
    ServerMember,
    ServerMemberRole,
    ServerRole,
)
from app.schemas import ServerRoleCreate
from app.services.server_role_service import create_server_role
from app.server_permissions import SERVER_PERMISSION_KEYS


def _setup_server(db_session, owner: dict, actor: dict | None = None):
    server = Server(owner_id=owner["id"], name="Servidor de cargos")
    db_session.add(server)
    db_session.flush()

    owner_member = ServerMember(
        server_id=server.id,
        user_id=owner["id"],
        status="ACTIVE",
    )
    db_session.add(owner_member)
    if actor is not None and actor["id"] != owner["id"]:
        db_session.add(
            ServerMember(
                server_id=server.id,
                user_id=actor["id"],
                status="ACTIVE",
            )
        )
    db_session.flush()
    return server


def _assign_role(
    db_session,
    server: Server,
    actor: dict,
    assigned_by: dict,
    *,
    position: int,
    permissions: dict,
) -> ServerRole:
    role = ServerRole(
        server_id=server.id,
        name=f"Cargo de teste {position} {len(permissions)}",
        position=position,
        permissions=permissions,
        is_default=False,
        is_system_role=False,
    )
    db_session.add(role)
    db_session.flush()
    membership = db_session.scalar(
        select(ServerMember).where(
            ServerMember.server_id == server.id,
            ServerMember.user_id == actor["id"],
        )
    )
    assert membership is not None
    db_session.add(
        ServerMemberRole(
            server_id=server.id,
            member_id=membership.id,
            role_id=role.id,
            assigned_by=assigned_by["id"],
        )
    )
    db_session.flush()
    return role


def _role_data(
    *,
    name: str = "Novo cargo",
    position: int = 1,
    permissions: dict | None = None,
) -> ServerRoleCreate:
    return ServerRoleCreate.model_validate(
        {
            "name": name,
            "position": position,
            "permissions": permissions or {},
        }
    )


def test_owner_creates_role_without_manage_roles(
    db_session, create_user
):
    owner = create_user()
    server = _setup_server(db_session, owner)

    role = create_server_role(
        db_session, server.id, owner["id"], _role_data()
    )

    assert role.server_id == server.id
    assert role.name == "Novo cargo"
    assert role.position == 1
    assert role.is_default is False
    assert role.is_system_role is False


def test_active_manager_creates_role_below_own_position(
    db_session, create_user
):
    owner = create_user()
    actor = create_user()
    server = _setup_server(db_session, owner, actor)
    _assign_role(
        db_session,
        server,
        actor,
        owner,
        position=10,
        permissions={"manage_roles": True, "kick_members": True},
    )

    role = create_server_role(
        db_session,
        server.id,
        actor["id"],
        _role_data(position=9, permissions={"kick_members": True}),
    )

    assert role.position == 9
    assert role.permissions == {"kick_members": True}


def test_member_without_manage_roles_cannot_create_role(
    db_session, create_user
):
    owner = create_user()
    actor = create_user()
    server = _setup_server(db_session, owner, actor)
    _assign_role(
        db_session,
        server,
        actor,
        owner,
        position=10,
        permissions={"kick_members": True},
    )

    with pytest.raises(HTTPException) as error:
        create_server_role(
            db_session, server.id, actor["id"], _role_data(position=1)
        )

    assert error.value.status_code == 403


def test_left_member_cannot_create_role(db_session, create_user):
    owner = create_user()
    actor = create_user()
    server = _setup_server(db_session, owner)
    db_session.add(
        ServerMember(
            server_id=server.id,
            user_id=actor["id"],
            status="LEFT",
            left_at=datetime.now(timezone.utc),
        )
    )
    db_session.flush()

    with pytest.raises(HTTPException) as error:
        create_server_role(
            db_session, server.id, actor["id"], _role_data()
        )

    assert error.value.status_code == 404


def test_user_without_membership_cannot_create_role(db_session, create_user):
    owner = create_user()
    outsider = create_user()
    server = _setup_server(db_session, owner)

    with pytest.raises(HTTPException) as error:
        create_server_role(
            db_session, server.id, outsider["id"], _role_data()
        )

    assert error.value.status_code == 404


def test_nonexistent_server_cannot_receive_role(db_session, create_user):
    actor = create_user()

    with pytest.raises(HTTPException) as error:
        create_server_role(
            db_session, 2_147_483_647, actor["id"], _role_data()
        )

    assert error.value.status_code == 404


@pytest.mark.parametrize("requested_position", [10, 11])
def test_member_cannot_create_role_at_or_above_own_position(
    db_session, create_user, requested_position: int
):
    owner = create_user()
    actor = create_user()
    server = _setup_server(db_session, owner, actor)
    _assign_role(
        db_session,
        server,
        actor,
        owner,
        position=10,
        permissions={"manage_roles": True},
    )

    with pytest.raises(HTTPException) as error:
        create_server_role(
            db_session,
            server.id,
            actor["id"],
            _role_data(position=requested_position),
        )

    assert error.value.status_code == 403


def test_member_cannot_grant_permission_they_do_not_effectively_have(
    db_session, create_user
):
    owner = create_user()
    actor = create_user()
    server = _setup_server(db_session, owner, actor)
    _assign_role(
        db_session,
        server,
        actor,
        owner,
        position=10,
        permissions={"manage_roles": True},
    )

    with pytest.raises(HTTPException) as error:
        create_server_role(
            db_session,
            server.id,
            actor["id"],
            _role_data(
                position=5,
                permissions={"kick_members": True},
            ),
        )

    assert error.value.status_code == 403


def test_owner_can_grant_all_approved_permissions(db_session, create_user):
    owner = create_user()
    server = _setup_server(db_session, owner)
    all_permissions = {permission: True for permission in SERVER_PERMISSION_KEYS}

    role = create_server_role(
        db_session,
        server.id,
        owner["id"],
        _role_data(permissions=all_permissions),
    )

    assert role.permissions == all_permissions


def test_false_role_permission_is_preserved_not_treated_as_revocation(
    db_session, create_user
):
    owner = create_user()
    actor = create_user()
    server = _setup_server(db_session, owner, actor)
    _assign_role(
        db_session,
        server,
        actor,
        owner,
        position=10,
        permissions={"manage_roles": True},
    )

    role = create_server_role(
        db_session,
        server.id,
        actor["id"],
        _role_data(position=5, permissions={"kick_members": False}),
    )

    assert role.permissions == {"kick_members": False}


def test_duplicate_exact_name_returns_conflict(db_session, create_user):
    owner = create_user()
    server = _setup_server(db_session, owner)
    db_session.add(
        ServerRole(
            server_id=server.id,
            name="Moderador",
            position=1,
            permissions={},
            is_default=False,
            is_system_role=False,
        )
    )
    db_session.flush()

    with pytest.raises(HTTPException) as error:
        create_server_role(
            db_session,
            server.id,
            owner["id"],
            _role_data(name="Moderador"),
        )

    assert error.value.status_code == 409


def test_created_role_is_not_assigned_to_any_member(db_session, create_user):
    owner = create_user()
    server = _setup_server(db_session, owner)

    role = create_server_role(
        db_session, server.id, owner["id"], _role_data()
    )

    assignment = db_session.scalar(
        select(ServerMemberRole).where(
            ServerMemberRole.server_id == server.id,
            ServerMemberRole.role_id == role.id,
        )
    )
    assert assignment is None


def test_database_failure_rolls_back_role_creation(
    db_session, create_user, monkeypatch
):
    owner = create_user()
    server = _setup_server(db_session, owner)

    def fail_flush(*args, **kwargs):
        raise SQLAlchemyError("falha simulada antes do commit")

    monkeypatch.setattr(db_session, "flush", fail_flush)
    with pytest.raises(HTTPException) as error:
        create_server_role(
            db_session, server.id, owner["id"], _role_data()
        )
    monkeypatch.undo()

    assert error.value.status_code == 500
    assert db_session.scalar(
        select(ServerRole).where(
            ServerRole.server_id == server.id,
            ServerRole.name == "Novo cargo",
        )
    ) is None


def test_non_name_integrity_error_is_not_reported_as_duplicate(
    db_session, create_user, monkeypatch
):
    owner = create_user()
    server = _setup_server(db_session, owner)

    def fail_flush(*args, **kwargs):
        raise IntegrityError("insert", {}, Exception("other constraint"))

    monkeypatch.setattr(db_session, "flush", fail_flush)
    with pytest.raises(HTTPException) as error:
        create_server_role(
            db_session, server.id, owner["id"], _role_data()
        )

    assert error.value.status_code == 500
    assert "nome" not in error.value.detail.lower()
