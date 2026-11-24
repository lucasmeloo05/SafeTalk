from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.models import Server, ServerMember


def _create_server(client: TestClient, headers: dict, name: str = "Comunidade"):
    return client.post(
        "/servers/",
        json={"name": name, "description": "Descrição inicial"},
        headers=headers,
    )


def test_create_server_sets_authenticated_user_as_owner_and_active_member(
    client: TestClient,
    db_session,
    create_user,
    auth_headers,
):
    owner = create_user()
    response = _create_server(client, auth_headers(owner))

    assert response.status_code == 201, response.text
    server = response.json()
    assert server["owner_id"] == owner["id"]
    assert server["name"] == "Comunidade"
    assert server["description"] == "Descrição inicial"

    membership = db_session.scalar(
        select(ServerMember).where(
            ServerMember.server_id == server["id"],
            ServerMember.user_id == owner["id"],
        )
    )
    assert membership is not None
    assert membership.status == "ACTIVE"
    assert membership.left_at is None


def test_create_server_rejects_client_supplied_owner_id(
    client: TestClient,
    db_session,
    create_user,
    auth_headers,
):
    authenticated = create_user()
    arbitrary_owner = create_user()

    response = client.post(
        "/servers/",
        json={"name": "Não deve ser criado", "owner_id": arbitrary_owner["id"]},
        headers=auth_headers(authenticated),
    )

    assert response.status_code == 422
    assert db_session.scalar(select(func.count()).select_from(Server)) == 0


def test_list_servers_returns_only_active_memberships(
    client: TestClient,
    db_session,
    create_user,
    auth_headers,
):
    user = create_user()
    another_user = create_user()
    headers = auth_headers(user)

    active_response = _create_server(client, headers, "Participação ativa")
    active_server_id = active_response.json()["id"]

    left_server = Server(owner_id=another_user["id"], name="Participação encerrada")
    other_server = Server(owner_id=another_user["id"], name="Servidor alheio")
    db_session.add_all([left_server, other_server])
    db_session.flush()
    db_session.add_all(
        [
            ServerMember(
                server_id=left_server.id,
                user_id=user["id"],
                status="LEFT",
                left_at=datetime.now(timezone.utc),
            ),
            ServerMember(
                server_id=other_server.id,
                user_id=another_user["id"],
                status="ACTIVE",
            ),
        ]
    )
    db_session.flush()

    response = client.get("/servers/", headers=headers)

    assert response.status_code == 200
    assert [server["id"] for server in response.json()] == [active_server_id]


def test_active_member_can_consult_server(
    client: TestClient,
    db_session,
    create_user,
    auth_headers,
):
    owner = create_user()
    member = create_user()
    server = _create_server(client, auth_headers(owner)).json()
    db_session.add(
        ServerMember(
            server_id=server["id"],
            user_id=member["id"],
            status="ACTIVE",
        )
    )
    db_session.flush()

    response = client.get(
        f"/servers/{server['id']}",
        headers=auth_headers(member),
    )

    assert response.status_code == 200
    assert response.json()["id"] == server["id"]


def test_missing_server_returns_same_not_found_response_for_consultation(
    client: TestClient,
    create_user,
    auth_headers,
):
    user = create_user()

    response = client.get(
        "/servers/2147483647",
        headers=auth_headers(user),
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Servidor não encontrado."}


def test_existing_server_without_membership_returns_not_found_for_consultation(
    client: TestClient,
    create_user,
    auth_headers,
):
    owner = create_user()
    outsider = create_user()
    server = _create_server(client, auth_headers(owner)).json()

    response = client.get(
        f"/servers/{server['id']}",
        headers=auth_headers(outsider),
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Servidor não encontrado."}


def test_discoverable_server_remains_hidden_from_external_users(
    client: TestClient, db_session, create_user, auth_headers,
):
    owner, outsider = create_user(), create_user()
    server = _create_server(client, auth_headers(owner)).json()
    db_session.execute(
        Server.__table__.update()
        .where(Server.id == server["id"])
        .values(is_discoverable=True)
    )
    db_session.flush()

    assert client.get("/servers/", headers=auth_headers(outsider)).json() == []
    detail = client.get(
        f"/servers/{server['id']}", headers=auth_headers(outsider)
    )
    assert detail.status_code == 404
    assert detail.json() == {"detail": "Servidor não encontrado."}


def test_left_member_cannot_consult_or_update_server(
    client: TestClient,
    db_session,
    create_user,
    auth_headers,
):
    owner = create_user()
    member = create_user()
    server = _create_server(client, auth_headers(owner)).json()
    membership = ServerMember(
        server_id=server["id"],
        user_id=member["id"],
        status="LEFT",
        left_at=datetime.now(timezone.utc),
    )
    db_session.add(membership)
    db_session.flush()

    headers = auth_headers(member)
    read_response = client.get(
        f"/servers/{server['id']}",
        headers=headers,
    )
    update_response = client.patch(
        f"/servers/{server['id']}",
        json={"name": "Alteração indevida"},
        headers=headers,
    )

    assert read_response.status_code == 404
    assert read_response.json() == {"detail": "Servidor não encontrado."}
    assert update_response.status_code == 404
    assert update_response.json() == read_response.json()


def test_missing_server_returns_not_found_for_update(
    client: TestClient,
    create_user,
    auth_headers,
):
    user = create_user()

    response = client.patch(
        "/servers/2147483647",
        json={"name": "Não deve ser atualizado"},
        headers=auth_headers(user),
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Servidor não encontrado."}


def test_owner_can_update_basic_server_information(
    client: TestClient,
    create_user,
    auth_headers,
):
    owner = create_user()
    headers = auth_headers(owner)
    server = _create_server(client, headers).json()

    response = client.patch(
        f"/servers/{server['id']}",
        json={"name": "  Nome atualizado  ", "description": None},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Nome atualizado"
    assert response.json()["description"] is None
    assert response.json()["owner_id"] == owner["id"]


def test_another_active_member_cannot_update_server(
    client: TestClient,
    db_session,
    create_user,
    auth_headers,
):
    owner = create_user()
    member = create_user()
    server = _create_server(client, auth_headers(owner)).json()
    db_session.add(
        ServerMember(
            server_id=server["id"],
            user_id=member["id"],
            status="ACTIVE",
        )
    )
    db_session.flush()

    response = client.patch(
        f"/servers/{server['id']}",
        json={"name": "Alteração indevida"},
        headers=auth_headers(member),
    )

    assert response.status_code == 403


def test_existing_server_without_membership_returns_not_found_for_update(
    client: TestClient,
    create_user,
    auth_headers,
):
    owner = create_user()
    outsider = create_user()
    server = _create_server(client, auth_headers(owner)).json()

    response = client.patch(
        f"/servers/{server['id']}",
        json={"name": "Alteração indevida"},
        headers=auth_headers(outsider),
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Servidor não encontrado."}


def test_update_rejects_owner_id_and_does_not_change_owner(
    client: TestClient,
    create_user,
    auth_headers,
):
    owner = create_user()
    arbitrary_owner = create_user()
    headers = auth_headers(owner)
    server = _create_server(client, headers).json()

    response = client.patch(
        f"/servers/{server['id']}",
        json={"name": "Nome válido", "owner_id": arbitrary_owner["id"]},
        headers=headers,
    )

    assert response.status_code == 422
    current = client.get(f"/servers/{server['id']}", headers=headers)
    assert current.status_code == 200
    assert current.json()["owner_id"] == owner["id"]
    assert current.json()["name"] == "Comunidade"


def test_server_create_and_update_reject_is_discoverable(
    client: TestClient, create_user, auth_headers,
):
    owner = create_user()
    headers = auth_headers(owner)

    create_response = client.post(
        "/servers/",
        json={"name": "Privado", "is_discoverable": True},
        headers=headers,
    )
    assert create_response.status_code == 422

    server = _create_server(client, headers).json()
    update_response = client.patch(
        f"/servers/{server['id']}",
        json={"is_discoverable": True},
        headers=headers,
    )
    assert update_response.status_code == 422
    current = client.get(f"/servers/{server['id']}", headers=headers)
    assert current.status_code == 200
    assert "is_discoverable" not in current.json()


def test_create_server_rolls_back_if_membership_creation_fails(
    client: TestClient,
    db_session,
    create_user,
    auth_headers,
    monkeypatch,
):
    owner = create_user()

    original_add = db_session.add

    def fail_membership_add(instance, _warn=True):
        if isinstance(instance, ServerMember):
            raise SQLAlchemyError("falha simulada ao persistir a participação")
        return original_add(instance, _warn=_warn)

    monkeypatch.setattr(db_session, "add", fail_membership_add)
    response = client.post(
        "/servers/",
        json={"name": "Transação incompleta"},
        headers=auth_headers(owner),
    )

    assert response.status_code == 500
    assert db_session.scalar(
        select(func.count()).select_from(Server).where(
            Server.name == "Transação incompleta"
        )
    ) == 0
    assert db_session.scalar(
        select(func.count()).select_from(ServerMember).where(
            ServerMember.user_id == owner["id"]
        )
    ) == 0
