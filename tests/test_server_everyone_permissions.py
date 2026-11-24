import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier
from uuid import uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.main import app
from app.models import (
    Server,
    ServerConfigHistory,
    ServerMember,
    ServerMemberRole,
    ServerRole,
    User,
)
from app.settings import settings
from conftest import test_engine


def _create_server(client, headers, name="Configuração @everyone"):
    response = client.post(
        "/servers/",
        json={"name": name},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _permissions_path(server_id: int) -> str:
    return f"/servers/{server_id}/everyone-permissions"


def test_server_detail_exposes_current_known_everyone_permissions_only(
    client, db_session, create_user, auth_headers
):
    owner = create_user()
    member = create_user()
    headers = auth_headers(owner)
    server_data = _create_server(client, headers)
    server = db_session.get(Server, server_data["id"])
    assert server is not None
    server.everyone_permissions = {
        "manage_roles": True,
        "ban_members": False,
        "unknown_legacy_key": True,
        "kick_members": "true",
    }
    db_session.add(ServerMember(
        server_id=server.id,
        user_id=member["id"],
        status="ACTIVE",
    ))
    db_session.flush()

    detail = client.get(
        f"/servers/{server.id}",
        headers=auth_headers(member),
    )
    listing = client.get("/servers/", headers=auth_headers(member))

    assert detail.status_code == listing.status_code == 200
    assert detail.json()["everyone_permissions"] == {
        "manage_roles": True,
        "ban_members": False,
    }
    listed_server = next(item for item in listing.json() if item["id"] == server.id)
    assert listed_server["everyone_permissions"] == detail.json()["everyone_permissions"]


def test_everyone_update_preserves_unknown_legacy_keys_without_exposing_them(
    client, db_session, create_user, auth_headers
):
    owner = create_user()
    headers = auth_headers(owner)
    server_data = _create_server(client, headers)
    server = db_session.get(Server, server_data["id"])
    assert server is not None
    server.everyone_permissions = {
        "manage_roles": True,
        "future_permission": {"legacy": True},
    }
    db_session.flush()

    response = client.patch(
        _permissions_path(server.id),
        headers={**headers, "X-Expected-Permissions": '{"manage_roles":true}'},
        json={"kick_members": True},
    )

    assert response.status_code == 200, response.text
    assert response.json()["everyone_permissions"] == {"kick_members": True}
    db_session.refresh(server)
    assert server.everyone_permissions == {
        "kick_members": True,
        "future_permission": {"legacy": True},
    }


def test_owner_can_replace_everyone_permissions_and_history_is_recorded(
    client, db_session, create_user, auth_headers
):
    owner = create_user()
    headers = auth_headers(owner)
    server_data = _create_server(client, headers)
    server = db_session.get(Server, server_data["id"])
    assert server is not None
    server.everyone_permissions = {"manage_roles": True}
    db_session.flush()

    new_permissions = {
        "manage_invites": True,
        "mention_everyone": False,
    }
    response = client.patch(
        _permissions_path(server.id),
        json=new_permissions,
        headers={**headers, "X-Expected-Permissions": '{"manage_roles":true}'},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "server_id": server.id,
        "everyone_permissions": new_permissions,
    }
    db_session.refresh(server)
    assert server.everyone_permissions == new_permissions

    history = db_session.scalar(
        select(ServerConfigHistory).where(
            ServerConfigHistory.server_id == server.id,
            ServerConfigHistory.setting_name == "everyone_permissions",
        )
    )
    assert history is not None
    assert history.changed_by == owner["id"]
    assert json.loads(history.old_value) == {"manage_roles": True}
    assert json.loads(history.new_value) == new_permissions


def test_non_owner_with_manage_roles_cannot_change_everyone_permissions(
    client, db_session, create_user, auth_headers
):
    owner = create_user()
    member = create_user()
    owner_headers = auth_headers(owner)
    member_headers = auth_headers(member)
    server_data = _create_server(client, owner_headers)
    server = db_session.get(Server, server_data["id"])
    assert server is not None
    initial_permissions = {"ban_members": True}
    initial_response = client.patch(
        _permissions_path(server.id),
        json=initial_permissions,
        headers={**owner_headers, "X-Expected-Permissions": '{}'},
    )
    assert initial_response.status_code == 200, initial_response.text
    membership = ServerMember(
        server_id=server.id,
        user_id=member["id"],
        status="ACTIVE",
    )
    role = ServerRole(
        server_id=server.id,
        name="Gerente de cargos",
        position=1,
        permissions={"manage_roles": True},
    )
    db_session.add_all([membership, role])
    db_session.flush()
    db_session.add(
        ServerMemberRole(
            member_id=membership.id,
            role_id=role.id,
            server_id=server.id,
            assigned_by=owner["id"],
        )
    )
    db_session.flush()

    response = client.patch(
        _permissions_path(server.id),
        json={"manage_invites": True},
        headers=member_headers,
    )

    assert response.status_code == 403
    db_session.refresh(server)
    assert server.everyone_permissions == initial_permissions
    history = db_session.scalars(
        select(ServerConfigHistory).where(
            ServerConfigHistory.server_id == server.id
        )
    ).all()
    assert len(history) == 1


def test_everyone_permissions_route_requires_authentication(client):
    response = client.patch(
        _permissions_path(1),
        json={"manage_roles": True},
    )

    assert response.status_code in {401, 403}


def test_inactive_owner_cannot_change_everyone_permissions(
    client, db_session, create_user, auth_headers
):
    owner = create_user()
    headers = auth_headers(owner)
    server_data = _create_server(client, headers)
    membership = db_session.scalar(
        select(ServerMember).where(
            ServerMember.server_id == server_data["id"],
            ServerMember.user_id == owner["id"],
        )
    )
    assert membership is not None
    membership.status = "LEFT"
    membership.left_at = datetime.now(timezone.utc)
    db_session.flush()

    response = client.patch(
        _permissions_path(server_data["id"]),
        json={"manage_roles": True},
        headers=headers,
    )

    assert response.status_code == 404


def test_missing_server_is_rejected(client, create_user, auth_headers):
    user = create_user()

    response = client.patch(
        _permissions_path(999999),
        json={"manage_roles": True},
        headers=auth_headers(user),
    )

    assert response.status_code == 404


def test_empty_everyone_permissions_replaces_previous_grants(
    client, db_session, create_user, auth_headers
):
    owner = create_user()
    headers = auth_headers(owner)
    server_data = _create_server(client, headers)
    server = db_session.get(Server, server_data["id"])
    assert server is not None
    server.everyone_permissions = {"manage_roles": True}
    db_session.flush()

    response = client.patch(
        _permissions_path(server.id),
        json={},
        headers={**headers, "X-Expected-Permissions": '{"manage_roles":true}'},
    )

    assert response.status_code == 200, response.text
    assert response.json()["everyone_permissions"] == {}
    db_session.refresh(server)
    assert server.everyone_permissions == {}


@pytest.mark.parametrize(
    "payload",
    [
        {"unapproved_permission": True},
        {"manage_roles": 1},
        {"manage_roles": "true"},
        {"owner_id": 42},
        {"changed_by": 42},
    ],
)
def test_unknown_keys_non_boolean_values_and_client_fields_are_rejected(
    client, create_user, auth_headers, payload
):
    owner = create_user()
    headers = auth_headers(owner)
    server_data = _create_server(client, headers)

    response = client.patch(
        _permissions_path(server_data["id"]),
        json=payload,
        headers=headers,
    )

    assert response.status_code == 422


def test_audit_failure_rolls_back_everyone_permissions_update(
    client, db_session, create_user, auth_headers, monkeypatch
):
    owner = create_user()
    headers = auth_headers(owner)
    server_data = _create_server(client, headers)
    server = db_session.get(Server, server_data["id"])
    assert server is not None
    initial_permissions = {"manage_roles": True}
    initial_response = client.patch(
        _permissions_path(server.id),
        json=initial_permissions,
        headers={**headers, "X-Expected-Permissions": '{}'},
    )
    assert initial_response.status_code == 200, initial_response.text

    original_flush = db_session.flush

    def fail_when_flushing_history(objects=None):
        if objects is None and any(
            isinstance(item, ServerConfigHistory) for item in db_session.new
        ):
            raise SQLAlchemyError("falha simulada ao gravar auditoria")
        return original_flush() if objects is None else original_flush(objects)

    monkeypatch.setattr(db_session, "flush", fail_when_flushing_history)
    response = client.patch(
        _permissions_path(server.id),
        json={"manage_invites": True},
        headers={**headers, "X-Expected-Permissions": '{"manage_roles":true}'},
    )

    assert response.status_code == 500
    monkeypatch.setattr(db_session, "flush", original_flush)
    db_session.expire_all()
    persisted_server = db_session.get(Server, server.id)
    assert persisted_server is not None
    assert persisted_server.everyone_permissions == initial_permissions
    history = db_session.scalars(
        select(ServerConfigHistory).where(
            ServerConfigHistory.server_id == server.id,
            ServerConfigHistory.setting_name == "everyone_permissions",
        )
    ).all()
    assert len(history) == 1
    assert json.loads(history[0].new_value) == initial_permissions


@pytest.mark.parametrize("resource", ["everyone", "role"])
def test_concurrent_updates_keep_configuration_and_history_consistent(resource):
    suffix = uuid4().hex[:8]
    owner_id = None
    server_id = None
    original_override = app.dependency_overrides.get(get_db)

    with Session(test_engine) as setup_db:
        owner = User(
            username=f"settings_owner_{suffix}",
            email=f"settings_owner_{suffix}@example.com",
            password_hash="synthetic-test-hash",
            is_active=True,
        )
        setup_db.add(owner)
        setup_db.flush()
        server = Server(
            owner_id=owner.id,
            name=f"Configuração concorrente {suffix}",
            everyone_permissions={"manage_roles": True},
        )
        setup_db.add(server)
        setup_db.flush()
        setup_db.add(
            ServerMember(
                server_id=server.id,
                user_id=owner.id,
                status="ACTIVE",
            )
        )
        path = _permissions_path(server.id)
        setting = "everyone_permissions"
        if resource == "role":
            role = ServerRole(server_id=server.id, name="Inicial", position=1,
                              permissions={"manage_roles": True})
            setup_db.add(role)
            setup_db.flush()
            role_id = role.id
            path = f"/servers/{server.id}/roles/{role_id}"
            setting = f"server_role:{role_id}"
        setup_db.commit()
        owner_id = owner.id
        server_id = server.id

    now = int(datetime.now(timezone.utc).timestamp())
    token = jwt.encode(
        {"sub": str(owner_id), "iat": now, "exp": now + 300},
        settings.jwt_secret_key,
        algorithm="HS256",
    )
    headers = {"Authorization": f"Bearer {token}", "X-Expected-Permissions": '{"manage_roles":true}'}
    barrier = Barrier(2)
    configurations = [
        {"manage_invites": True},
        {"ban_members": True},
    ]

    def override_get_db():
        with Session(test_engine) as db:
            yield db

    def update_configuration(configuration):
        with TestClient(app) as client:
            barrier.wait(timeout=10)
            return client.patch(
                path,
                json=configuration if resource == "everyone" else {
                    "permissions": configuration, "name": next(iter(configuration)),
                },
                headers=headers,
            )

    try:
        app.dependency_overrides[get_db] = override_get_db
        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(update_configuration, configurations))

        assert sorted(response.status_code for response in responses) == [200, 409]
        loser = next(response for response in responses if response.status_code == 409)
        assert loser.json()["detail"]["code"] == "permissions_conflict"
        winner = configurations[next(i for i, response in enumerate(responses) if response.status_code == 200)]

        with Session(test_engine) as verify_db:
            history = verify_db.scalars(select(ServerConfigHistory).where(
                ServerConfigHistory.server_id == server_id,
                ServerConfigHistory.setting_name == setting,
            )).all()
            assert len(history) == 1
            before = json.loads(history[0].old_value)
            after = json.loads(history[0].new_value)
            if resource == "role":
                persisted = verify_db.get(ServerRole, role_id)
                assert persisted.name == next(iter(winner))
                assert before["permissions"] == {"manage_roles": True}
                assert after["permissions"] == persisted.permissions == winner
            else:
                assert before == {"manage_roles": True}
                assert after == verify_db.get(Server, server_id).everyone_permissions == winner
    finally:
        if original_override is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = original_override
        with Session(test_engine) as cleanup_db:
            cleanup_db.execute(
                ServerConfigHistory.__table__.delete().where(
                    ServerConfigHistory.server_id == server_id
                )
            )
            if resource == "role":
                cleanup_db.execute(ServerRole.__table__.delete().where(ServerRole.id == role_id))
            cleanup_db.execute(
                ServerMember.__table__.delete().where(
                    ServerMember.server_id == server_id
                )
            )
            cleanup_db.execute(
                Server.__table__.delete().where(Server.id == server_id)
            )
            cleanup_db.execute(User.__table__.delete().where(User.id == owner_id))
            cleanup_db.commit()

@pytest.mark.parametrize("resource", ["role", "everyone"])
@pytest.mark.parametrize("header, status", [(None, 428), ("invalid", 422),
    ('{"unknown":true}', 422), ('{"manage_roles":1}', 422), ('{"manage_roles":true}', 409)])
def test_permission_precondition(client, db_session, create_user, auth_headers, resource, header, status):
    headers = auth_headers(create_user())
    server_id = _create_server(client, headers)["id"]
    path = _permissions_path(server_id)
    payload = {"kick_members": True}
    if resource == "role":
        role = ServerRole(server_id=server_id, name="Original", position=1, permissions={})
        db_session.add(role)
        db_session.commit()
        path = f"/servers/{server_id}/roles/{role.id}"
        payload = {"name": "Alterado", "permissions": payload}
    if header is not None:
        headers["X-Expected-Permissions"] = header
    response = client.patch(path, headers=headers, json=payload)
    assert response.status_code == status, response.text
    if status == 409:
        assert response.json()["detail"]["code"] == "permissions_conflict"
    if resource == "role":
        db_session.refresh(role)
        assert (role.name, role.permissions) == ("Original", {})
    else:
        assert db_session.get(Server, server_id).everyone_permissions == {}

def test_permission_preflight_allows_expected_permissions(client):
    response = client.options("/servers/12/everyone-permissions", headers={
        "Origin": "http://localhost:5173",
        "Access-Control-Request-Method": "PATCH",
        "Access-Control-Request-Headers": "authorization,content-type,x-expected-permissions",
    })
    assert response.status_code == 200
    assert "x-expected-permissions" in response.headers["Access-Control-Allow-Headers"].lower()
