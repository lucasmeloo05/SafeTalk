from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import ServerMember, ServerMemberRole, ServerRole


def _create_server(client: TestClient, owner: dict, auth_headers) -> dict:
    response = client.post(
        "/servers/",
        json={"name": f"Servidor de {owner['username']}"},
        headers=auth_headers(owner),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _add_member(
    db_session,
    server_id: int,
    user_id: int,
    *,
    status: str = "ACTIVE",
) -> ServerMember:
    membership = ServerMember(
        server_id=server_id,
        user_id=user_id,
        status=status,
        left_at=datetime.now(timezone.utc) if status == "LEFT" else None,
    )
    db_session.add(membership)
    db_session.flush()
    return membership


def _assign_actor_role(
    db_session,
    *,
    server_id: int,
    membership: ServerMember,
    assigned_by: int,
    position: int,
    permissions: dict,
) -> ServerRole:
    role = ServerRole(
        server_id=server_id,
        name=f"Cargo de autorização {position}",
        position=position,
        permissions=permissions,
        is_default=False,
        is_system_role=False,
    )
    db_session.add(role)
    db_session.flush()
    db_session.add(
        ServerMemberRole(
            server_id=server_id,
            member_id=membership.id,
            role_id=role.id,
            assigned_by=assigned_by,
        )
    )
    db_session.flush()
    return role


def _create_role(
    client: TestClient,
    server_id: int,
    headers: dict[str, str],
    *,
    name: str = "Novo cargo",
    position: int = 1,
    permissions: dict | None = None,
    extra: dict | None = None,
):
    payload = {
        "name": name,
        "position": position,
        "permissions": permissions or {},
    }
    if extra:
        payload.update(extra)
    return client.post(
        f"/servers/{server_id}/roles",
        json=payload,
        headers=headers,
    )


def test_owner_can_create_role_and_receives_created_response(
    client, db_session, create_user, auth_headers
):
    owner = create_user()
    server = _create_server(client, owner, auth_headers)

    response = _create_role(
        client,
        server["id"],
        auth_headers(owner),
        name="  Cargo do proprietário  ",
        permissions={"manage_roles": True},
    )

    assert response.status_code == 201, response.text
    created = response.json()
    assert set(created) == {
        "id",
        "server_id",
        "name",
        "description",
        "permissions",
        "position",
        "is_default",
        "is_system_role",
        "created_at",
    }
    assert created["server_id"] == server["id"]
    assert created["name"] == "Cargo do proprietário"
    assert created["position"] == 1
    assert created["permissions"] == {"manage_roles": True}
    assert created["is_default"] is False
    assert created["is_system_role"] is False
    assert created["created_at"]


def test_active_manager_can_create_role_below_own_position(
    client, db_session, create_user, auth_headers
):
    owner = create_user()
    manager = create_user()
    server = _create_server(client, owner, auth_headers)
    membership = _add_member(db_session, server["id"], manager["id"])
    _assign_actor_role(
        db_session,
        server_id=server["id"],
        membership=membership,
        assigned_by=owner["id"],
        position=10,
        permissions={"manage_roles": True, "kick_members": True},
    )

    response = _create_role(
        client,
        server["id"],
        auth_headers(manager),
        name="Cargo inferior",
        position=9,
        permissions={"kick_members": True},
    )

    assert response.status_code == 201, response.text
    assert response.json()["name"] == "Cargo inferior"
    assert response.json()["position"] == 9


def test_member_without_manage_roles_cannot_create_role(
    client, db_session, create_user, auth_headers
):
    owner = create_user()
    member = create_user()
    server = _create_server(client, owner, auth_headers)
    _add_member(db_session, server["id"], member["id"])

    response = _create_role(
        client,
        server["id"],
        auth_headers(member),
    )

    assert response.status_code == 403


def test_user_without_active_membership_cannot_create_role(
    client, db_session, create_user, auth_headers
):
    owner = create_user()
    outsider = create_user()
    server = _create_server(client, owner, auth_headers)

    response = _create_role(
        client,
        server["id"],
        auth_headers(outsider),
    )

    assert response.status_code == 404


def test_left_member_cannot_create_role(
    client, db_session, create_user, auth_headers
):
    owner = create_user()
    left_member = create_user()
    server = _create_server(client, owner, auth_headers)
    _add_member(
        db_session,
        server["id"],
        left_member["id"],
        status="LEFT",
    )

    response = _create_role(
        client,
        server["id"],
        auth_headers(left_member),
    )

    assert response.status_code == 404


@pytest.mark.parametrize("position", [10, 11])
def test_manager_cannot_create_role_at_or_above_own_hierarchy(
    client, db_session, create_user, auth_headers, position: int
):
    owner = create_user()
    manager = create_user()
    server = _create_server(client, owner, auth_headers)
    membership = _add_member(db_session, server["id"], manager["id"])
    _assign_actor_role(
        db_session,
        server_id=server["id"],
        membership=membership,
        assigned_by=owner["id"],
        position=10,
        permissions={"manage_roles": True},
    )

    response = _create_role(
        client,
        server["id"],
        auth_headers(manager),
        position=position,
    )

    assert response.status_code == 403


def test_manager_cannot_grant_permission_they_do_not_have(
    client, db_session, create_user, auth_headers
):
    owner = create_user()
    manager = create_user()
    server = _create_server(client, owner, auth_headers)
    membership = _add_member(db_session, server["id"], manager["id"])
    _assign_actor_role(
        db_session,
        server_id=server["id"],
        membership=membership,
        assigned_by=owner["id"],
        position=10,
        permissions={"manage_roles": True},
    )

    response = _create_role(
        client,
        server["id"],
        auth_headers(manager),
        position=5,
        permissions={"kick_members": True},
    )

    assert response.status_code == 403


def test_duplicate_role_name_returns_conflict(
    client, db_session, create_user, auth_headers
):
    owner = create_user()
    server = _create_server(client, owner, auth_headers)
    headers = auth_headers(owner)
    first = _create_role(
        client,
        server["id"],
        headers,
        name="Moderador",
    )
    second = _create_role(
        client,
        server["id"],
        headers,
        name="Moderador",
        position=2,
    )

    assert first.status_code == 201, first.text
    assert second.status_code == 409


@pytest.mark.parametrize(
    "field,value",
    [
        ("server_id", 999),
        ("owner_id", 999),
        ("assigned_by", 999),
        ("is_default", True),
        ("is_system_role", True),
    ],
)
def test_client_cannot_supply_internal_role_fields(
    client, create_user, auth_headers, field: str, value: object
):
    owner = create_user()
    server = _create_server(client, owner, auth_headers)

    response = _create_role(
        client,
        server["id"],
        auth_headers(owner),
        extra={field: value},
    )

    assert response.status_code == 422


def test_role_creation_does_not_assign_role_automatically(
    client, db_session, create_user, auth_headers
):
    owner = create_user()
    server = _create_server(client, owner, auth_headers)

    response = _create_role(
        client,
        server["id"],
        auth_headers(owner),
    )

    assert response.status_code == 201, response.text
    role_id = response.json()["id"]
    assignment = db_session.scalar(
        select(ServerMemberRole).where(
            ServerMemberRole.server_id == server["id"],
            ServerMemberRole.role_id == role_id,
        )
    )
    assert assignment is None


def test_role_creation_route_requires_authentication(client):
    response = client.post(
        "/servers/1/roles",
        json={"name": "Cargo", "position": 1},
    )

    assert response.status_code in {401, 403}
