import pytest
from sqlalchemy.exc import IntegrityError

from app.models import Server, ServerRole


def _create_server(db_session, owner_id: int) -> Server:
    server = Server(owner_id=owner_id, name="Servidor de posições")
    db_session.add(server)
    db_session.flush()
    return server


@pytest.mark.parametrize("position", [1, 2, 25])
def test_positive_role_positions_are_accepted(
    db_session,
    create_user,
    position: int,
):
    owner = create_user()
    server = _create_server(db_session, owner["id"])
    role = ServerRole(
        server_id=server.id,
        name=f"Cargo posição {position}",
        position=position,
    )

    db_session.add(role)
    db_session.flush()

    assert role.position == position
    assert role.id is not None


@pytest.mark.parametrize("position", [0, -1])
def test_database_rejects_zero_and_negative_role_positions(
    db_session,
    create_user,
    position: int,
):
    owner = create_user()
    server = _create_server(db_session, owner["id"])
    role = ServerRole(
        server_id=server.id,
        name=f"Cargo posição inválida {position}",
        position=position,
    )

    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(role)
            db_session.flush()


def test_roles_in_same_server_may_share_position(db_session, create_user):
    owner = create_user()
    server = _create_server(db_session, owner["id"])
    roles = [
        ServerRole(server_id=server.id, name=name, position=3)
        for name in ("Cargo A", "Cargo B")
    ]

    db_session.add_all(roles)
    db_session.flush()

    assert roles[0].id != roles[1].id
    assert [role.position for role in roles] == [3, 3]


def test_missing_position_has_no_orm_default_and_is_rejected(
    db_session,
    create_user,
):
    owner = create_user()
    server = _create_server(db_session, owner["id"])
    position_column = ServerRole.__table__.c.position
    role = ServerRole(server_id=server.id, name="Cargo sem posição")

    assert position_column.default is None
    assert role.position is None

    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(role)
            db_session.flush()
