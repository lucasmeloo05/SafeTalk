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

import app.services.server_member_service as server_member_service
from app.database import get_db
from app.main import app
from app.models import (
    Server,
    ServerMember,
    ServerMemberRole,
    ServerRole,
    User,
)
from app.settings import settings
from conftest import test_engine


def _create_server(client: TestClient, headers: dict, name: str = "Membros"):
    response = client.post(
        "/servers/",
        json={"name": name},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _add_member(db_session, server_id: int, user_id: int, status: str = "ACTIVE"):
    membership = ServerMember(
        server_id=server_id,
        user_id=user_id,
        status=status,
        left_at=(
            datetime.now(timezone.utc)
            if status == "LEFT"
            else None
        ),
    )
    db_session.add(membership)
    db_session.flush()
    return membership


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/servers/1/members"),
        ("get", "/servers/1/members/1"),
        ("post", "/servers/1/leave"),
    ],
)
def test_member_routes_require_authentication(client, method, path):
    response = getattr(client, method)(path)

    assert response.status_code in {401, 403}


def test_member_routes_reject_invalid_jwt(client):
    response = client.get(
        "/servers/1/members",
        headers={"Authorization": "Bearer invalid-token"},
    )

    assert response.status_code == 401


def test_member_list_returns_only_active_members_and_minimal_profile(
    client,
    db_session,
    create_user,
    auth_headers,
):
    owner = create_user()
    active_user = create_user()
    left_user = create_user()
    server = _create_server(client, auth_headers(owner))
    _add_member(db_session, server["id"], active_user["id"])
    _add_member(db_session, server["id"], left_user["id"], "LEFT")

    response = client.get(
        f"/servers/{server['id']}/members",
        headers=auth_headers(active_user),
    )

    assert response.status_code == 200, response.text
    members = response.json()
    assert {member["user_id"] for member in members} == {
        owner["id"],
        active_user["id"],
    }
    assert all(
        set(member) == {"user_id", "username", "joined_at"}
        for member in members
    )
    assert all(member["user_id"] != left_user["id"] for member in members)


def test_member_list_requires_active_membership_and_hides_left_membership(
    client,
    db_session,
    create_user,
    auth_headers,
):
    owner = create_user()
    left_user = create_user()
    outsider = create_user()
    server = _create_server(client, auth_headers(owner))
    _add_member(db_session, server["id"], left_user["id"], "LEFT")

    left_response = client.get(
        f"/servers/{server['id']}/members",
        headers=auth_headers(left_user),
    )
    outsider_response = client.get(
        f"/servers/{server['id']}/members",
        headers=auth_headers(outsider),
    )

    assert left_response.status_code == outsider_response.status_code == 404
    assert left_response.json() == outsider_response.json()


def test_member_detail_returns_only_active_member_without_personal_data(
    client,
    db_session,
    create_user,
    auth_headers,
):
    owner = create_user()
    member = create_user()
    left_user = create_user()
    server = _create_server(client, auth_headers(owner))
    _add_member(db_session, server["id"], member["id"])
    _add_member(db_session, server["id"], left_user["id"], "LEFT")
    headers = auth_headers(member)

    response = client.get(
        f"/servers/{server['id']}/members/{owner['id']}",
        headers=headers,
    )
    left_response = client.get(
        f"/servers/{server['id']}/members/{left_user['id']}",
        headers=headers,
    )
    missing_response = client.get(
        f"/servers/{server['id']}/members/2147483647",
        headers=headers,
    )

    assert response.status_code == 200, response.text
    member_data = response.json()
    assert member_data["user_id"] == owner["id"]
    assert member_data["username"] == owner["username"]
    assert set(member_data) == {"user_id", "username", "joined_at"}
    assert member_data["joined_at"]
    assert left_response.status_code == missing_response.status_code == 404
    assert left_response.json() == missing_response.json()


def test_member_detail_does_not_expose_user_from_another_server(
    client,
    db_session,
    create_user,
    auth_headers,
):
    owner_a = create_user()
    owner_b = create_user()
    actor = create_user()
    target = create_user()
    server_a = _create_server(client, auth_headers(owner_a), "Servidor A")
    server_b = _create_server(client, auth_headers(owner_b), "Servidor B")
    _add_member(db_session, server_a["id"], actor["id"])
    _add_member(db_session, server_b["id"], target["id"])

    response = client.get(
        f"/servers/{server_a['id']}/members/{target['id']}",
        headers=auth_headers(actor),
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Membro não encontrado."}


def test_member_list_paginates_with_default_and_maximum_limits(
    client,
    db_session,
    create_user,
    auth_headers,
):
    owner = create_user()
    server = _create_server(client, auth_headers(owner))
    other_users = [
        User(
            username=f"member_page_{index}_{uuid4().hex[:8]}",
            email=f"member_page_{index}_{uuid4().hex[:8]}@example.com",
            password_hash="synthetic-test-hash",
            is_active=True,
        )
        for index in range(24)
    ]
    db_session.add_all(other_users)
    db_session.flush()
    db_session.add_all(
        [
            ServerMember(
                server_id=server["id"],
                user_id=user.id,
                status="ACTIVE",
            )
            for user in other_users
        ]
    )
    db_session.flush()
    headers = auth_headers(owner)

    first_page = client.get(
        f"/servers/{server['id']}/members",
        headers=headers,
    )
    second_page = client.get(
        f"/servers/{server['id']}/members?limit=100&offset=20",
        headers=headers,
    )
    too_many = client.get(
        f"/servers/{server['id']}/members?limit=101",
        headers=headers,
    )

    assert first_page.status_code == 200
    assert len(first_page.json()) == 20
    assert second_page.status_code == 200
    assert len(second_page.json()) == 5
    assert too_many.status_code == 422


def test_member_routes_return_not_found_for_missing_server(client, create_user, auth_headers):
    user = create_user()
    headers = auth_headers(user)

    list_response = client.get("/servers/2147483647/members", headers=headers)
    detail_response = client.get(
        "/servers/2147483647/members/1",
        headers=headers,
    )
    leave_response = client.post("/servers/2147483647/leave", headers=headers)

    assert list_response.status_code == detail_response.status_code == 404
    assert leave_response.status_code == 404


def test_member_can_leave_and_all_individual_roles_are_removed(
    client,
    db_session,
    create_user,
    auth_headers,
):
    owner = create_user()
    member_user = create_user()
    server = _create_server(client, auth_headers(owner))
    membership = _add_member(db_session, server["id"], member_user["id"])
    roles = [
        ServerRole(server_id=server["id"], name=f"cargo-{index}", position=index + 1)
        for index in range(3)
    ]
    db_session.add_all(roles)
    db_session.flush()
    assignments = [
        ServerMemberRole(
            member_id=membership.id,
            role_id=role.id,
            server_id=server["id"],
            assigned_by=owner["id"],
        )
        for role in roles
    ]
    db_session.add_all(assignments)
    db_session.flush()

    response = client.post(
        f"/servers/{server['id']}/leave",
        headers=auth_headers(member_user),
    )

    db_session.expire_all()
    updated_membership = db_session.get(ServerMember, membership.id)
    remaining_assignments = db_session.scalars(
        select(ServerMemberRole).where(
            ServerMemberRole.member_id == membership.id,
            ServerMemberRole.server_id == server["id"],
        )
    ).all()
    assert response.status_code == 204
    assert response.content == b""
    assert updated_membership.status == "LEFT"
    assert updated_membership.left_at is not None
    assert remaining_assignments == []


def test_owner_cannot_leave_before_transferring_ownership(
    client,
    db_session,
    create_user,
    auth_headers,
):
    owner = create_user()
    server = _create_server(client, auth_headers(owner))

    response = client.post(
        f"/servers/{server['id']}/leave",
        headers=auth_headers(owner),
    )

    membership = db_session.scalar(
        select(ServerMember).where(
            ServerMember.server_id == server["id"],
            ServerMember.user_id == owner["id"],
        )
    )
    assert response.status_code == 409
    assert membership.status == "ACTIVE"
    assert membership.left_at is None


def test_repeated_leave_returns_conflict_without_changing_left_membership(
    client,
    db_session,
    create_user,
    auth_headers,
):
    owner = create_user()
    member_user = create_user()
    server = _create_server(client, auth_headers(owner))
    membership = _add_member(db_session, server["id"], member_user["id"])
    headers = auth_headers(member_user)

    first_response = client.post(
        f"/servers/{server['id']}/leave",
        headers=headers,
    )
    db_session.expire_all()
    first_left_at = db_session.get(ServerMember, membership.id).left_at
    second_response = client.post(
        f"/servers/{server['id']}/leave",
        headers=headers,
    )

    assert first_response.status_code == 204
    assert second_response.status_code == 409
    db_session.expire_all()
    final_membership = db_session.get(ServerMember, membership.id)
    assert final_membership.status == "LEFT"
    assert final_membership.left_at == first_left_at


def test_leave_ignores_client_user_id_and_cannot_target_other_server(
    client,
    db_session,
    create_user,
    auth_headers,
):
    owner = create_user()
    actor = create_user()
    other_member = create_user()
    other_owner = create_user()
    server = _create_server(client, auth_headers(owner), "Servidor do ator")
    other_server = _create_server(client, auth_headers(other_owner), "Outro servidor")
    actor_membership = _add_member(db_session, server["id"], actor["id"])
    other_membership = _add_member(db_session, server["id"], other_member["id"])
    headers = auth_headers(actor)
    db_session.commit()

    wrong_server_response = client.post(
        f"/servers/{other_server['id']}/leave",
        headers=headers,
    )
    tampered_body_response = client.post(
        f"/servers/{server['id']}/leave",
        json={"user_id": other_member["id"]},
        headers=headers,
    )

    db_session.expire_all()
    assert wrong_server_response.status_code == 404
    assert tampered_body_response.status_code == 204
    assert db_session.get(ServerMember, actor_membership.id).status == "LEFT"
    assert db_session.get(ServerMember, other_membership.id).status == "ACTIVE"


def test_leave_rolls_back_role_cleanup_if_later_operation_fails(
    client,
    db_session,
    create_user,
    auth_headers,
    monkeypatch,
):
    owner = create_user()
    member_user = create_user()
    server = _create_server(client, auth_headers(owner))
    membership = _add_member(db_session, server["id"], member_user["id"])
    role = ServerRole(server_id=server["id"], name="cargo", position=1)
    db_session.add(role)
    db_session.flush()
    assignment = ServerMemberRole(
        member_id=membership.id,
        role_id=role.id,
        server_id=server["id"],
        assigned_by=owner["id"],
    )
    db_session.add(assignment)
    db_session.flush()
    db_session.commit()
    original_remove = server_member_service._remove_member_role_assignments

    def fail_after_removal(db, server_id, member_id):
        original_remove(db, server_id, member_id)
        raise SQLAlchemyError("falha simulada antes da transição")

    monkeypatch.setattr(
        server_member_service,
        "_remove_member_role_assignments",
        fail_after_removal,
    )
    response = client.post(
        f"/servers/{server['id']}/leave",
        headers=auth_headers(member_user),
    )

    db_session.expire_all()
    restored_membership = db_session.get(ServerMember, membership.id)
    restored_assignment = db_session.scalar(
        select(ServerMemberRole).where(ServerMemberRole.id == assignment.id)
    )
    assert response.status_code == 500
    assert restored_membership.status == "ACTIVE"
    assert restored_membership.left_at is None
    assert restored_assignment is not None


def test_two_concurrent_leave_requests_only_close_membership_once():
    suffix = uuid4().hex[:8]
    owner_id = None
    member_id = None
    server_id = None
    original_override = app.dependency_overrides.get(get_db)

    with Session(test_engine) as setup_db:
        owner = User(
            username=f"concurrent_owner_{suffix}",
            email=f"concurrent_owner_{suffix}@example.com",
            password_hash="synthetic-test-hash",
            is_active=True,
        )
        member = User(
            username=f"concurrent_member_{suffix}",
            email=f"concurrent_member_{suffix}@example.com",
            password_hash="synthetic-test-hash",
            is_active=True,
        )
        setup_db.add_all([owner, member])
        setup_db.flush()
        server = Server(owner_id=owner.id, name=f"Concorrencia {suffix}")
        setup_db.add(server)
        setup_db.flush()
        setup_db.add_all(
            [
                ServerMember(
                    server_id=server.id,
                    user_id=owner.id,
                    status="ACTIVE",
                ),
                ServerMember(
                    server_id=server.id,
                    user_id=member.id,
                    status="ACTIVE",
                ),
            ]
        )
        setup_db.commit()
        owner_id = owner.id
        member_id = member.id
        server_id = server.id

    now = int(datetime.now(timezone.utc).timestamp())
    token = jwt.encode(
        {"sub": str(member_id), "iat": now, "exp": now + 300},
        settings.jwt_secret_key,
        algorithm="HS256",
    )
    headers = {"Authorization": f"Bearer {token}"}
    barrier = Barrier(2)

    def override_get_db():
        with Session(test_engine) as db:
            yield db

    def send_leave_request():
        with TestClient(app) as client:
            barrier.wait(timeout=10)
            return client.post(
                f"/servers/{server_id}/leave",
                headers=headers,
            )

    try:
        app.dependency_overrides[get_db] = override_get_db
        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(lambda _: send_leave_request(), range(2)))

        assert sorted(response.status_code for response in responses) == [204, 409]
        with Session(test_engine) as verify_db:
            membership = verify_db.scalar(
                select(ServerMember).where(
                    ServerMember.server_id == server_id,
                    ServerMember.user_id == member_id,
                )
            )
            assert membership.status == "LEFT"
            assert membership.left_at is not None
    finally:
        if original_override is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = original_override
        with Session(test_engine) as cleanup_db:
            cleanup_db.execute(
                ServerMemberRole.__table__.delete().where(
                    ServerMemberRole.server_id == server_id
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
            cleanup_db.execute(
                User.__table__.delete().where(User.id.in_([owner_id, member_id]))
            )
            cleanup_db.commit()
