import json
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


def _add_member(db_session, server_id: int, user_id: int, *, member_status="ACTIVE"):
    member = ServerMember(
        server_id=server_id,
        user_id=user_id,
        status=member_status,
        left_at=(
            datetime.now(timezone.utc) if member_status == "LEFT" else None
        ),
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
    permissions: dict | None = None,
    is_default: bool = False,
    is_system_role: bool = False,
) -> ServerRole:
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


def _assign_role(db_session, *, server_id, membership, role, assigned_by):
    assignment = ServerMemberRole(
        server_id=server_id,
        member_id=membership.id,
        role_id=role.id,
        assigned_by=assigned_by,
    )
    db_session.add(assignment)
    db_session.flush()
    return assignment


def _delete_role(client, server_id, role_id, headers):
    return client.delete(
        f"/servers/{server_id}/roles/{role_id}",
        headers=headers,
    )


def _create_manager_context(client, db_session, create_user, auth_headers):
    owner = create_user()
    manager = create_user()
    server = _create_server(client, owner, auth_headers)
    membership = _add_member(db_session, server["id"], manager["id"])
    manager_role = _add_role(
        db_session,
        server["id"],
        name="Gerência",
        position=10,
        permissions={"manage_roles": True},
    )
    _assign_role(
        db_session,
        server_id=server["id"],
        membership=membership,
        role=manager_role,
        assigned_by=owner["id"],
    )
    target_role = _add_role(
        db_session,
        server["id"],
        name="Cargo excluível",
        position=5,
    )
    return owner, manager, server, target_role


def test_owner_deletes_role_with_204_empty_body_and_audit(
    client, db_session, create_user, auth_headers
):
    owner = create_user()
    server = _create_server(client, owner, auth_headers)
    role = _add_role(
        db_session,
        server["id"],
        name="Cargo removido",
        position=1,
        permissions={"kick_members": False},
    )
    role_id = role.id

    response = _delete_role(
        client, server["id"], role_id, auth_headers(owner)
    )

    assert response.status_code == 204
    assert response.content == b""
    assert db_session.get(ServerRole, role_id) is None
    audit = db_session.scalar(
        select(ServerConfigHistory).where(
            ServerConfigHistory.server_id == server["id"],
            ServerConfigHistory.setting_name == f"server_role:{role_id}",
        )
    )
    assert audit is not None
    assert audit.changed_by == owner["id"]
    assert json.loads(audit.old_value)["id"] == role_id
    assert json.loads(audit.new_value) == {"deleted": True}


def test_authorized_manager_deletes_role_below_own_hierarchy(
    client, db_session, create_user, auth_headers
):
    owner, manager, server, role = _create_manager_context(
        client, db_session, create_user, auth_headers
    )

    response = _delete_role(
        client, server["id"], role.id, auth_headers(manager)
    )

    assert response.status_code == 204
    assert response.content == b""
    assert db_session.get(ServerRole, role.id) is None
    audit = db_session.scalar(
        select(ServerConfigHistory).where(
            ServerConfigHistory.server_id == server["id"],
            ServerConfigHistory.setting_name == f"server_role:{role.id}",
        )
    )
    assert audit.changed_by == manager["id"]


def test_delete_role_requires_authentication(client):
    response = _delete_role(client, 1, 1, {})
    assert response.status_code in {401, 403}


def test_member_without_manage_roles_cannot_delete(client, db_session, create_user, auth_headers):
    owner = create_user()
    member = create_user()
    server = _create_server(client, owner, auth_headers)
    _add_member(db_session, server["id"], member["id"])
    role = _add_role(db_session, server["id"], name="Cargo", position=1)
    db_session.commit()

    response = _delete_role(
        client, server["id"], role.id, auth_headers(member)
    )

    assert response.status_code == 403
    assert db_session.get(ServerRole, role.id) is not None


@pytest.mark.parametrize("manager_position", [5, 4])
def test_manager_without_strictly_higher_hierarchy_cannot_delete(
    client, db_session, create_user, auth_headers, manager_position
):
    owner = create_user()
    manager = create_user()
    server = _create_server(client, owner, auth_headers)
    membership = _add_member(db_session, server["id"], manager["id"])
    manager_role = _add_role(
        db_session,
        server["id"],
        name="Gerência",
        position=manager_position,
        permissions={"manage_roles": True},
    )
    _assign_role(
        db_session,
        server_id=server["id"],
        membership=membership,
        role=manager_role,
        assigned_by=owner["id"],
    )
    target = _add_role(db_session, server["id"], name="Alvo", position=5)
    db_session.commit()

    response = _delete_role(
        client, server["id"], target.id, auth_headers(manager)
    )

    assert response.status_code == 403
    assert db_session.get(ServerRole, target.id) is not None


def test_owner_cannot_delete_system_role(client, db_session, create_user, auth_headers):
    owner = create_user()
    server = _create_server(client, owner, auth_headers)
    role = _add_role(
        db_session,
        server["id"],
        name="Reservado",
        position=1,
        is_system_role=True,
    )
    db_session.commit()

    response = _delete_role(
        client, server["id"], role.id, auth_headers(owner)
    )

    assert response.status_code == 403
    assert db_session.get(ServerRole, role.id) is not None


def test_missing_or_foreign_server_role_returns_not_found(
    client, db_session, create_user, auth_headers
):
    owner = create_user()
    other_owner = create_user()
    server = _create_server(client, owner, auth_headers)
    other_server = _create_server(client, other_owner, auth_headers)
    foreign_role = _add_role(
        db_session,
        other_server["id"],
        name="Cargo de outro servidor",
        position=1,
    )
    db_session.commit()

    missing = _delete_role(
        client, server["id"], foreign_role.id + 999, auth_headers(owner)
    )
    foreign = _delete_role(
        client, server["id"], foreign_role.id, auth_headers(owner)
    )

    assert missing.status_code == 404
    assert foreign.status_code == 404
    assert db_session.get(ServerRole, foreign_role.id) is not None


@pytest.mark.parametrize("member_status", ["ACTIVE", "LEFT"])
def test_role_with_active_or_left_member_assignment_returns_conflict(
    client, db_session, create_user, auth_headers, member_status
):
    owner = create_user()
    assigned_user = create_user()
    server = _create_server(client, owner, auth_headers)
    membership = _add_member(
        db_session,
        server["id"],
        assigned_user["id"],
        member_status=member_status,
    )
    role = _add_role(db_session, server["id"], name="Atribuído", position=1)
    assignment = _assign_role(
        db_session,
        server_id=server["id"],
        membership=membership,
        role=role,
        assigned_by=owner["id"],
    )
    db_session.commit()

    response = _delete_role(
        client, server["id"], role.id, auth_headers(owner)
    )

    assert response.status_code == 409
    assert db_session.get(ServerRole, role.id) is not None
    assert db_session.get(ServerMemberRole, assignment.id) is not None


def test_left_actor_cannot_delete_role(
    client, db_session, create_user, auth_headers
):
    owner = create_user()
    left_user = create_user()
    server = _create_server(client, owner, auth_headers)
    _add_member(
        db_session, server["id"], left_user["id"], member_status="LEFT"
    )
    role = _add_role(db_session, server["id"], name="Cargo", position=1)
    db_session.commit()

    response = _delete_role(
        client, server["id"], role.id, auth_headers(left_user)
    )

    assert response.status_code == 404
    assert db_session.get(ServerRole, role.id) is not None


def test_get_post_and_patch_role_routes_remain_available(
    client, db_session, create_user, auth_headers
):
    owner = create_user()
    server = _create_server(client, owner, auth_headers)
    headers = auth_headers(owner)
    created = client.post(
        f"/servers/{server['id']}/roles",
        json={"name": "Inicial", "position": 1},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    role_id = created.json()["id"]

    listed = client.get(f"/servers/{server['id']}/roles", headers=headers)
    detailed = client.get(
        f"/servers/{server['id']}/roles/{role_id}", headers=headers
    )
    updated = client.patch(
        f"/servers/{server['id']}/roles/{role_id}",
        json={"name": "Atualizado"},
        headers=headers,
    )

    assert listed.status_code == 200
    assert detailed.status_code == 200
    assert updated.status_code == 200
    assert updated.json()["name"] == "Atualizado"
