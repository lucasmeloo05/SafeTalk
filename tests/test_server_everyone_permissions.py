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
        headers=headers,
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
        headers=owner_headers,
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
        headers=headers,
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
        headers=headers,
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
        headers=headers,
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


def test_concurrent_updates_keep_configuration_and_history_consistent():
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
        setup_db.commit()
        owner_id = owner.id
        server_id = server.id

    now = int(datetime.now(timezone.utc).timestamp())
    token = jwt.encode(
        {"sub": str(owner_id), "iat": now, "exp": now + 300},
        settings.jwt_secret_key,
        algorithm="HS256",
    )
    headers = {"Authorization": f"Bearer {token}"}
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
                _permissions_path(server_id),
                json=configuration,
                headers=headers,
            )

    try:
        app.dependency_overrides[get_db] = override_get_db
        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(update_configuration, configurations))

        assert [response.status_code for response in responses] == [200, 200]

        with Session(test_engine) as verify_db:
            persisted_server = verify_db.get(Server, server_id)
            history = verify_db.scalars(
                select(ServerConfigHistory)
                .where(
                    ServerConfigHistory.server_id == server_id,
                    ServerConfigHistory.setting_name == "everyone_permissions",
                )
                .order_by(ServerConfigHistory.id)
            ).all()
            assert persisted_server is not None
            assert len(history) == 2
            assert json.loads(history[0].old_value) == {"manage_roles": True}
            assert json.loads(history[1].old_value) == json.loads(
                history[0].new_value
            )
            assert json.loads(history[1].new_value) == (
                persisted_server.everyone_permissions
            )
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
