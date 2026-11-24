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


def _add_member(db_session, server_id: int, user_id: int, *, status="ACTIVE"):
    member = ServerMember(
        server_id=server_id,
        user_id=user_id,
        status=status,
        left_at=(datetime.now(timezone.utc) if status == "LEFT" else None),
    )
    db_session.add(member)
    db_session.flush()
    return member


def _add_role(
    db_session,
    server_id: int,
    *,
    name: str,
    position: int,
    description: str | None = None,
    permissions: dict | None = None,
    is_system_role: bool = False,
) -> ServerRole:
    role = ServerRole(
        server_id=server_id,
        name=name,
        position=position,
        description=description,
        permissions=permissions or {},
        is_default=False,
        is_system_role=is_system_role,
    )
    db_session.add(role)
    db_session.flush()
    return role


def _assign_role(
    db_session,
    *,
    server_id: int,
    membership: ServerMember,
    role: ServerRole,
    assigned_by: int,
):
    db_session.add(
        ServerMemberRole(
            server_id=server_id,
            member_id=membership.id,
            role_id=role.id,
            assigned_by=assigned_by,
        )
    )
    db_session.flush()


def _create_manager_context(client, db_session, create_user, auth_headers):
    owner = create_user()
    manager = create_user()
    server = _create_server(client, owner, auth_headers)
    manager_membership = _add_member(
        db_session, server["id"], manager["id"]
    )
    manager_role = _add_role(
        db_session,
        server["id"],
        name="Gerência",
        position=10,
        permissions={"manage_roles": True, "kick_members": True},
    )
    _assign_role(
        db_session,
        server_id=server["id"],
        membership=manager_membership,
        role=manager_role,
        assigned_by=owner["id"],
    )
    target_role = _add_role(
        db_session,
        server["id"],
        name="Cargo editável",
        position=5,
        description="Descrição original",
        permissions={"ban_members": True},
    )
    return owner, manager, server, target_role


def _patch_role(client, server_id, role_id, headers, payload):
    return client.patch(
        f"/servers/{server_id}/roles/{role_id}",
        json=payload,
        headers=headers,
    )


def test_owner_can_edit_role_and_receives_response_schema(
    client, db_session, create_user, auth_headers
):
    owner = create_user()
    server = _create_server(client, owner, auth_headers)
    role = _add_role(
        db_session,
        server["id"],
        name="Cargo comum",
        position=1,
    )

    response = _patch_role(
        client,
        server["id"],
        role.id,
        auth_headers(owner),
        {"name": "Cargo atualizado", "description": "Nova descrição"},
    )

    assert response.status_code == 200, response.text
    assert set(response.json()) == {
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
    assert response.json() == {
        "id": role.id,
        "server_id": server["id"],
        "name": "Cargo atualizado",
        "description": "Nova descrição",
        "permissions": {},
        "position": 1,
        "is_default": False,
        "is_system_role": False,
        "created_at": response.json()["created_at"],
    }


def test_active_manager_can_edit_lower_role(
    client, db_session, create_user, auth_headers
):
    _, manager, server, role = _create_manager_context(
        client, db_session, create_user, auth_headers
    )

    response = _patch_role(
        client,
        server["id"],
        role.id,
        auth_headers(manager),
        {"position": 8},
    )

    assert response.status_code == 200, response.text
    assert response.json()["position"] == 8
    assert response.json()["name"] == "Cargo editável"


def test_role_update_requires_authentication(
    client, db_session, create_user, auth_headers
):
    owner = create_user()
    server = _create_server(client, owner, auth_headers)
    role = _add_role(db_session, server["id"], name="Cargo", position=1)

    response = _patch_role(client, server["id"], role.id, {}, {"name": "X"})

    assert response.status_code in {401, 403}


def test_member_without_manage_roles_cannot_edit(
    client, db_session, create_user, auth_headers
):
    owner = create_user()
    member = create_user()
    server = _create_server(client, owner, auth_headers)
    _add_member(db_session, server["id"], member["id"])
    role = _add_role(db_session, server["id"], name="Cargo", position=1)

    response = _patch_role(
        client,
        server["id"],
        role.id,
        auth_headers(member),
        {"name": "Não autorizado"},
    )

    assert response.status_code == 403
    assert role.name == "Cargo"


def test_manager_without_sufficient_hierarchy_cannot_edit(
    client, db_session, create_user, auth_headers
):
    owner = create_user()
    manager = create_user()
    server = _create_server(client, owner, auth_headers)
    manager_membership = _add_member(
        db_session, server["id"], manager["id"]
    )
    manager_role = _add_role(
        db_session,
        server["id"],
        name="Gerência baixa",
        position=5,
        permissions={"manage_roles": True},
    )
    _assign_role(
        db_session,
        server_id=server["id"],
        membership=manager_membership,
        role=manager_role,
        assigned_by=owner["id"],
    )
    target_role = _add_role(
        db_session, server["id"], name="Cargo igual", position=5
    )

    response = _patch_role(
        client,
        server["id"],
        target_role.id,
        auth_headers(manager),
        {"description": "Negado"},
    )

    assert response.status_code == 403


def test_system_role_cannot_be_edited_by_owner(
    client, db_session, create_user, auth_headers
):
    owner = create_user()
    server = _create_server(client, owner, auth_headers)
    role = _add_role(
        db_session,
        server["id"],
        name="Cargo reservado",
        position=1,
        is_system_role=True,
    )

    response = _patch_role(
        client,
        server["id"],
        role.id,
        auth_headers(owner),
        {"name": "Tentativa"},
    )

    assert response.status_code == 403
    assert role.name == "Cargo reservado"


def test_missing_or_other_server_role_returns_not_found(
    client, db_session, create_user, auth_headers
):
    owner = create_user()
    other_owner = create_user()
    server = _create_server(client, owner, auth_headers)
    other_server = _create_server(client, other_owner, auth_headers)
    other_role = _add_role(
        db_session,
        other_server["id"],
        name="Cargo de outro servidor",
        position=1,
    )

    missing_response = _patch_role(
        client,
        server["id"],
        2_147_483_647,
        auth_headers(owner),
        {"name": "Ausente"},
    )
    foreign_response = _patch_role(
        client,
        server["id"],
        other_role.id,
        auth_headers(owner),
        {"name": "IDOR"},
    )

    assert missing_response.status_code == 404
    assert foreign_response.status_code == 404
    assert other_role.name == "Cargo de outro servidor"


def test_duplicate_name_returns_conflict(
    client, db_session, create_user, auth_headers
):
    owner = create_user()
    server = _create_server(client, owner, auth_headers)
    role = _add_role(db_session, server["id"], name="Cargo A", position=1)
    _add_role(db_session, server["id"], name="Cargo B", position=2)

    response = _patch_role(
        client,
        server["id"],
        role.id,
        auth_headers(owner),
        {"name": "Cargo B"},
    )

    assert response.status_code == 409


@pytest.mark.parametrize(
    "field_name,field_value",
    [
        ("server_id", 999),
        ("owner_id", 999),
        ("is_default", True),
        ("is_system_role", True),
        ("created_at", "2026-01-01T00:00:00Z"),
        ("assigned_by", 999),
        ("actor_user_id", 999),
        ("unexpected", "value"),
    ],
)
def test_role_patch_rejects_internal_and_extra_fields(
    client, db_session, create_user, auth_headers, field_name, field_value
):
    owner = create_user()
    server = _create_server(client, owner, auth_headers)
    role = _add_role(db_session, server["id"], name="Cargo", position=1)
    payload = {"name": "Alteração", field_name: field_value}

    response = _patch_role(
        client, server["id"], role.id, auth_headers(owner), payload
    )

    assert response.status_code == 422
    assert role.name == "Cargo"


def test_patch_is_partial_and_preserves_omitted_fields(
    client, db_session, create_user, auth_headers
):
    owner = create_user()
    server = _create_server(client, owner, auth_headers)
    role = _add_role(
        db_session,
        server["id"],
        name="Original",
        position=3,
        description="Preservada",
        permissions={"ban_members": True},
    )

    response = _patch_role(
        client,
        server["id"],
        role.id,
        auth_headers(owner),
        {"name": "Novo nome"},
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Novo nome"
    assert response.json()["description"] == "Preservada"
    assert response.json()["position"] == 3
    assert response.json()["permissions"] == {"ban_members": True}


def test_permissions_are_replaced_and_empty_object_clears_role_grants(
    client, db_session, create_user, auth_headers
):
    owner = create_user()
    server = _create_server(client, owner, auth_headers)
    role = _add_role(
        db_session,
        server["id"],
        name="Cargo",
        position=1,
        permissions={"ban_members": True, "kick_members": True},
    )

    replacement = _patch_role(
        client,
        server["id"],
        role.id,
        {**auth_headers(owner), "X-Expected-Permissions": '{"kick_members":true,"ban_members":true}'},
        {"permissions": {"kick_members": False}},
    )
    cleared = _patch_role(
        client,
        server["id"],
        role.id,
        {**auth_headers(owner), "X-Expected-Permissions": "{}"},
        {"permissions": {}},
    )

    assert replacement.status_code == 200, replacement.text
    assert replacement.json()["permissions"] == {"kick_members": False}
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["permissions"] == {}


@pytest.mark.parametrize("payload, known", [
    ({"name": "Outro nome"}, {"ban_members": True}),
    ({"description": None}, {"ban_members": True}),
    ({"permissions": {"kick_members": True}}, {"kick_members": True}),
    ({"permissions": {}}, {}),
])
def test_patch_preserves_stored_legacy_permissions(
    client, db_session, create_user, auth_headers, payload, known
):
    owner = create_user()
    server = _create_server(client, owner, auth_headers)
    legacy = {"legacy_flag": True, "legacy_metadata": {"version": 1}}
    role = _add_role(db_session, server["id"], name="Original", position=3,
                     permissions={**legacy, "ban_members": True})

    headers = {**auth_headers(owner), "X-Expected-Permissions": '{"ban_members":true}'}
    response = _patch_role(client, server["id"], role.id, headers, payload)

    assert response.status_code == 200, response.text
    db_session.refresh(role)
    assert role.permissions == response.json()["permissions"] == {**legacy, **known}


def test_get_and_post_role_routes_remain_available(
    client, db_session, create_user, auth_headers
):
    owner = create_user()
    server = _create_server(client, owner, auth_headers)
    role = _add_role(db_session, server["id"], name="Existente", position=1)

    list_response = client.get(
        f"/servers/{server['id']}/roles", headers=auth_headers(owner)
    )
    detail_response = client.get(
        f"/servers/{server['id']}/roles/{role.id}",
        headers=auth_headers(owner),
    )
    create_response = client.post(
        f"/servers/{server['id']}/roles",
        json={"name": "Novo", "position": 2},
        headers=auth_headers(owner),
    )

    assert list_response.status_code == 200
    assert detail_response.status_code == 200
    assert create_response.status_code == 201
