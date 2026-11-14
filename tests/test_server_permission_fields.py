import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.models import Server, ServerRole


def test_permission_foundation_fields_have_database_defaults(
    db_session,
    create_user,
):
    owner = create_user()

    server_id = db_session.execute(
        text(
            """
            INSERT INTO servers (
                owner_id, name, is_adult, ai_moderation_enabled, is_discoverable
            )
            VALUES (:owner_id, :name, false, false, false)
            RETURNING id
            """
        ),
        {"owner_id": owner["id"], "name": "Permissões da comunidade"},
    ).scalar_one()
    role_id = db_session.execute(
        text(
            """
            INSERT INTO server_roles (
                server_id, name, permissions, position, is_default
            )
            VALUES (:server_id, :name, '{}'::jsonb, 1, false)
            RETURNING id
            """
        ),
        {"server_id": server_id, "name": "Cargo comum"},
    ).scalar_one()
    db_session.flush()

    server = db_session.get(Server, server_id)
    role = db_session.get(ServerRole, role_id)

    assert server is not None
    assert server.everyone_permissions == {}
    assert role is not None
    assert role.is_system_role is False
    assert role.is_default is False


def test_permission_foundation_fields_persist_and_are_independent(
    db_session,
    create_user,
):
    owner = create_user()
    server = Server(owner_id=owner["id"], name="Persistência de permissões")
    db_session.add(server)
    db_session.flush()

    system_role = ServerRole(
        server_id=server.id,
        name="Reservado",
        position=1,
        is_system_role=True,
        is_default=False,
    )
    default_role = ServerRole(
        server_id=server.id,
        name="Marcado como default",
        position=2,
        is_system_role=False,
        is_default=True,
    )
    second_server = Server(
        owner_id=owner["id"],
        name="Cargo com ambas as marcações",
    )
    server.everyone_permissions = {
        "send_messages": True,
        "mention_everyone": False,
    }
    db_session.add_all([system_role, default_role, second_server])
    db_session.flush()
    both_flags_role = ServerRole(
        server_id=second_server.id,
        name="Reservado e default",
        position=1,
        is_system_role=True,
        is_default=True,
    )
    db_session.add(both_flags_role)
    db_session.flush()
    system_role_id = system_role.id
    default_role_id = default_role.id
    both_flags_role_id = both_flags_role.id
    server_id = server.id

    db_session.expire_all()
    persisted_server = db_session.get(Server, server_id)
    persisted_system_role = db_session.get(ServerRole, system_role_id)
    persisted_default_role = db_session.get(ServerRole, default_role_id)
    persisted_both_flags_role = db_session.get(ServerRole, both_flags_role_id)

    assert persisted_server is not None
    assert persisted_server.everyone_permissions == {
        "send_messages": True,
        "mention_everyone": False,
    }
    assert persisted_system_role is not None
    assert persisted_system_role.is_system_role is True
    assert persisted_system_role.is_default is False
    assert persisted_default_role is not None
    assert persisted_default_role.is_system_role is False
    assert persisted_default_role.is_default is True
    assert persisted_both_flags_role is not None
    assert persisted_both_flags_role.is_system_role is True
    assert persisted_both_flags_role.is_default is True


def test_orm_python_defaults_are_independent():
    permissions_default = Server.__table__.c.everyone_permissions.default
    system_role_default = ServerRole.__table__.c.is_system_role.default

    assert permissions_default is not None
    assert callable(permissions_default.arg)
    first_permissions = permissions_default.arg(None)
    second_permissions = permissions_default.arg(None)
    assert first_permissions == {}
    assert second_permissions == {}
    assert first_permissions is not second_permissions

    assert system_role_default is not None
    assert system_role_default.arg is False


def test_permission_foundation_fields_reject_null_values(
    db_session,
    create_user,
):
    owner = create_user()
    server = Server(owner_id=owner["id"], name="Integridade das permissões")
    db_session.add(server)
    db_session.flush()

    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    """
                    INSERT INTO servers (
                        owner_id, name, is_adult, ai_moderation_enabled,
                        is_discoverable, everyone_permissions
                    )
                    VALUES (
                        :owner_id, :name, false, false, false, NULL
                    )
                    """
                ),
                {"owner_id": owner["id"], "name": "Sem permissões"},
            )

    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    """
                    INSERT INTO server_roles (
                        server_id, name, permissions, position, is_default,
                        is_system_role
                    )
                    VALUES (
                        :server_id, :name, '{}'::jsonb, 1, false, NULL
                    )
                    """
                ),
                {"server_id": server.id, "name": "Sem classificação"},
            )


@pytest.mark.parametrize(
    "json_value",
    ["null", "[]", '"texto"', "42", "true"],
)
def test_everyone_permissions_rejects_non_object_json(
    db_session,
    create_user,
    json_value,
):
    owner = create_user()

    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    """
                    INSERT INTO servers (
                        owner_id, name, is_adult, ai_moderation_enabled,
                        is_discoverable, everyone_permissions
                    )
                    VALUES (
                        :owner_id, :name, false, false, false,
                        CAST(:json_value AS jsonb)
                    )
                    """
                ),
                {
                    "owner_id": owner["id"],
                    "name": "JSON não objeto",
                    "json_value": json_value,
                },
            )
