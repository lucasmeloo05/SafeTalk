from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import (
    Server,
    ServerAuditLog,
    ServerBan,
    ServerMember,
    ServerMemberRole,
    ServerRole,
)


def _server(db_session, create_user, *, name="Servidor de moderação"):
    owner = create_user()
    server = Server(owner_id=owner["id"], name=name)
    db_session.add(server)
    db_session.flush()
    owner_membership = ServerMember(
        server_id=server.id,
        user_id=owner["id"],
        status="ACTIVE",
    )
    db_session.add(owner_membership)
    db_session.flush()
    return owner, server


def _member(db_session, server, user):
    member = ServerMember(
        server_id=server.id,
        user_id=user["id"],
        status="ACTIVE",
    )
    db_session.add(member)
    db_session.flush()
    return member


def _ban(db_session, server, target, actor, **overrides):
    values = {
        "server_id": server.id,
        "user_id": target["id"],
        "banned_by": actor["id"],
        "target_highest_role_position": 0,
    }
    values.update(overrides)
    ban = ServerBan(**values)
    db_session.add(ban)
    db_session.flush()
    return ban


def test_active_ban_persists_target_and_actor(db_session, create_user):
    owner, server = _server(db_session, create_user)
    target = create_user()
    _member(db_session, server, target)

    ban = _ban(
        db_session,
        server,
        target,
        owner,
        reason="Violação das regras",
        target_highest_role_position=7,
    )

    persisted = db_session.get(ServerBan, ban.id)
    assert persisted is not None
    assert persisted.server_id == server.id
    assert persisted.user_id == target["id"]
    assert persisted.banned_by == owner["id"]
    assert persisted.is_active is True
    assert persisted.revoked_at is None
    assert persisted.revoked_by is None
    assert persisted.target_highest_role_position == 7
    assert persisted.reason == "Violação das regras"
    assert persisted.banned_at.tzinfo is not None


def test_revoked_ban_and_new_cycle_are_preserved(db_session, create_user):
    owner, server = _server(db_session, create_user)
    moderator = create_user()
    _member(db_session, server, moderator)
    target = create_user()
    _member(db_session, server, target)

    first = _ban(db_session, server, target, owner)
    first.is_active = False
    first.revoked_by = moderator["id"]
    first.revoked_at = first.banned_at + timedelta(seconds=1)
    db_session.flush()

    second = _ban(db_session, server, target, owner)
    cycles = db_session.scalars(
        select(ServerBan)
        .where(
            ServerBan.server_id == server.id,
            ServerBan.user_id == target["id"],
        )
        .order_by(ServerBan.id)
    ).all()

    assert [cycle.id for cycle in cycles] == [first.id, second.id]
    assert cycles[0].is_active is False
    assert cycles[0].revoked_by == moderator["id"]
    assert cycles[1].is_active is True
    assert cycles[1].revoked_at is None


def test_partial_unique_index_rejects_two_active_bans(db_session, create_user):
    owner, server = _server(db_session, create_user)
    target = create_user()
    _member(db_session, server, target)
    _ban(db_session, server, target, owner)

    db_session.add(
        ServerBan(
            server_id=server.id,
            user_id=target["id"],
            banned_by=owner["id"],
            target_highest_role_position=0,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_ban_target_must_belong_to_the_referenced_server(
    db_session, create_user
):
    owner_a, server_a = _server(db_session, create_user, name="Servidor A")
    owner_b, server_b = _server(db_session, create_user, name="Servidor B")
    target = create_user()
    _member(db_session, server_a, target)

    db_session.add(
        ServerBan(
            server_id=server_b.id,
            user_id=target["id"],
            banned_by=owner_b["id"],
            target_highest_role_position=0,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()
    assert owner_a["id"] != owner_b["id"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"revoked_at": datetime.now(timezone.utc)},
        {"is_active": False},
        {
            "is_active": False,
            "revoked_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
            "revoked_by": 999999,
        },
        {"target_highest_role_position": -1},
    ],
)
def test_invalid_ban_state_and_snapshot_values_are_rejected(
    db_session, create_user, overrides
):
    owner, server = _server(db_session, create_user)
    target = create_user()
    _member(db_session, server, target)
    values = {
        "server_id": server.id,
        "user_id": target["id"],
        "banned_by": owner["id"],
        "target_highest_role_position": 0,
    }
    values.update(overrides)
    db_session.add(ServerBan(**values))

    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_moderation_audit_persists_events_and_role_snapshot(
    db_session, create_user
):
    owner, server = _server(db_session, create_user)
    target = create_user()
    membership = _member(db_session, server, target)
    role = ServerRole(
        server_id=server.id,
        name="Moderador",
        description="Cargo anterior",
        position=4,
        permissions={"kick_members": True},
    )
    db_session.add(role)
    db_session.flush()
    assignment = ServerMemberRole(
        server_id=server.id,
        member_id=membership.id,
        role_id=role.id,
        assigned_by=owner["id"],
    )
    db_session.add(assignment)
    db_session.flush()

    snapshot = [
        {
            "role_id": role.id,
            "name": role.name,
            "description": role.description,
            "position": role.position,
            "permissions": role.permissions,
            "is_default": role.is_default,
            "is_system_role": role.is_system_role,
            "created_at": role.created_at.isoformat(),
            "assigned_at": assignment.assigned_at.isoformat(),
            "assigned_by": assignment.assigned_by,
        }
    ]
    ban = _ban(
        db_session,
        server,
        target,
        owner,
        target_highest_role_position=role.position,
    )
    db_session.add_all(
        [
            ServerAuditLog(
                server_id=server.id,
                event_type="MEMBER_BANNED",
                actor_user_id=owner["id"],
                target_user_id=target["id"],
                reason="Banimento de teste",
                ban_id=ban.id,
                role_snapshot=snapshot,
            ),
            ServerAuditLog(
                server_id=server.id,
                event_type="MEMBER_UNBANNED",
                actor_user_id=owner["id"],
                target_user_id=target["id"],
                ban_id=ban.id,
                role_snapshot=None,
            ),
            ServerAuditLog(
                server_id=server.id,
                event_type="MEMBER_KICKED",
                actor_user_id=owner["id"],
                target_user_id=target["id"],
                role_snapshot=[],
            ),
        ]
    )
    db_session.flush()

    events = db_session.scalars(
        select(ServerAuditLog)
        .where(ServerAuditLog.server_id == server.id)
        .order_by(ServerAuditLog.id)
    ).all()
    assert [event.event_type for event in events] == [
        "MEMBER_BANNED",
        "MEMBER_UNBANNED",
        "MEMBER_KICKED",
    ]
    assert events[0].ban_id == ban.id
    assert events[0].role_snapshot == snapshot
    assert events[0].reason == "Banimento de teste"
    assert events[0].occurred_at.tzinfo is not None
    assert events[1].ban_id == ban.id
    assert events[1].role_snapshot is None
    assert events[2].ban_id is None
    assert events[2].role_snapshot == []


@pytest.mark.parametrize(
    "event_type,needs_ban,role_snapshot",
    [
        ("MEMBER_KICKED", False, []),
        ("MEMBER_BANNED", True, []),
        ("MEMBER_UNBANNED", True, None),
        ("OWNERSHIP_TRANSFERRED", False, None),
    ],
)
def test_approved_moderation_event_snapshot_shapes_are_accepted(
    db_session, create_user, event_type, needs_ban, role_snapshot
):
    owner, server = _server(db_session, create_user)
    target = create_user()
    _member(db_session, server, target)
    ban = _ban(db_session, server, target, owner) if needs_ban else None

    event = ServerAuditLog(
        server_id=server.id,
        event_type=event_type,
        actor_user_id=owner["id"],
        target_user_id=target["id"],
        ban_id=ban.id if ban is not None else None,
        role_snapshot=role_snapshot,
    )
    db_session.add(event)
    db_session.flush()
    db_session.refresh(event)

    assert event.event_type == event_type
    assert event.ban_id == (ban.id if ban is not None else None)
    assert event.role_snapshot == role_snapshot


@pytest.mark.parametrize(
    "event_type,ban_id,role_snapshot",
    [
        ("UNKNOWN", None, []),
        ("MEMBER_KICKED", 1, []),
        ("MEMBER_BANNED", None, []),
        ("MEMBER_BANNED", 1, None),
        ("MEMBER_BANNED", 1, {}),
        ("MEMBER_UNBANNED", None, None),
        ("MEMBER_UNBANNED", 1, []),
        ("OWNERSHIP_TRANSFERRED", 1, None),
        ("OWNERSHIP_TRANSFERRED", None, []),
    ],
)
def test_invalid_audit_event_combinations_are_rejected(
    db_session, create_user, event_type, ban_id, role_snapshot
):
    owner, server = _server(db_session, create_user)
    target = create_user()
    _member(db_session, server, target)
    ban = None
    if ban_id == 1:
        ban = _ban(db_session, server, target, owner)

    db_session.add(
        ServerAuditLog(
            server_id=server.id,
            event_type=event_type,
            actor_user_id=owner["id"],
            target_user_id=target["id"],
            ban_id=ban.id if ban is not None else None,
            role_snapshot=role_snapshot,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_audit_ban_reference_cannot_cross_server_or_target(
    db_session, create_user
):
    owner_a, server_a = _server(db_session, create_user, name="Servidor A")
    owner_b, server_b = _server(db_session, create_user, name="Servidor B")
    target_a = create_user()
    target_b = create_user()
    _member(db_session, server_a, target_a)
    _member(db_session, server_b, target_b)
    ban = _ban(db_session, server_a, target_a, owner_a)

    db_session.add(
        ServerAuditLog(
            server_id=server_b.id,
            event_type="MEMBER_BANNED",
            actor_user_id=owner_b["id"],
            target_user_id=target_b["id"],
            ban_id=ban.id,
            role_snapshot=[],
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()
