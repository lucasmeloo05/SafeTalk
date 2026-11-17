from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Server,
    ServerAuditLog,
    ServerBan,
    ServerMember,
    ServerMemberRole,
    User,
)
from app.services.server_moderation_service import (
    ban_server_member,
    kick_server_member,
    unban_server_member,
)
from conftest import test_engine


def _persistent_context(*, target_left=False, add_active_ban=False):
    suffix = uuid4().hex[:10]
    with Session(test_engine) as db:
        owner = User(
            username=f"mod_owner_{suffix}",
            email=f"mod_owner_{suffix}@example.com",
            password_hash="synthetic-test-hash",
            is_active=True,
        )
        target = User(
            username=f"mod_target_{suffix}",
            email=f"mod_target_{suffix}@example.com",
            password_hash="synthetic-test-hash",
            is_active=True,
        )
        db.add_all([owner, target])
        db.flush()
        server = Server(owner_id=owner.id, name=f"Moderação concorrente {suffix}")
        db.add(server)
        db.flush()
        owner_member = ServerMember(
            server_id=server.id,
            user_id=owner.id,
            status="ACTIVE",
        )
        target_member = ServerMember(
            server_id=server.id,
            user_id=target.id,
            status="LEFT" if target_left else "ACTIVE",
            left_at=None if not target_left else datetime.now(timezone.utc),
        )
        db.add_all([owner_member, target_member])
        db.flush()
        ban_id = None
        if add_active_ban:
            ban = ServerBan(
                server_id=server.id,
                user_id=target.id,
                banned_by=owner.id,
                target_highest_role_position=0,
            )
            db.add(ban)
            db.flush()
            ban_id = ban.id
        db.commit()
        return owner.id, target.id, target_member.id, server.id, ban_id


def _cleanup(context):
    owner_id, target_id, _member_id, server_id, _ban_id = context
    with Session(test_engine) as db:
        db.execute(
            ServerAuditLog.__table__.delete().where(
                ServerAuditLog.server_id == server_id
            )
        )
        db.execute(
            ServerBan.__table__.delete().where(
                ServerBan.server_id == server_id
            )
        )
        db.execute(
            ServerMemberRole.__table__.delete().where(
                ServerMemberRole.server_id == server_id
            )
        )
        db.execute(
            ServerMember.__table__.delete().where(
                ServerMember.server_id == server_id
            )
        )
        db.execute(Server.__table__.delete().where(Server.id == server_id))
        db.execute(
            User.__table__.delete().where(User.id.in_([owner_id, target_id]))
        )
        db.commit()


def _concurrent(operation_a, operation_b):
    barrier = Barrier(2)

    def run(operation):
        with Session(test_engine) as db:
            barrier.wait(timeout=10)
            try:
                operation(db)
                return "ok"
            except Exception as exc:
                from fastapi import HTTPException

                if isinstance(exc, HTTPException):
                    return exc.status_code
                raise

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(run, operation_a),
            executor.submit(run, operation_b),
        ]
        return [future.result(timeout=30) for future in futures]


def test_concurrent_kicks_transition_and_audit_once():
    context = _persistent_context()
    owner_id, target_id, member_id, server_id, _ban_id = context
    try:
        outcomes = _concurrent(
            lambda db: kick_server_member(db, server_id, target_id, owner_id),
            lambda db: kick_server_member(db, server_id, target_id, owner_id),
        )
        assert outcomes.count("ok") == 1
        assert outcomes.count(409) == 1
        with Session(test_engine) as db:
            member = db.get(ServerMember, member_id)
            events = db.scalars(
                select(ServerAuditLog).where(
                    ServerAuditLog.server_id == server_id,
                    ServerAuditLog.event_type == "MEMBER_KICKED",
                )
            ).all()
        assert member.status == "LEFT"
        assert len(events) == 1
    finally:
        _cleanup(context)


def test_concurrent_bans_create_one_active_cycle_and_audit():
    context = _persistent_context()
    owner_id, target_id, member_id, server_id, _ban_id = context
    try:
        outcomes = _concurrent(
            lambda db: ban_server_member(db, server_id, target_id, owner_id),
            lambda db: ban_server_member(db, server_id, target_id, owner_id),
        )
        assert outcomes.count("ok") == 1
        assert outcomes.count(409) == 1
        with Session(test_engine) as db:
            member = db.get(ServerMember, member_id)
            bans = db.scalars(
                select(ServerBan).where(
                    ServerBan.server_id == server_id,
                    ServerBan.user_id == target_id,
                    ServerBan.is_active.is_(True),
                )
            ).all()
            events = db.scalars(
                select(ServerAuditLog).where(
                    ServerAuditLog.server_id == server_id,
                    ServerAuditLog.event_type == "MEMBER_BANNED",
                )
            ).all()
        assert member.status == "LEFT"
        assert len(bans) == 1
        assert len(events) == 1
        assert events[0].ban_id == bans[0].id
    finally:
        _cleanup(context)


def test_concurrent_unbans_revoke_cycle_and_audit_once():
    context = _persistent_context(target_left=True, add_active_ban=True)
    owner_id, _target_id, _member_id, server_id, ban_id = context
    try:
        outcomes = _concurrent(
            lambda db: unban_server_member(db, server_id, ban_id, owner_id),
            lambda db: unban_server_member(db, server_id, ban_id, owner_id),
        )
        assert outcomes.count("ok") == 1
        assert outcomes.count(409) == 1
        with Session(test_engine) as db:
            ban = db.get(ServerBan, ban_id)
            events = db.scalars(
                select(ServerAuditLog).where(
                    ServerAuditLog.server_id == server_id,
                    ServerAuditLog.event_type == "MEMBER_UNBANNED",
                )
            ).all()
        assert ban.is_active is False
        assert ban.revoked_by == owner_id
        assert ban.revoked_at is not None
        assert len(events) == 1
    finally:
        _cleanup(context)
