from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.models import ServerMember, ServerRole


def _create_server(client: TestClient, user: dict, auth_headers) -> dict:
    response = client.post(
        "/servers/",
        json={"name": f"Servidor de {user['username']}"},
        headers=auth_headers(user),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _add_member(
    db_session,
    server_id: int,
    user_id: int,
    *,
    status: str = "ACTIVE",
) -> None:
    db_session.add(
        ServerMember(
            server_id=server_id,
            user_id=user_id,
            status=status,
            left_at=datetime.now(timezone.utc) if status == "LEFT" else None,
        )
    )
    db_session.flush()


def _add_role(
    db_session,
    server_id: int,
    name: str,
    position: int,
    *,
    permissions: dict | None = None,
) -> ServerRole:
    role = ServerRole(
        server_id=server_id,
        name=name,
        description=f"Descrição de {name}",
        permissions=permissions or {},
        position=position,
        is_default=False,
        is_system_role=False,
    )
    db_session.add(role)
    db_session.flush()
    return role


def test_active_member_can_list_roles_in_position_order_without_manage_roles(
    client,
    db_session,
    create_user,
    auth_headers,
):
    owner = create_user()
    member = create_user()
    server = _create_server(client, owner, auth_headers)
    _add_member(db_session, server["id"], member["id"])
    later_role = _add_role(
        db_session,
        server["id"],
        "Cargo superior",
        5,
        permissions={"manage_invites": True},
    )
    earlier_role = _add_role(
        db_session,
        server["id"],
        "Cargo inicial",
        1,
        permissions={"kick_members": False},
    )

    response = client.get(
        f"/servers/{server['id']}/roles",
        headers=auth_headers(member),
    )

    assert response.status_code == 200, response.text
    roles = response.json()
    assert [role["id"] for role in roles] == [earlier_role.id, later_role.id]
    assert [role["position"] for role in roles] == [1, 5]
    assert roles[0]["permissions"] == {"kick_members": False}
    assert roles[1]["permissions"] == {"manage_invites": True}
    assert all(
        set(role)
        == {
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
        for role in roles
    )
    assert all(role["is_default"] is False for role in roles)
    assert all(role["is_system_role"] is False for role in roles)


def test_server_owner_can_list_roles(client, db_session, create_user, auth_headers):
    owner = create_user()
    server = _create_server(client, owner, auth_headers)
    role = _add_role(db_session, server["id"], "Cargo do servidor", 2)

    response = client.get(
        f"/servers/{server['id']}/roles",
        headers=auth_headers(owner),
    )

    assert response.status_code == 200, response.text
    assert [item["id"] for item in response.json()] == [role.id]


def test_list_roles_rejects_non_member_and_left_member(
    client,
    db_session,
    create_user,
    auth_headers,
):
    owner = create_user()
    outsider = create_user()
    left_member = create_user()
    server = _create_server(client, owner, auth_headers)
    role = _add_role(db_session, server["id"], "Cargo protegido", 1)
    _add_member(db_session, server["id"], left_member["id"], status="LEFT")

    outsider_response = client.get(
        f"/servers/{server['id']}/roles",
        headers=auth_headers(outsider),
    )
    left_response = client.get(
        f"/servers/{server['id']}/roles",
        headers=auth_headers(left_member),
    )
    left_detail_response = client.get(
        f"/servers/{server['id']}/roles/{role.id}",
        headers=auth_headers(left_member),
    )

    assert outsider_response.status_code == left_response.status_code == 404
    assert left_detail_response.status_code == 404
    assert outsider_response.json() == left_response.json()


def test_role_detail_returns_requested_role_to_active_member(
    client,
    db_session,
    create_user,
    auth_headers,
):
    owner = create_user()
    member = create_user()
    server = _create_server(client, owner, auth_headers)
    _add_member(db_session, server["id"], member["id"])
    role = _add_role(
        db_session,
        server["id"],
        "Cargo visível",
        3,
        permissions={"manage_roles": False},
    )

    response = client.get(
        f"/servers/{server['id']}/roles/{role.id}",
        headers=auth_headers(member),
    )

    assert response.status_code == 200, response.text
    assert response.json()["id"] == role.id
    assert response.json()["server_id"] == server["id"]
    assert response.json()["name"] == "Cargo visível"
    assert response.json()["permissions"] == {"manage_roles": False}


def test_role_detail_rejects_missing_role_and_role_from_another_server(
    client,
    db_session,
    create_user,
    auth_headers,
):
    owner_a = create_user()
    owner_b = create_user()
    member = create_user()
    server_a = _create_server(client, owner_a, auth_headers)
    server_b = _create_server(client, owner_b, auth_headers)
    _add_member(db_session, server_a["id"], member["id"])
    role_b = _add_role(db_session, server_b["id"], "Cargo privado", 1)
    headers = auth_headers(member)

    missing_response = client.get(
        f"/servers/{server_a['id']}/roles/2147483647",
        headers=headers,
    )
    foreign_response = client.get(
        f"/servers/{server_a['id']}/roles/{role_b.id}",
        headers=headers,
    )

    assert missing_response.status_code == foreign_response.status_code == 404
    assert missing_response.json() == foreign_response.json()


def test_role_list_is_isolated_between_servers(
    client,
    db_session,
    create_user,
    auth_headers,
):
    owner_a = create_user()
    owner_b = create_user()
    member = create_user()
    server_a = _create_server(client, owner_a, auth_headers)
    server_b = _create_server(client, owner_b, auth_headers)
    _add_member(db_session, server_a["id"], member["id"])
    role_a = _add_role(db_session, server_a["id"], "Cargo A", 1)
    role_b = _add_role(db_session, server_b["id"], "Cargo B", 1)

    response = client.get(
        f"/servers/{server_a['id']}/roles",
        headers=auth_headers(member),
    )

    assert response.status_code == 200, response.text
    assert [role["id"] for role in response.json()] == [role_a.id]
    assert all(role["id"] != role_b.id for role in response.json())


def test_server_role_read_routes_require_authentication(client):
    list_response = client.get("/servers/1/roles")
    detail_response = client.get("/servers/1/roles/1")

    assert list_response.status_code in {401, 403}
    assert detail_response.status_code in {401, 403}
