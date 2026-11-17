from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models import (
    Server,
    ServerBan,
    ServerInvite,
    ServerMember,
    ServerMemberRole,
    ServerRole,
    User,
)
from app.services.server_invite_service import hash_server_invite_token
from app.services.server_member_service import leave_server
from app.services.server_moderation_service import (
    ban_server_member,
    kick_server_member,
)


def _server(db_session, create_user, *, name="Servidor para convites API"):
    owner = create_user()
    server = Server(owner_id=owner["id"], name=name)
    db_session.add(server)
    db_session.flush()
    membership = ServerMember(
        server_id=server.id,
        user_id=owner["id"],
        status="ACTIVE",
    )
    db_session.add(membership)
    db_session.flush()
    return owner, server


def _add_member(db_session, server, user, *, status="ACTIVE"):
    membership = ServerMember(
        server_id=server.id,
        user_id=user["id"],
        status=status,
        left_at=(datetime.now(timezone.utc) if status == "LEFT" else None),
    )
    db_session.add(membership)
    db_session.flush()
    return membership


def _grant_manage_invites(db_session, server, owner, user):
    member = _add_member(db_session, server, user)
    role = ServerRole(
        server_id=server.id,
        name=f"Gerenciador de convites {user['id']}",
        position=1,
        permissions={"manage_invites": True},
        is_default=False,
        is_system_role=False,
    )
    db_session.add(role)
    db_session.flush()
    db_session.add(
        ServerMemberRole(
            server_id=server.id,
            member_id=member.id,
            role_id=role.id,
            assigned_by=owner["id"],
        )
    )
    db_session.flush()
    return member


def _create_invite(client, headers, server_id, **payload):
    response = client.post(
        f"/servers/{server_id}/invites",
        headers=headers,
        json=payload,
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_owner_creates_invite_and_raw_token_is_only_in_creation_response(
    client, db_session, create_user, auth_headers
):
    owner, server = _server(db_session, create_user)
    headers = auth_headers(owner)
    expiry = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()

    response = client.post(
        f"/servers/{server.id}/invites",
        headers=headers,
        json={"expires_at": expiry, "max_uses": 3},
    )

    assert response.status_code == 201, response.text
    created = response.json()
    assert created["token"]
    assert created["server_id"] == server.id
    assert created["created_at"]
    assert datetime.fromisoformat(created["expires_at"]) == datetime.fromisoformat(expiry)
    assert created["max_uses"] == 3
    assert created["uses_count"] == 0
    assert "token_hash" not in created
    stored = db_session.get(ServerInvite, created["id"])
    assert stored.created_by == owner["id"]
    assert stored.token_hash == hash_server_invite_token(created["token"])
    assert created["token"] != stored.token_hash

    listing = client.get(f"/servers/{server.id}/invites", headers=headers)
    assert listing.status_code == 200
    assert created["token"] not in listing.text
    assert stored.token_hash not in listing.text


def test_active_manager_can_create_and_list_invites(
    client, db_session, create_user, auth_headers
):
    owner, server = _server(db_session, create_user)
    manager = create_user()
    _grant_manage_invites(db_session, server, owner, manager)
    headers = auth_headers(manager)

    created = _create_invite(client, headers, server.id, max_uses=2)
    listed = client.get(f"/servers/{server.id}/invites", headers=headers)

    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()] == [created["id"]]
    assert "token_hash" not in listed.text
    assert created["token"] not in listed.text


def test_member_without_manage_invites_cannot_create_or_list(
    client, db_session, create_user, auth_headers
):
    owner, server = _server(db_session, create_user)
    member = create_user()
    _add_member(db_session, server, member)
    db_session.commit()
    headers = auth_headers(member)

    create_response = client.post(
        f"/servers/{server.id}/invites", headers=headers, json={}
    )
    list_response = client.get(
        f"/servers/{server.id}/invites", headers=headers
    )

    assert create_response.status_code == 403
    assert list_response.status_code == 403


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("post", "/servers/1/invites", {}),
        ("post", "/servers/1/invites/accept", {"token": "bad"}),
        ("get", "/servers/1/invites", None),
        ("delete", "/servers/1/invites/1", None),
    ],
)
def test_invite_routes_require_authentication(client, method, path, payload):
    response = getattr(client, method)(path, json=payload) if payload is not None else getattr(client, method)(path)
    assert response.status_code == 401


def test_create_invite_rejects_internal_fields_and_invalid_options(
    client, db_session, create_user, auth_headers
):
    owner, server = _server(db_session, create_user)
    headers = auth_headers(owner)
    cases = [
        {"created_by": owner["id"]},
        {"user_id": owner["id"]},
        {"max_uses": True},
        {"max_uses": 0},
        {"unexpected": "value"},
    ]

    for payload in cases:
        response = client.post(
            f"/servers/{server.id}/invites",
            headers=headers,
            json=payload,
        )
        assert response.status_code == 422


def test_accept_valid_invite_creates_membership_for_authenticated_user(
    client, db_session, create_user, auth_headers
):
    owner, server = _server(db_session, create_user)
    created = _create_invite(client, auth_headers(owner), server.id)
    entrant = create_user()

    response = client.post(
        f"/servers/{server.id}/invites/accept",
        headers=auth_headers(entrant),
        json={"token": created["token"]},
    )

    assert response.status_code == 200, response.text
    member = response.json()
    assert member["server_id"] == server.id
    assert member["user_id"] == entrant["id"]
    assert member["status"] == "ACTIVE"
    assert member["left_at"] is None
    assert "token_hash" not in response.text
    stored_invite = db_session.get(ServerInvite, created["id"])
    assert stored_invite.uses_count == 1


@pytest.mark.parametrize("exit_action", ["leave", "kick"])
def test_acceptance_reenters_member_after_leave_or_kick(
    client, db_session, create_user, auth_headers, exit_action
):
    owner, server = _server(db_session, create_user)
    target = create_user()
    membership = _add_member(db_session, server, target)
    db_session.commit()
    if exit_action == "leave":
        leave_server(db_session, db_session.get(User, target["id"]), server.id)
    else:
        kick_server_member(db_session, server.id, target["id"], owner["id"])
    created = _create_invite(client, auth_headers(owner), server.id)

    response = client.post(
        f"/servers/{server.id}/invites/accept",
        headers=auth_headers(target),
        json={"token": created["token"]},
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ACTIVE"
    assert response.json()["left_at"] is None
    assert db_session.get(ServerMember, membership.id).user_id == target["id"]
    assert db_session.get(ServerInvite, created["id"]).uses_count == 1


def test_acceptance_rejects_active_ban_without_consuming_invite(
    client, db_session, create_user, auth_headers
):
    owner, server = _server(db_session, create_user)
    target = create_user()
    _add_member(db_session, server, target)
    db_session.commit()
    created = _create_invite(client, auth_headers(owner), server.id)
    ban_server_member(db_session, server.id, target["id"], owner["id"])
    response = client.post(
        f"/servers/{server.id}/invites/accept",
        headers=auth_headers(target),
        json={"token": created["token"]},
    )

    assert response.status_code == 403
    assert db_session.get(ServerInvite, created["id"]).uses_count == 0
    assert db_session.scalar(
        select(ServerBan.id).where(
            ServerBan.server_id == server.id,
            ServerBan.user_id == target["id"],
            ServerBan.is_active.is_(True),
        )
    ) is not None


@pytest.mark.parametrize("invite_state", ["expired", "revoked", "exhausted"])
def test_acceptance_rejects_unusable_invite_states(
    client, db_session, create_user, auth_headers, invite_state
):
    owner, server = _server(db_session, create_user)
    target = create_user()
    headers = auth_headers(owner)
    if invite_state == "expired":
        created_at = datetime.now(timezone.utc) - timedelta(days=2)
        invite = ServerInvite(
            server_id=server.id,
            created_by=owner["id"],
            token_hash=hash_server_invite_token("expired-token"),
            created_at=created_at,
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        db_session.add(invite)
        db_session.flush()
        token = "expired-token"
    elif invite_state == "revoked":
        created = _create_invite(client, headers, server.id)
        token = created["token"]
        revoke = client.delete(
            f"/servers/{server.id}/invites/{created['id']}", headers=headers
        )
        assert revoke.status_code == 204
    else:
        created = _create_invite(client, headers, server.id, max_uses=1)
        token = created["token"]
        first_user = create_user()
        first_accept = client.post(
            f"/servers/{server.id}/invites/accept",
            headers=auth_headers(first_user),
            json={"token": token},
        )
        assert first_accept.status_code == 200

    response = client.post(
        f"/servers/{server.id}/invites/accept",
        headers=auth_headers(target),
        json={"token": token},
    )
    assert response.status_code == 409


def test_acceptance_rejects_invalid_and_foreign_server_tokens(
    client, db_session, create_user, auth_headers
):
    owner_a, server_a = _server(db_session, create_user)
    owner_b, server_b = _server(db_session, create_user, name="Outro servidor")
    created = _create_invite(client, auth_headers(owner_b), server_b.id)
    user = create_user()
    headers = auth_headers(user)

    invalid = client.post(
        f"/servers/{server_a.id}/invites/accept",
        headers=headers,
        json={"token": "invalid-token"},
    )
    foreign = client.post(
        f"/servers/{server_a.id}/invites/accept",
        headers=headers,
        json={"token": created["token"]},
    )

    assert invalid.status_code == 404
    assert foreign.status_code == 404
    assert db_session.get(ServerInvite, created["id"]).uses_count == 0


def test_list_invites_paginates_and_never_exposes_hash_or_token(
    client, db_session, create_user, auth_headers
):
    owner, server = _server(db_session, create_user)
    headers = auth_headers(owner)
    created = [
        _create_invite(client, headers, server.id)
        for _ in range(3)
    ]

    first_page = client.get(
        f"/servers/{server.id}/invites?limit=2&offset=0", headers=headers
    )
    second_page = client.get(
        f"/servers/{server.id}/invites?limit=2&offset=2", headers=headers
    )

    assert first_page.status_code == 200
    assert second_page.status_code == 200
    assert len(first_page.json()) == 2
    assert len(second_page.json()) == 1
    body = first_page.text + second_page.text
    for invite in created:
        assert invite["token"] not in body
        stored = db_session.get(ServerInvite, invite["id"])
        assert stored.token_hash not in body
    assert all("token_hash" not in item for item in first_page.json())


def test_revoke_invite_authorization_and_server_isolation(
    client, db_session, create_user, auth_headers
):
    owner_a, server_a = _server(db_session, create_user)
    owner_b, server_b = _server(db_session, create_user, name="Servidor B")
    member = create_user()
    _add_member(db_session, server_a, member)
    invite_a = _create_invite(client, auth_headers(owner_a), server_a.id)
    invite_b = _create_invite(client, auth_headers(owner_b), server_b.id)

    forbidden = client.delete(
        f"/servers/{server_a.id}/invites/{invite_a['id']}",
        headers=auth_headers(member),
    )
    foreign = client.delete(
        f"/servers/{server_a.id}/invites/{invite_b['id']}",
        headers=auth_headers(owner_a),
    )
    revoked = client.delete(
        f"/servers/{server_a.id}/invites/{invite_a['id']}",
        headers=auth_headers(owner_a),
    )

    assert forbidden.status_code == 403
    assert foreign.status_code == 404
    assert revoked.status_code == 204
    assert revoked.content == b""
    assert db_session.get(ServerInvite, invite_a["id"]).revoked_at is not None
    assert db_session.get(ServerInvite, invite_b["id"]).revoked_at is None


def test_invite_route_rejects_missing_server_and_bad_pagination(
    client, create_user, auth_headers
):
    user = create_user()
    headers = auth_headers(user)
    missing = client.get("/servers/999999/invites", headers=headers)
    bad_limit = client.get("/servers/1/invites?limit=101", headers=headers)
    assert missing.status_code == 404
    assert bad_limit.status_code == 422
