from app.models import Server, ServerMember, ServerMemberRole, ServerRole


def _create_server(client, headers):
    response = client.post(
        "/servers/",
        headers=headers,
        json={"name": "Contexto de autorização"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_authorization_context_uses_union_and_highest_individual_role(
    client, db_session, create_user, auth_headers
):
    owner = create_user()
    manager = create_user()
    server_data = _create_server(client, auth_headers(owner))
    server = db_session.get(Server, server_data["id"])
    assert server is not None
    server.everyone_permissions = {"manage_invites": True}

    membership = ServerMember(
        server_id=server.id,
        user_id=manager["id"],
        status="ACTIVE",
    )
    db_session.add(membership)
    db_session.flush()
    lower = ServerRole(
        server_id=server.id,
        name="Gerenciador inferior",
        position=3,
        permissions={"ban_members": True},
    )
    higher = ServerRole(
        server_id=server.id,
        name="Gerenciador superior",
        position=9,
        permissions={"manage_roles": True},
    )
    db_session.add_all([lower, higher])
    db_session.flush()
    db_session.add_all([
        ServerMemberRole(
            server_id=server.id,
            member_id=membership.id,
            role_id=lower.id,
            assigned_by=owner["id"],
        ),
        ServerMemberRole(
            server_id=server.id,
            member_id=membership.id,
            role_id=higher.id,
            assigned_by=owner["id"],
        ),
    ])
    db_session.flush()

    response = client.get(
        f"/servers/{server.id}/authorization-context",
        headers=auth_headers(manager),
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "server_id": server.id,
        "user_id": manager["id"],
        "is_owner": False,
        "highest_role_position": 9,
        "effective_permissions": ["ban_members", "manage_invites", "manage_roles"],
        "has_manage_roles_permission": True,
    }


def test_owner_and_member_without_roles_have_separate_owner_authority_and_zero_level(
    client, db_session, create_user, auth_headers
):
    owner = create_user()
    member = create_user()
    server_data = _create_server(client, auth_headers(owner))
    server = db_session.get(Server, server_data["id"])
    assert server is not None
    server.everyone_permissions = {"kick_members": True}
    db_session.add(ServerMember(
        server_id=server.id,
        user_id=member["id"],
        status="ACTIVE",
    ))
    db_session.flush()

    owner_context = client.get(
        f"/servers/{server.id}/authorization-context",
        headers=auth_headers(owner),
    )
    member_context = client.get(
        f"/servers/{server.id}/authorization-context",
        headers=auth_headers(member),
    )

    assert owner_context.status_code == member_context.status_code == 200
    assert owner_context.json()["is_owner"] is True
    assert owner_context.json()["highest_role_position"] == 0
    assert owner_context.json()["has_manage_roles_permission"] is False
    assert member_context.json()["is_owner"] is False
    assert member_context.json()["highest_role_position"] == 0
    assert member_context.json()["effective_permissions"] == ["kick_members"]
    assert member_context.json()["has_manage_roles_permission"] is False


def test_authorization_context_requires_active_membership_and_authentication(
    client, create_user, auth_headers
):
    owner = create_user()
    outsider = create_user()
    server_data = _create_server(client, auth_headers(owner))

    missing_auth = client.get(
        f"/servers/{server_data['id']}/authorization-context"
    )
    outsider_response = client.get(
        f"/servers/{server_data['id']}/authorization-context",
        headers=auth_headers(outsider),
    )

    assert missing_auth.status_code in {401, 403}
    assert outsider_response.status_code == 404
