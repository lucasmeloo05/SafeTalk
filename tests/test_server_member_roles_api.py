from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import (
    ServerConfigHistory,
    ServerMember,
    ServerMemberRole,
    ServerRole,
)


def _create_server(client: TestClient, owner: dict, auth_headers) -> dict:
    response = client.post(
        "/servers/",
        json={"name": f"Servidor de {owner['username']}"},
        headers=auth_headers(owner),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _member(db_session, server_id, user_id, *, member_status="ACTIVE"):
    membership = ServerMember(
        server_id=server_id,
        user_id=user_id,
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
    server_id,
    *,
    name,
    position,
    permissions=None,
    is_default=False,
    is_system_role=False,
):
    role = ServerRole(
        server_id=server_id,
        name=name,
        position=position,
        permissions=permissions or {},
        is_default=is_default,
        is_system_role=is_system_role,
    )
    db_session.add(role)
    db_session.flush()
    return role


def _assign(db_session, *, server_id, membership, role, assigned_by):
    assignment = ServerMemberRole(
        server_id=server_id,
        member_id=membership.id,
        role_id=role.id,
        assigned_by=assigned_by,
    )
    db_session.add(assignment)
    db_session.flush()
    return assignment


def _manager_context(client, db_session, create_user, auth_headers):
    owner = create_user()
    manager = create_user()
    server = _create_server(client, owner, auth_headers)
    membership = _member(db_session, server["id"], manager["id"])
    manager_role = _role(
        db_session,
        server["id"],
        name="Gerência",
        position=10,
        permissions={"manage_roles": True},
    )
    _assign(
        db_session,
        server_id=server["id"],
        membership=membership,
        role=manager_role,
        assigned_by=owner["id"],
    )
    target = create_user()
    target_membership = _member(db_session, server["id"], target["id"])
    return owner, manager, server, target, target_membership


def _assign_route(client, server_id, user_id, role_id, headers, *, body=None):
    return client.put(
        f"/servers/{server_id}/members/{user_id}/roles/{role_id}",
        headers=headers,
        json=body,
    )


def _remove_route(client, server_id, user_id, role_id, headers):
    return client.delete(
        f"/servers/{server_id}/members/{user_id}/roles/{role_id}",
        headers=headers,
    )


def _audit(db_session, server_id, membership_id, role_id):
    return db_session.scalars(
        select(ServerConfigHistory).where(
            ServerConfigHistory.server_id == server_id,
            ServerConfigHistory.setting_name
            == f"server_member_role:{membership_id}:{role_id}",
        )
    ).all()


def test_owner_put_assigns_role_with_204_and_authenticated_assigner(
    client, db_session, create_user, auth_headers
):
    owner = create_user()
    target = create_user()
    server = _create_server(client, owner, auth_headers)
    membership = _member(db_session, server["id"], target["id"])
    role = _role(db_session, server["id"], name="Cargo", position=1)

    response = _assign_route(
        client,
        server["id"],
        target["id"],
        role.id,
        auth_headers(owner),
        body={"assigned_by": target["id"]},
    )

    assert response.status_code == 204
    assert response.content == b""
    assignment = db_session.scalar(
        select(ServerMemberRole).where(
            ServerMemberRole.member_id == membership.id,
            ServerMemberRole.role_id == role.id,
        )
    )
    assert assignment.assigned_by == owner["id"]
    audit = _audit(db_session, server["id"], membership.id, role.id)
    assert len(audit) == 1
    assert audit[0].changed_by == owner["id"]


@pytest.mark.parametrize(("permissions", "self_assignment"), [
    ({"manage_roles": True}, False),
    ({"ban_members": True, "manage_invites": True}, False),
    ({"manage_roles": True}, True),
])
def test_owner_can_assign_grants_without_holding_them(
    client, db_session, create_user, auth_headers, permissions, self_assignment
):
    owner = create_user()
    headers = auth_headers(owner)
    server_id = _create_server(client, owner, auth_headers)["id"]
    target = owner if self_assignment else create_user()
    if not self_assignment:
        _member(db_session, server_id, target["id"])
    path = f"/servers/{server_id}"
    context = client.get(f"{path}/authorization-context", headers=headers)
    assert context.status_code == 200
    assert context.json()["effective_permissions"] == []
    created = client.post(f"{path}/roles", headers=headers, json={
        "name": "Delegado", "position": 5, "permissions": permissions,
    })
    assert created.status_code == 201, created.text

    assigned = _assign_route(client, server_id, target["id"], created.json()["id"], headers)
    assert assigned.status_code == 204, assigned.text
    result = client.get(f"{path}/authorization-context", headers=auth_headers(target))
    assert result.status_code == 200
    assert set(result.json()["effective_permissions"]) == set(permissions)


def test_authorized_manager_can_put_role_below_own_hierarchy(
    client, db_session, create_user, auth_headers
):
    _, manager, server, target, membership = _manager_context(
        client, db_session, create_user, auth_headers
    )
    role = _role(db_session, server["id"], name="Inferior", position=5)

    response = _assign_route(
        client,
        server["id"],
        target["id"],
        role.id,
        auth_headers(manager),
    )

    assert response.status_code == 204
    assert db_session.scalar(
        select(ServerMemberRole.id).where(
            ServerMemberRole.member_id == membership.id,
            ServerMemberRole.role_id == role.id,
        )
    ) is not None


def test_put_requires_authentication(client):
    response = _assign_route(client, 1, 1, 1, {})
    assert response.status_code in {401, 403}


def test_member_without_manage_roles_is_forbidden(
    client, db_session, create_user, auth_headers
):
    owner = create_user()
    actor = create_user()
    target = create_user()
    server = _create_server(client, owner, auth_headers)
    _member(db_session, server["id"], actor["id"])
    _member(db_session, server["id"], target["id"])
    role = _role(db_session, server["id"], name="Cargo", position=1)
    db_session.commit()

    response = _assign_route(
        client, server["id"], target["id"], role.id, auth_headers(actor)
    )

    assert response.status_code == 403


@pytest.mark.parametrize("manager_position", [5, 4])
def test_manager_at_or_below_role_position_is_forbidden(
    client, db_session, create_user, auth_headers, manager_position
):
    owner, manager, server, target, _ = _manager_context(
        client, db_session, create_user, auth_headers
    )
    manager_role = db_session.scalar(
        select(ServerRole).where(
            ServerRole.server_id == server["id"],
            ServerRole.name == "Gerência",
        )
    )
    manager_role.position = manager_position
    role = _role(db_session, server["id"], name="Cargo", position=5)
    db_session.commit()

    response = _assign_route(
        client, server["id"], target["id"], role.id, auth_headers(manager)
    )

    assert response.status_code == 403


def test_foreign_server_role_and_nonmember_target_return_404(
    client, db_session, create_user, auth_headers
):
    owner = create_user()
    other_owner = create_user()
    target = create_user()
    server = _create_server(client, owner, auth_headers)
    other_server = _create_server(client, other_owner, auth_headers)
    foreign_role = _role(
        db_session, other_server["id"], name="Alheio", position=1
    )

    foreign = _assign_route(
        client,
        server["id"],
        target["id"],
        foreign_role.id,
        auth_headers(owner),
    )
    assert foreign.status_code == 404


@pytest.mark.parametrize("target_status", ["LEFT", "MISSING"])
def test_put_rejects_left_or_nonmember_target(
    client, db_session, create_user, auth_headers, target_status
):
    owner = create_user()
    target = create_user()
    server = _create_server(client, owner, auth_headers)
    if target_status == "LEFT":
        _member(
            db_session,
            server["id"],
            target["id"],
            member_status="LEFT",
        )
    role = _role(db_session, server["id"], name="Cargo", position=1)

    response = _assign_route(
        client,
        server["id"],
        target["id"],
        role.id,
        auth_headers(owner),
    )

    assert response.status_code == 404


def test_system_role_is_protected_for_owner_and_member_target_owner_is_protected(
    client, db_session, create_user, auth_headers
):
    owner, manager, server, target, _ = _manager_context(
        client, db_session, create_user, auth_headers
    )
    system_role = _role(
        db_session,
        server["id"],
        name="Sistema",
        position=1,
        is_system_role=True,
    )

    owner_response = _assign_route(
        client,
        server["id"],
        target["id"],
        system_role.id,
        auth_headers(owner),
    )
    assert owner_response.status_code == 403

    normal_role = _role(
        db_session, server["id"], name="Normal", position=1
    )
    manager_response = _assign_route(
        client,
        server["id"],
        owner["id"],
        normal_role.id,
        auth_headers(manager),
    )
    assert manager_response.status_code == 403


def test_duplicate_put_is_idempotent_and_is_default_is_not_protected(
    client, db_session, create_user, auth_headers
):
    owner = create_user()
    target = create_user()
    server = _create_server(client, owner, auth_headers)
    membership = _member(db_session, server["id"], target["id"])
    role = _role(
        db_session,
        server["id"],
        name="Padrão permitido",
        position=1,
        is_default=True,
    )

    first = _assign_route(
        client, server["id"], target["id"], role.id, auth_headers(owner)
    )
    second = _assign_route(
        client, server["id"], target["id"], role.id, auth_headers(owner)
    )

    assert first.status_code == second.status_code == 204
    assert first.content == second.content == b""
    assert len(_audit(db_session, server["id"], membership.id, role.id)) == 1


def test_member_cannot_receive_new_effective_grant_the_actor_lacks(
    client, db_session, create_user, auth_headers
):
    owner, manager, server, target, _ = _manager_context(
        client, db_session, create_user, auth_headers
    )
    role = _role(
        db_session,
        server["id"],
        name="Banimento",
        position=5,
        permissions={"ban_members": True},
    )
    db_session.commit()

    response = _assign_route(
        client, server["id"], target["id"], role.id, auth_headers(manager)
    )

    assert response.status_code == 403


def test_member_hierarchy_cannot_be_promoted_to_manager_level(
    client, db_session, create_user, auth_headers
):
    owner, manager, server, target, target_membership = _manager_context(
        client, db_session, create_user, auth_headers
    )
    same_level = _role(
        db_session, server["id"], name="Mesmo nível", position=10
    )
    db_session.commit()

    response = _assign_route(
        client,
        server["id"],
        target["id"],
        same_level.id,
        auth_headers(manager),
    )

    assert response.status_code == 403
    assert db_session.scalar(
        select(ServerMemberRole.id).where(
            ServerMemberRole.member_id == target_membership.id,
            ServerMemberRole.role_id == same_level.id,
        )
    ) is None


def test_owner_can_remove_role_and_response_is_empty_204(
    client, db_session, create_user, auth_headers
):
    owner = create_user()
    target = create_user()
    server = _create_server(client, owner, auth_headers)
    membership = _member(db_session, server["id"], target["id"])
    role = _role(db_session, server["id"], name="Removível", position=1)
    assignment = _assign(
        db_session,
        server_id=server["id"],
        membership=membership,
        role=role,
        assigned_by=owner["id"],
    )

    response = _remove_route(
        client, server["id"], target["id"], role.id, auth_headers(owner)
    )

    assert response.status_code == 204
    assert response.content == b""
    assert db_session.get(ServerMemberRole, assignment.id) is None
    audit = _audit(db_session, server["id"], membership.id, role.id)
    assert len(audit) == 1
    assert audit[0].changed_by == owner["id"]


def test_manager_can_remove_lower_role_from_lower_member(
    client, db_session, create_user, auth_headers
):
    owner, manager, server, target, membership = _manager_context(
        client, db_session, create_user, auth_headers
    )
    role = _role(db_session, server["id"], name="Inferior", position=5)
    assignment = _assign(
        db_session,
        server_id=server["id"],
        membership=membership,
        role=role,
        assigned_by=owner["id"],
    )

    response = _remove_route(
        client, server["id"], target["id"], role.id, auth_headers(manager)
    )

    assert response.status_code == 204
    assert db_session.get(ServerMemberRole, assignment.id) is None


def test_member_without_manage_roles_cannot_remove_role(
    client, db_session, create_user, auth_headers
):
    owner = create_user()
    actor = create_user()
    target = create_user()
    server = _create_server(client, owner, auth_headers)
    _member(db_session, server["id"], actor["id"])
    _member(db_session, server["id"], target["id"])
    role = _role(db_session, server["id"], name="Cargo", position=1)

    response = _remove_route(
        client, server["id"], target["id"], role.id, auth_headers(actor)
    )

    assert response.status_code == 403


@pytest.mark.parametrize("manager_position", [1, 5])
def test_member_without_strictly_higher_position_cannot_remove_role(
    client, db_session, create_user, auth_headers, manager_position
):
    owner, manager, server, target, _ = _manager_context(
        client, db_session, create_user, auth_headers
    )
    manager_role = db_session.scalar(
        select(ServerRole).where(
            ServerRole.server_id == server["id"],
            ServerRole.name == "Gerência",
        )
    )
    manager_role.position = manager_position
    role = _role(db_session, server["id"], name="Cargo", position=5)
    db_session.commit()

    response = _remove_route(
        client, server["id"], target["id"], role.id, auth_headers(manager)
    )

    assert response.status_code == 403


def test_delete_rejects_role_from_another_server_and_system_role(
    client, db_session, create_user, auth_headers
):
    owner = create_user()
    other_owner = create_user()
    target = create_user()
    server = _create_server(client, owner, auth_headers)
    other_server = _create_server(client, other_owner, auth_headers)
    _member(db_session, server["id"], target["id"])
    foreign_role = _role(
        db_session, other_server["id"], name="Alheio", position=1
    )
    foreign_response = _remove_route(
        client,
        server["id"],
        target["id"],
        foreign_role.id,
        auth_headers(owner),
    )
    assert foreign_response.status_code == 404

    system_role = _role(
        db_session,
        server["id"],
        name="Sistema",
        position=1,
        is_system_role=True,
    )
    system_response = _remove_route(
        client,
        server["id"],
        target["id"],
        system_role.id,
        auth_headers(owner),
    )
    assert system_response.status_code == 403


def test_delete_is_idempotent_and_does_not_create_audit_when_absent(
    client, db_session, create_user, auth_headers
):
    owner = create_user()
    target = create_user()
    server = _create_server(client, owner, auth_headers)
    membership = _member(db_session, server["id"], target["id"])
    role = _role(db_session, server["id"], name="Ausente", position=1)

    first = _remove_route(
        client, server["id"], target["id"], role.id, auth_headers(owner)
    )
    second = _remove_route(
        client, server["id"], target["id"], role.id, auth_headers(owner)
    )

    assert first.status_code == second.status_code == 204
    assert first.content == second.content == b""
    assert _audit(db_session, server["id"], membership.id, role.id) == []


def test_delete_requires_auth_and_nonowner_cannot_remove_owner_role(
    client, db_session, create_user, auth_headers
):
    no_auth = _remove_route(client, 1, 1, 1, {})
    assert no_auth.status_code in {401, 403}

    owner, manager, server, _, _ = _manager_context(
        client, db_session, create_user, auth_headers
    )
    owner_membership = db_session.scalar(
        select(ServerMember).where(
            ServerMember.server_id == server["id"],
            ServerMember.user_id == owner["id"],
        )
    )
    role = _role(db_session, server["id"], name="Owner", position=1)
    _assign(
        db_session,
        server_id=server["id"],
        membership=owner_membership,
        role=role,
        assigned_by=owner["id"],
    )

    response = _remove_route(
        client, server["id"], owner["id"], role.id, auth_headers(manager)
    )
    assert response.status_code == 403


@pytest.mark.parametrize("target_status", ["LEFT", "MISSING"])
def test_remove_rejects_left_or_nonmember_target(
    client, db_session, create_user, auth_headers, target_status
):
    owner = create_user()
    target = create_user()
    server = _create_server(client, owner, auth_headers)
    if target_status == "LEFT":
        _member(db_session, server["id"], target["id"], member_status="LEFT")
    role = _role(db_session, server["id"], name="Cargo", position=1)

    response = _remove_route(
        client, server["id"], target["id"], role.id, auth_headers(owner)
    )
    assert response.status_code == 404
