from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, event, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import Server, ServerConfigHistory, ServerMember, ServerRole, User
from app.schemas import ServerRoleCreate, ServerRoleResponse, ServerRoleUpdate
from app.services.server_role_service import create_server_role, update_server_role
from conftest import test_engine


@pytest.fixture
def owned_server():
    suffix = uuid4().hex[:12]
    with Session(test_engine) as setup:
        owner = User(username=f"owner_{suffix}", email=f"{suffix}@example.test",
                     password_hash="synthetic-test-hash", is_active=True)
        setup.add(owner)
        setup.flush()
        server = Server(owner_id=owner.id, name="Teste de resposta")
        setup.add(server)
        setup.flush()
        owner_id, server_id = owner.id, server.id
        setup.add(ServerMember(server_id=server_id, user_id=owner_id, status="ACTIVE"))
        setup.commit()
    try:
        yield server_id, owner_id
    finally:
        with Session(test_engine) as cleanup:
            for model in (ServerConfigHistory, ServerRole, ServerMember):
                cleanup.execute(delete(model).where(model.server_id == server_id))
            cleanup.execute(delete(Server).where(Server.id == server_id))
            cleanup.execute(delete(User).where(User.id == owner_id))
            cleanup.commit()


def prepare_write(db, operation, server_id, owner_id):
    payload = ServerRoleCreate(name="Original", position=2, permissions={"kick_members": True})
    if operation == "create":
        return lambda: create_server_role(db, server_id, owner_id, payload)
    original = create_server_role(db, server_id, owner_id, payload)
    role_id = original.id
    return lambda: update_server_role(db, server_id, role_id, owner_id,
                                      ServerRoleUpdate(description="Atualizado"))


@pytest.mark.parametrize("operation", ["create", "update"])
def test_write_response_keeps_committed_state_without_post_commit_sql(owned_server, operation):
    server_id, owner_id = owned_server
    with test_engine.connect() as connection, Session(connection, expire_on_commit=True) as writer:
        write = prepare_write(writer, operation, server_id, owner_id)
        committed = False
        post_commit_sql = []

        @event.listens_for(writer, "after_commit")
        def mark_commit(session):
            nonlocal committed
            committed = True

        @event.listens_for(connection, "before_cursor_execute")
        def track_sql(conn, cursor, statement, parameters, context, executemany):
            if committed:
                post_commit_sql.append(statement)

        response = write()
        assert committed
        # Intercalar uma segunda gravação exatamente entre commit e serialização.
        with Session(test_engine) as other:
            role = other.scalars(select(ServerRole).where(ServerRole.server_id == server_id)).one()
            expected = ServerRoleResponse.model_validate(role).model_dump(mode="json")
            assert expected["description"] == ("Atualizado" if operation == "update" else None)
            later = update_server_role(other, server_id, role.id, owner_id,
                                       ServerRoleUpdate(name="Alteração posterior"))
            assert later.name == "Alteração posterior"

        serialized = ServerRoleResponse.model_validate(response).model_dump(mode="json")
        assert post_commit_sql == []
        assert serialized == expected


@pytest.mark.parametrize("operation", ["create", "update"])
def test_commit_failure_rolls_back_role_and_history(owned_server, operation):
    server_id, owner_id = owned_server
    with Session(test_engine) as writer:
        write = prepare_write(writer, operation, server_id, owner_id)

        @event.listens_for(writer, "before_commit")
        def fail_commit(session):
            raise SQLAlchemyError("Falha de commit simulada")

        with pytest.raises(HTTPException) as failure:
            write()
        assert failure.value.status_code == 500
        assert not writer.in_transaction()

    with Session(test_engine) as reader:
        roles = reader.scalars(select(ServerRole).where(ServerRole.server_id == server_id)).all()
        history = reader.scalars(select(ServerConfigHistory).where(ServerConfigHistory.server_id == server_id)).all()
        if operation == "create":
            assert not roles
            assert not history
        else:
            assert len(roles) == len(history) == 1
            assert roles[0].description is None
