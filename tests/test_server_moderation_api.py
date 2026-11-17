from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import app.routers.server_moderation as moderation_router
from app.models import (
    ServerAuditLog,
    ServerBan,
    ServerMember,
    ServerMemberRole,
    ServerRole,
)


def _create_server(client: TestClient, owner: dict, auth_headers):
    response = client.post(
        "/servers/",
        json={"name": f"Moderação {uuid4().hex[:8]}"},
        headers=auth_headers(owner),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _add_member(db_session, server_id: int, user: dict, *, member_status="ACTIVE"):
    membership = ServerMember(
        server_id=server_id,
        user_id=user["id"],
        status=member_status,
        left_at=(
            datetime.now(timezone.utc) if member_status == "LEFT" else None
        ),
    )
    db_session.add(membership)
    db_session.flush()
    return membership


def _grant_role(db_session, server_id: int, user: dict, *, position, permissions):
    membership = db_session.scalar(
        select(ServerMember).where(
            ServerMember.server_id == server_id,
            ServerMember.user_id == user["id"],
        )
    )
    role = ServerRole(
        server_id=server_id,
        name=f"Cargo {uuid4().hex[:8]}",
        position=position,
        permissions=permissions,
        is_default=False,
        is_system_role=False,
    )
    db_session.add(role)
    db_session.flush()
    db_session.add(
        ServerMemberRole(
            server_id=server_id,
            member_id=membership.id,
            role_id=role.id,
            assigned_by=membership.user_id,
        )
    )
    db_session.flush()
    return role


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/servers/1/members/2/kick"),
        ("post", "/servers/1/members/2/ban"),
        ("get", "/servers/1/bans"),
        ("post", "/servers/1/bans/1/unban"),
        ("get", "/servers/1/audit-logs"),
    ],
)
def test_moderation_routes_require_authentication(client, method, path):
    response = getattr(client, method)(path)
    assert response.status_code == 401


def test_kick_route_delegates_to_service_with_authenticated_actor(
    client, create_user, auth_headers, monkeypatch
):
    owner = create_user()
    server = _create_server(client, owner, auth_headers)
    calls = []

    def fake_kick(db, server_id, target_user_id, actor_user_id, reason):
        calls.append((server_id, target_user_id, actor_user_id, reason))

    monkeypatch.setattr(moderation_router, "kick_server_member", fake_kick)
    response = client.post(
        f"/servers/{server['id']}/members/987/kick",
        json={"reason": "auditoria"},
        headers=auth_headers(owner),
    )

    assert response.status_code == 204
    assert calls == [(server["id"], 987, owner["id"], "auditoria")]


def test_owner_can_kick_and_response_has_no_body(
    client, db_session, create_user, auth_headers
):
    owner = create_user()
    target = create_user()
    server = _create_server(client, owner, auth_headers)
    membership = _add_member(db_session, server["id"], target)

    response = client.post(
        f"/servers/{server['id']}/members/{target['id']}/kick",
        json={"reason": "  violação das regras  "},
        headers=auth_headers(owner),
    )

    assert response.status_code == 204
    assert response.content == b""
    assert db_session.get(ServerMember, membership.id).status == "LEFT"
    audit = db_session.scalar(
        select(ServerAuditLog).where(
            ServerAuditLog.server_id == server["id"],
            ServerAuditLog.event_type == "MEMBER_KICKED",
        )
    )
    assert audit.reason == "violação das regras"
    assert audit.ban_id is None


def test_owner_can_ban_and_response_excludes_internal_role_snapshot(
    client, db_session, create_user, auth_headers
):
    owner = create_user()
    target = create_user()
    server = _create_server(client, owner, auth_headers)
    target_membership = _add_member(db_session, server["id"], target)

    response = client.post(
        f"/servers/{server['id']}/members/{target['id']}/ban",
        json={"reason": "abuso"},
        headers=auth_headers(owner),
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["server_id"] == server["id"]
    assert body["user_id"] == target["id"]
    assert body["banned_by"] == owner["id"]
    assert body["reason"] == "abuso"
    assert body["is_active"] is True
    assert "role_snapshot" not in body
    assert "target_highest_role_position" not in body
    assert db_session.get(ServerMember, target_membership.id).status == "LEFT"


@pytest.mark.parametrize(
    ("operation", "permission"),
    [("kick", "kick_members"), ("ban", "ban_members")],
)
def test_common_member_moderation_requires_matching_permission(
    client, db_session, create_user, auth_headers, operation, permission
):
    owner, actor, target = create_user(), create_user(), create_user()
    server = _create_server(client, owner, auth_headers)
    _add_member(db_session, server["id"], actor)
    _add_member(db_session, server["id"], target)
    # A high role without the operation-specific grant is insufficient.
    _grant_role(
        db_session,
        server["id"],
        actor,
        position=10,
        permissions={"unban_members": True},
    )

    response = client.post(
        f"/servers/{server['id']}/members/{target['id']}/{operation}",
        headers=auth_headers(actor),
    )
    assert response.status_code == 403


@pytest.mark.parametrize(
    ("operation", "permission"),
    [("kick", "kick_members"), ("ban", "ban_members")],
)
def test_authorized_member_can_use_kick_or_ban_service(
    client, db_session, create_user, auth_headers, operation, permission
):
    owner, actor, target = create_user(), create_user(), create_user()
    server = _create_server(client, owner, auth_headers)
    _add_member(db_session, server["id"], actor)
    _add_member(db_session, server["id"], target)
    _grant_role(
        db_session,
        server["id"],
        actor,
        position=10,
        permissions={permission: True},
    )
    _grant_role(
        db_session,
        server["id"],
        target,
        position=2,
        permissions={},
    )

    response = client.post(
        f"/servers/{server['id']}/members/{target['id']}/{operation}",
        headers=auth_headers(actor),
    )

    assert response.status_code == (204 if operation == "kick" else 201)


def test_moderation_routes_reject_foreign_target_and_missing_ids(
    client, db_session, create_user, auth_headers
):
    owner_a, owner_b, target = create_user(), create_user(), create_user()
    server_a = _create_server(client, owner_a, auth_headers)
    server_b = _create_server(client, owner_b, auth_headers)
    _add_member(db_session, server_b["id"], target)
    response = client.post(
        f"/servers/{server_a['id']}/members/{target['id']}/kick",
        headers=auth_headers(owner_a),
    )
    assert response.status_code == 404
    missing_target = client.post(
        f"/servers/{server_a['id']}/members/2147483647/ban",
        headers=auth_headers(owner_a),
    )
    assert missing_target.status_code == 404
    missing_server = client.get(
        f"/servers/2147483647/bans", headers=auth_headers(owner_a)
    )
    assert missing_server.status_code == 404
    assert server_b["id"] != server_a["id"]


@pytest.mark.parametrize(
    "payload",
    [{"reason": " "}, {"reason": "x" * 501}, {"actor_user_id": 1}],
)
def test_moderation_body_rejects_invalid_reason_and_internal_fields(
    client, create_user, auth_headers, payload
):
    owner = create_user()
    server = _create_server(client, owner, auth_headers)
    response = client.post(
        f"/servers/{server['id']}/members/2/kick",
        json=payload,
        headers=auth_headers(owner),
    )
    assert response.status_code == 422


def test_unban_owner_and_authorized_member_return_no_content(
    client, db_session, create_user, auth_headers
):
    owner, manager, target = create_user(), create_user(), create_user()
    server = _create_server(client, owner, auth_headers)
    _add_member(db_session, server["id"], manager)
    _add_member(db_session, server["id"], target)
    _grant_role(
        db_session,
        server["id"],
        manager,
        position=1,
        permissions={"unban_members": True},
    )
    ban_response = client.post(
        f"/servers/{server['id']}/members/{target['id']}/ban",
        headers=auth_headers(owner),
    )
    assert ban_response.status_code == 201
    ban_id = ban_response.json()["id"]

    response = client.post(
        f"/servers/{server['id']}/bans/{ban_id}/unban",
        json={"reason": "revisado"},
        headers=auth_headers(manager),
    )
    assert response.status_code == 204
    assert response.content == b""
    ban = db_session.get(ServerBan, ban_id)
    assert ban.is_active is False
    assert ban.revoked_by == manager["id"]
    assert db_session.scalar(
        select(ServerAuditLog).where(
            ServerAuditLog.server_id == server["id"],
            ServerAuditLog.event_type == "MEMBER_UNBANNED",
        )
    ).reason == "revisado"


def test_unban_rejects_member_without_unban_permission(
    client, db_session, create_user, auth_headers
):
    owner, member, target = create_user(), create_user(), create_user()
    server = _create_server(client, owner, auth_headers)
    _add_member(db_session, server["id"], member)
    _add_member(db_session, server["id"], target)
    _grant_role(
        db_session,
        server["id"],
        member,
        position=10,
        permissions={"kick_members": True},
    )
    ban = client.post(
        f"/servers/{server['id']}/members/{target['id']}/ban",
        headers=auth_headers(owner),
    ).json()

    response = client.post(
        f"/servers/{server['id']}/bans/{ban['id']}/unban",
        headers=auth_headers(member),
    )

    assert response.status_code == 403
    assert db_session.get(ServerBan, ban["id"]).is_active is True


def test_unban_rejects_missing_cross_server_and_revoked_ban(
    client, db_session, create_user, auth_headers
):
    owner_a, owner_b, target = create_user(), create_user(), create_user()
    server_a = _create_server(client, owner_a, auth_headers)
    server_b = _create_server(client, owner_b, auth_headers)
    _add_member(db_session, server_b["id"], target)
    foreign_ban = client.post(
        f"/servers/{server_b['id']}/members/{target['id']}/ban",
        headers=auth_headers(owner_b),
    ).json()

    cross_server = client.post(
        f"/servers/{server_a['id']}/bans/{foreign_ban['id']}/unban",
        headers=auth_headers(owner_a),
    )
    missing = client.post(
        f"/servers/{server_a['id']}/bans/2147483647/unban",
        headers=auth_headers(owner_a),
    )
    assert cross_server.status_code == missing.status_code == 404

    revoked = client.post(
        f"/servers/{server_b['id']}/bans/{foreign_ban['id']}/unban",
        headers=auth_headers(owner_b),
    )
    repeated = client.post(
        f"/servers/{server_b['id']}/bans/{foreign_ban['id']}/unban",
        headers=auth_headers(owner_b),
    )
    assert revoked.status_code == 204
    assert repeated.status_code == 409


def test_ban_list_visibility_pagination_and_active_filter(
    client, db_session, create_user, auth_headers
):
    owner, manager, target_a, target_b = (
        create_user(), create_user(), create_user(), create_user()
    )
    server = _create_server(client, owner, auth_headers)
    _add_member(db_session, server["id"], manager)
    _add_member(db_session, server["id"], target_a)
    _add_member(db_session, server["id"], target_b)
    _grant_role(
        db_session,
        server["id"],
        manager,
        position=1,
        permissions={"unban_members": True},
    )

    first_ban = client.post(
        f"/servers/{server['id']}/members/{target_a['id']}/ban",
        headers=auth_headers(owner),
    ).json()
    client.post(
        f"/servers/{server['id']}/bans/{first_ban['id']}/unban",
        headers=auth_headers(owner),
    )
    client.post(
        f"/servers/{server['id']}/members/{target_b['id']}/ban",
        headers=auth_headers(owner),
    )

    owner_page = client.get(
        f"/servers/{server['id']}/bans?limit=1",
        headers=auth_headers(owner),
    )
    owner_second_page = client.get(
        f"/servers/{server['id']}/bans?limit=1&offset=1",
        headers=auth_headers(owner),
    )
    manager_list = client.get(
        f"/servers/{server['id']}/bans",
        headers=auth_headers(manager),
    )
    no_permission = create_user()
    _add_member(db_session, server["id"], no_permission)
    denied = client.get(
        f"/servers/{server['id']}/bans",
        headers=auth_headers(no_permission),
    )

    assert owner_page.status_code == 200
    assert len(owner_page.json()) == 1
    assert len(owner_second_page.json()) == 1
    assert owner_second_page.json()[0]["id"] != owner_page.json()[0]["id"]
    assert manager_list.status_code == 200
    assert len(manager_list.json()) == 1
    assert manager_list.json()[0]["is_active"] is True
    assert denied.status_code == 403


def test_audit_logs_are_owner_only_filtered_paginated_and_redacted(
    client, db_session, create_user, auth_headers
):
    owner, member, foreign_owner, foreign_target = (
        create_user(), create_user(), create_user(), create_user()
    )
    server = _create_server(client, owner, auth_headers)
    foreign_server = _create_server(client, foreign_owner, auth_headers)
    _add_member(db_session, server["id"], member)
    targets = [create_user(), create_user()]
    for target in targets:
        _add_member(db_session, server["id"], target)
    for target in targets:
        response = client.post(
            f"/servers/{server['id']}/members/{target['id']}/kick",
            headers=auth_headers(owner),
        )
        assert response.status_code == 204
    _add_member(db_session, foreign_server["id"], foreign_target)
    foreign_event = client.post(
        f"/servers/{foreign_server['id']}/members/{foreign_target['id']}/kick",
        headers=auth_headers(foreign_owner),
    )
    assert foreign_event.status_code == 204

    response = client.get(
        f"/servers/{server['id']}/audit-logs"
        f"?event_type=MEMBER_KICKED&actor_user_id={owner['id']}"
        f"&target_user_id={targets[0]['id']}&limit=1",
        headers=auth_headers(owner),
    )
    denied = client.get(
        f"/servers/{server['id']}/audit-logs",
        headers=auth_headers(member),
    )
    invalid_filter = client.get(
        f"/servers/{server['id']}/audit-logs?event_type=UNKNOWN",
        headers=auth_headers(owner),
    )

    assert response.status_code == 200
    assert len(response.json()) == 1
    item = response.json()[0]
    assert item["target_user_id"] == targets[0]["id"]
    assert item["event_type"] == "MEMBER_KICKED"
    assert "role_snapshot" not in item
    second_page = client.get(
        f"/servers/{server['id']}/audit-logs?event_type=MEMBER_KICKED"
        f"&actor_user_id={owner['id']}&limit=1&offset=0",
        headers=auth_headers(owner),
    )
    audit_page_two = client.get(
        f"/servers/{server['id']}/audit-logs?event_type=MEMBER_KICKED"
        f"&actor_user_id={owner['id']}&limit=1&offset=1",
        headers=auth_headers(owner),
    )
    assert second_page.status_code == 200
    assert len(second_page.json()) == 1
    assert len(audit_page_two.json()) == 1
    assert audit_page_two.json()[0]["id"] != second_page.json()[0]["id"]
    assert denied.status_code == 403
    assert invalid_filter.status_code == 422
    server_a_events = client.get(
        f"/servers/{server['id']}/audit-logs", headers=auth_headers(owner)
    )
    assert len(server_a_events.json()) == 2
