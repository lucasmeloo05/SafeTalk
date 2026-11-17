from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Server,
    ServerConfigHistory,
    ServerMember,
    ServerMemberRole,
    ServerRole,
    User,
)
from app.schemas import ServerRoleUpdate
from app.services.server_member_service import leave_server
from app.services.server_role_service import (
    assign_server_role_to_member,
    delete_server_role,
    remove_server_role_from_member,
    update_server_role,
)
from conftest import test_engine


def _persistent_context(*, target_has_assignment=False):
    suffix = uuid4().hex[:10]
    with Session(test_engine) as db:
        owner = User(
            username=f"assign_owner_{suffix}",
            email=f"assign_owner_{suffix}@example.com",
            password_hash="synthetic-test-hash",
            is_active=True,
        )
        target = User(
            username=f"assign_target_{suffix}",
            email=f"assign_target_{suffix}@example.com",
            password_hash="synthetic-test-hash",
            is_active=True,
        )
        db.add_all([owner, target])
        db.flush()
        server = Server(owner_id=owner.id, name=f"Concorrência {suffix}")
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
            status="ACTIVE",
        )
        role = ServerRole(
            server_id=server.id,
            name=f"Cargo {suffix}",
            position=1,
            permissions={},
            is_default=False,
            is_system_role=False,
        )
        db.add_all([owner_member, target_member, role])
        db.flush()
        if target_has_assignment:
            db.add(
                ServerMemberRole(
                    server_id=server.id,
                    member_id=target_member.id,
                    role_id=role.id,
                    assigned_by=owner.id,
                )
            )
        db.commit()
        return owner.id, target.id, target_member.id, server.id, role.id


def _cleanup(context):
    owner_id, target_id, _member_id, server_id, _role_id = context
    with Session(test_engine) as db:
        db.execute(
            ServerConfigHistory.__table__.delete().where(
                ServerConfigHistory.server_id == server_id
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
        db.execute(
            ServerRole.__table__.delete().where(
                ServerRole.server_id == server_id
            )
        )
        db.execute(Server.__table__.delete().where(Server.id == server_id))
        db.execute(
            User.__table__.delete().where(
                User.id.in_([owner_id, target_id])
            )
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
            except HTTPException as exc:
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(run, operation)
            for operation in (operation_a, operation_b)
        ]
        return [future.result(timeout=30) for future in futures]


def test_concurrent_puts_create_one_assignment_and_one_audit():
    context = _persistent_context()
    owner_id, target_id, member_id, server_id, role_id = context
    try:
        outcomes = _concurrent(
            lambda db: assign_server_role_to_member(
                db, server_id, target_id, role_id, owner_id
            ),
            lambda db: assign_server_role_to_member(
                db, server_id, target_id, role_id, owner_id
            ),
        )
        assert outcomes == ["ok", "ok"]
        with Session(test_engine) as db:
            assignments = db.scalars(
                select(ServerMemberRole).where(
                    ServerMemberRole.server_id == server_id,
                    ServerMemberRole.member_id == member_id,
                    ServerMemberRole.role_id == role_id,
                )
            ).all()
            audits = db.scalars(
                select(ServerConfigHistory).where(
                    ServerConfigHistory.server_id == server_id,
                    ServerConfigHistory.setting_name
                    == f"server_member_role:{member_id}:{role_id}",
                )
            ).all()
        assert len(assignments) == 1
        assert len(audits) == 1
    finally:
        _cleanup(context)


def test_concurrent_deletes_are_idempotent_and_audit_once():
    context = _persistent_context(target_has_assignment=True)
    owner_id, target_id, member_id, server_id, role_id = context
    try:
        outcomes = _concurrent(
            lambda db: remove_server_role_from_member(
                db, server_id, target_id, role_id, owner_id
            ),
            lambda db: remove_server_role_from_member(
                db, server_id, target_id, role_id, owner_id
            ),
        )
        assert outcomes == ["ok", "ok"]
        with Session(test_engine) as db:
            assert db.scalar(
                select(ServerMemberRole.id).where(
                    ServerMemberRole.server_id == server_id,
                    ServerMemberRole.member_id == member_id,
                    ServerMemberRole.role_id == role_id,
                )
            ) is None
            audits = db.scalars(
                select(ServerConfigHistory).where(
                    ServerConfigHistory.server_id == server_id,
                    ServerConfigHistory.setting_name
                    == f"server_member_role:{member_id}:{role_id}",
                )
            ).all()
        assert len(audits) == 1
    finally:
        _cleanup(context)


def test_concurrent_put_and_delete_leave_one_consistent_state():
    context = _persistent_context()
    owner_id, target_id, member_id, server_id, role_id = context
    try:
        outcomes = _concurrent(
            lambda db: assign_server_role_to_member(
                db, server_id, target_id, role_id, owner_id
            ),
            lambda db: remove_server_role_from_member(
                db, server_id, target_id, role_id, owner_id
            ),
        )
        assert outcomes == ["ok", "ok"]
        with Session(test_engine) as db:
            assignment_exists = db.scalar(
                select(ServerMemberRole.id).where(
                    ServerMemberRole.server_id == server_id,
                    ServerMemberRole.member_id == member_id,
                    ServerMemberRole.role_id == role_id,
                )
            ) is not None
            audits = db.scalars(
                select(ServerConfigHistory).where(
                    ServerConfigHistory.server_id == server_id,
                    ServerConfigHistory.setting_name
                    == f"server_member_role:{member_id}:{role_id}",
                )
            ).all()
        assert (
            assignment_exists and len(audits) == 1
        ) or (
            not assignment_exists and len(audits) == 2
        )
    finally:
        _cleanup(context)


def test_concurrent_assignment_and_leave_never_leave_left_member_assigned():
    context = _persistent_context()
    owner_id, target_id, member_id, server_id, role_id = context
    try:
        outcomes = _concurrent(
            lambda db: assign_server_role_to_member(
                db, server_id, target_id, role_id, owner_id
            ),
            lambda db: leave_server(
                db,
                SimpleNamespace(id=target_id),
                server_id,
            ),
        )
        assert all(result in {"ok", 404} for result in outcomes)
        with Session(test_engine) as db:
            member = db.get(ServerMember, member_id)
            assert member.status == "LEFT"
            assert db.scalar(
                select(ServerMemberRole.id).where(
                    ServerMemberRole.server_id == server_id,
                    ServerMemberRole.member_id == member_id,
                    ServerMemberRole.role_id == role_id,
                )
            ) is None
    finally:
        _cleanup(context)


@pytest.mark.parametrize("role_action", ["update", "delete"])
def test_assignment_serializes_with_role_update_or_deletion(role_action):
    context = _persistent_context()
    owner_id, target_id, member_id, server_id, role_id = context
    try:
        def mutate_role(db):
            if role_action == "update":
                update_server_role(
                    db,
                    server_id,
                    role_id,
                    owner_id,
                    ServerRoleUpdate(name="Cargo alterado"),
                )
            else:
                delete_server_role(db, server_id, role_id, owner_id)

        outcomes = _concurrent(
            lambda db: assign_server_role_to_member(
                db, server_id, target_id, role_id, owner_id
            ),
            mutate_role,
        )
        if role_action == "update":
            assert outcomes == ["ok", "ok"]
            with Session(test_engine) as db:
                assert db.scalar(
                    select(ServerRole.id).where(
                        ServerRole.id == role_id,
                        ServerRole.name == "Cargo alterado",
                    )
                ) is not None
                assert db.scalar(
                    select(ServerMemberRole.id).where(
                        ServerMemberRole.server_id == server_id,
                        ServerMemberRole.member_id == member_id,
                        ServerMemberRole.role_id == role_id,
                    )
                ) is not None
        else:
            assert outcomes in (["ok", 409], [404, "ok"])
            with Session(test_engine) as db:
                role_exists = db.get(ServerRole, role_id) is not None
                assignment_exists = db.scalar(
                    select(ServerMemberRole.id).where(
                        ServerMemberRole.server_id == server_id,
                        ServerMemberRole.member_id == member_id,
                        ServerMemberRole.role_id == role_id,
                    )
                ) is not None
                assert role_exists == assignment_exists
    finally:
        _cleanup(context)
