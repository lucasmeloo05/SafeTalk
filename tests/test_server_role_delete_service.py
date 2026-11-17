import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import (
    Server,
    ServerConfigHistory,
    ServerMember,
    ServerMemberRole,
    ServerRole,
    User,
)
from app.services.server_role_service import delete_server_role
from conftest import test_engine


def _create_server(db_session, create_user, *, name="Servidor de exclusão"):
    owner = create_user()
    server = Server(owner_id=owner["id"], name=name)
    db_session.add(server)
    db_session.flush()
    owner_member = ServerMember(
        server_id=server.id,
        user_id=owner["id"],
        status="ACTIVE",
    )
    db_session.add(owner_member)
    db_session.flush()
    return owner, server, owner_member


def _add_member(db_session, server, user, *, member_status="ACTIVE"):
    member = ServerMember(
        server_id=server.id,
        user_id=user["id"],
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
    server,
    *,
    name="Cargo comum",
    position=1,
    permissions=None,
    is_default=False,
    is_system_role=False,
):
    role = ServerRole(
        server_id=server.id,
        name=name,
        description="Descrição do cargo",
        position=position,
        permissions=permissions or {},
        is_default=is_default,
        is_system_role=is_system_role,
    )
    db_session.add(role)
    db_session.flush()
    return role


def _assign(db_session, server, member, role, assigned_by):
    assignment = ServerMemberRole(
        server_id=server.id,
        member_id=member.id,
        role_id=role.id,
        assigned_by=assigned_by,
    )
    db_session.add(assignment)
    db_session.flush()
    return assignment


def _assert_http_error(call, expected_status):
    with pytest.raises(HTTPException) as error:
        call()
    assert error.value.status_code == expected_status


def test_owner_deletes_unassigned_common_role_and_records_full_audit(
    db_session, create_user
):
    owner, server, _ = _create_server(db_session, create_user)
    role = _add_role(
        db_session,
        server,
        name="Excluir",
        permissions={"kick_members": False},
    )
    role_id = role.id
    snapshot = {
        "id": role.id,
        "name": role.name,
        "description": role.description,
        "position": role.position,
        "permissions": role.permissions,
        "is_default": role.is_default,
        "is_system_role": role.is_system_role,
        "created_at": role.created_at.isoformat(),
    }

    result = delete_server_role(db_session, server.id, role.id, owner["id"])

    assert result is None
    assert db_session.get(ServerRole, role_id) is None
    audit = db_session.scalar(
        select(ServerConfigHistory).where(
            ServerConfigHistory.server_id == server.id,
            ServerConfigHistory.setting_name == f"server_role:{role_id}",
        )
    )
    assert audit is not None
    assert audit.changed_by == owner["id"]
    assert json.loads(audit.old_value) == snapshot
    assert json.loads(audit.new_value) == {"deleted": True}
    assert audit.changed_at is not None


def test_active_manager_with_higher_role_deletes_lower_role(
    db_session, create_user
):
    owner, server, _ = _create_server(db_session, create_user)
    actor = create_user()
    actor_member = _add_member(db_session, server, actor)
    actor_role = _add_role(
        db_session,
        server,
        name="Gestor",
        position=10,
        permissions={"manage_roles": True},
    )
    _assign(db_session, server, actor_member, actor_role, owner["id"])
    target_role = _add_role(db_session, server, name="Inferior", position=5)

    delete_server_role(db_session, server.id, target_role.id, actor["id"])

    assert db_session.get(ServerRole, target_role.id) is None


def test_member_without_manage_roles_cannot_delete_role(db_session, create_user):
    _, server, _ = _create_server(db_session, create_user)
    actor = create_user()
    _add_member(db_session, server, actor)
    role = _add_role(db_session, server)
    db_session.commit()

    _assert_http_error(
        lambda: delete_server_role(db_session, server.id, role.id, actor["id"]),
        403,
    )
    assert db_session.get(ServerRole, role.id) is not None


@pytest.mark.parametrize("actor_position", [5, 4])
def test_member_cannot_delete_role_at_or_above_own_hierarchy(
    db_session, create_user, actor_position
):
    owner, server, _ = _create_server(db_session, create_user)
    actor = create_user()
    actor_member = _add_member(db_session, server, actor)
    actor_role = _add_role(
        db_session,
        server,
        name="Cargo do ator",
        position=actor_position,
        permissions={"manage_roles": True},
    )
    _assign(db_session, server, actor_member, actor_role, owner["id"])
    target_role = _add_role(db_session, server, name="Alvo", position=5)
    db_session.commit()

    _assert_http_error(
        lambda: delete_server_role(
            db_session, server.id, target_role.id, actor["id"]
        ),
        403,
    )
    assert db_session.get(ServerRole, target_role.id) is not None


def test_left_actor_cannot_delete_role(db_session, create_user):
    _, server, _ = _create_server(db_session, create_user)
    actor = create_user()
    _add_member(db_session, server, actor, member_status="LEFT")
    role = _add_role(db_session, server)
    db_session.commit()

    _assert_http_error(
        lambda: delete_server_role(db_session, server.id, role.id, actor["id"]),
        404,
    )
    assert db_session.get(ServerRole, role.id) is not None


def test_user_without_server_membership_cannot_delete_role(
    db_session, create_user
):
    _, server, _ = _create_server(db_session, create_user)
    actor = create_user()
    role = _add_role(db_session, server)
    db_session.commit()

    _assert_http_error(
        lambda: delete_server_role(db_session, server.id, role.id, actor["id"]),
        404,
    )
    assert db_session.get(ServerRole, role.id) is not None


def test_nonexistent_server_and_role_return_not_found(db_session, create_user):
    owner, server, _ = _create_server(db_session, create_user)
    role = _add_role(db_session, server)
    db_session.commit()

    _assert_http_error(
        lambda: delete_server_role(db_session, server.id + 999, role.id, owner["id"]),
        404,
    )
    _assert_http_error(
        lambda: delete_server_role(db_session, server.id, role.id + 999, owner["id"]),
        404,
    )


def test_role_from_another_server_cannot_be_deleted_by_id_manipulation(
    db_session, create_user
):
    owner, first_server, _ = _create_server(db_session, create_user)
    _, second_server, _ = _create_server(
        db_session, create_user, name="Outro servidor"
    )
    foreign_role = _add_role(db_session, second_server, name="Alheio")
    db_session.commit()

    _assert_http_error(
        lambda: delete_server_role(
            db_session, first_server.id, foreign_role.id, owner["id"]
        ),
        404,
    )
    assert db_session.get(ServerRole, foreign_role.id) is not None


def test_system_role_cannot_be_deleted_even_by_owner(db_session, create_user):
    owner, server, _ = _create_server(db_session, create_user)
    role = _add_role(db_session, server, is_system_role=True)
    db_session.commit()

    _assert_http_error(
        lambda: delete_server_role(db_session, server.id, role.id, owner["id"]),
        403,
    )
    assert db_session.get(ServerRole, role.id) is not None


@pytest.mark.parametrize("member_status", ["ACTIVE", "LEFT"])
def test_role_with_any_member_assignment_returns_conflict(
    db_session, create_user, member_status
):
    owner, server, _ = _create_server(db_session, create_user)
    assigned_user = create_user()
    member = _add_member(db_session, server, assigned_user, member_status=member_status)
    role = _add_role(db_session, server)
    assignment = _assign(db_session, server, member, role, owner["id"])
    db_session.commit()

    _assert_http_error(
        lambda: delete_server_role(db_session, server.id, role.id, owner["id"]),
        409,
    )
    assert db_session.get(ServerRole, role.id) is not None
    assert db_session.get(ServerMemberRole, assignment.id) is not None
    assert db_session.scalar(
        select(ServerConfigHistory.id).where(
            ServerConfigHistory.server_id == server.id,
            ServerConfigHistory.setting_name == f"server_role:{role.id}",
        )
    ) is None


def test_default_flag_alone_does_not_prevent_role_deletion(
    db_session, create_user
):
    owner, server, _ = _create_server(db_session, create_user)
    role = _add_role(db_session, server, is_default=True)

    delete_server_role(db_session, server.id, role.id, owner["id"])

    assert db_session.get(ServerRole, role.id) is None


def test_audit_failure_rolls_back_role_deletion(db_session, create_user, monkeypatch):
    owner, server, _ = _create_server(db_session, create_user)
    role = _add_role(db_session, server)
    role_id = role.id
    db_session.commit()

    def fail_audit_flush(*args, **kwargs):
        raise SQLAlchemyError("falha simulada ao persistir auditoria")

    monkeypatch.setattr(db_session, "flush", fail_audit_flush)
    _assert_http_error(
        lambda: delete_server_role(db_session, server.id, role_id, owner["id"]),
        500,
    )
    monkeypatch.undo()
    db_session.expire_all()

    assert db_session.get(ServerRole, role_id) is not None
    assert db_session.scalar(
        select(ServerConfigHistory.id).where(
            ServerConfigHistory.server_id == server.id,
            ServerConfigHistory.setting_name == f"server_role:{role_id}",
        )
    ) is None


def test_delete_failure_rolls_back_flushed_audit(db_session, create_user, monkeypatch):
    owner, server, _ = _create_server(db_session, create_user)
    role = _add_role(db_session, server)
    role_id = role.id
    db_session.commit()
    original_flush = db_session.flush

    def fail_role_delete_flush(*args, **kwargs):
        if any(isinstance(item, ServerRole) for item in db_session.deleted):
            raise SQLAlchemyError("falha simulada ao excluir cargo")
        return original_flush(*args, **kwargs)

    monkeypatch.setattr(db_session, "flush", fail_role_delete_flush)
    _assert_http_error(
        lambda: delete_server_role(db_session, server.id, role_id, owner["id"]),
        500,
    )
    monkeypatch.undo()
    db_session.expire_all()

    assert db_session.get(ServerRole, role_id) is not None
    assert db_session.scalar(
        select(ServerConfigHistory.id).where(
            ServerConfigHistory.server_id == server.id,
            ServerConfigHistory.setting_name == f"server_role:{role_id}",
        )
    ) is None


def test_delete_locks_server_membership_and_role_in_order(db_session, create_user):
    owner, server, _ = _create_server(db_session, create_user)
    role = _add_role(db_session, server)
    statements = []
    connection = db_session.connection()

    def capture_sql(conn, cursor, statement, parameters, context, executemany):
        if "for update" in statement.lower():
            statements.append(statement.lower())

    event.listen(connection, "before_cursor_execute", capture_sql)
    try:
        delete_server_role(db_session, server.id, role.id, owner["id"])
    finally:
        event.remove(connection, "before_cursor_execute", capture_sql)

    assert len(statements) == 3
    assert "from servers" in statements[0]
    assert "from server_members" in statements[1]
    assert "from server_roles" in statements[2]


def test_two_concurrent_deletions_do_not_leave_partial_state():
    suffix = uuid4().hex[:8]
    with Session(test_engine) as setup_db:
        owner = User(
            username=f"delete_owner_{suffix}",
            email=f"delete_owner_{suffix}@example.com",
            password_hash="synthetic-test-hash",
            is_active=True,
        )
        setup_db.add(owner)
        setup_db.flush()
        server = Server(owner_id=owner.id, name=f"Exclusão concorrente {suffix}")
        setup_db.add(server)
        setup_db.flush()
        setup_db.add(
            ServerMember(
                server_id=server.id,
                user_id=owner.id,
                status="ACTIVE",
            )
        )
        role = ServerRole(
            server_id=server.id,
            name="Cargo concorrente",
            position=1,
            permissions={},
            is_default=False,
            is_system_role=False,
        )
        setup_db.add(role)
        setup_db.commit()
        owner_id, server_id, role_id = owner.id, server.id, role.id

    barrier = Barrier(2)

    def delete_once():
        with Session(test_engine) as db:
            barrier.wait(timeout=10)
            try:
                delete_server_role(db, server_id, role_id, owner_id)
                return "deleted"
            except HTTPException as exc:
                return exc.status_code

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(lambda _: delete_once(), range(2)))

        assert sorted(map(str, outcomes)) == ["404", "deleted"]
        with Session(test_engine) as verify_db:
            assert verify_db.get(ServerRole, role_id) is None
            audit_rows = verify_db.scalars(
                select(ServerConfigHistory).where(
                    ServerConfigHistory.server_id == server_id,
                    ServerConfigHistory.setting_name == f"server_role:{role_id}",
                )
            ).all()
            assert len(audit_rows) == 1
    finally:
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
