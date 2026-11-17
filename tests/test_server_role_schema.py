import pytest
from pydantic import ValidationError

from app.schemas import ServerRoleCreate, ServerRoleUpdate


def test_server_role_create_accepts_valid_payload_and_trims_name():
    payload = ServerRoleCreate.model_validate(
        {
            "name": "  Moderador  ",
            "description": "Cargo de moderação",
            "position": 2,
            "permissions": {
                "kick_members": True,
                "ban_members": False,
            },
        }
    )

    assert payload.name == "Moderador"
    assert payload.description == "Cargo de moderação"
    assert payload.position == 2
    assert payload.permissions == {
        "kick_members": True,
        "ban_members": False,
    }


@pytest.mark.parametrize("name", ["", "   ", " \t\n "])
def test_server_role_create_rejects_empty_or_whitespace_name(name: str):
    with pytest.raises(ValidationError):
        ServerRoleCreate.model_validate({"name": name, "position": 1})


def test_server_role_create_rejects_name_longer_than_50_characters():
    with pytest.raises(ValidationError):
        ServerRoleCreate.model_validate({"name": "x" * 51, "position": 1})


def test_server_role_create_rejects_description_longer_than_255_characters():
    with pytest.raises(ValidationError):
        ServerRoleCreate.model_validate(
            {"name": "Cargo", "position": 1, "description": "x" * 256}
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "Cargo"},
        {"name": "Cargo", "position": 0},
        {"name": "Cargo", "position": -1},
        {"name": "Cargo", "position": True},
        {"name": "Cargo", "position": False},
    ],
)
def test_server_role_create_requires_strict_positive_position(payload: dict):
    with pytest.raises(ValidationError):
        ServerRoleCreate.model_validate(payload)


@pytest.mark.parametrize(
    "permissions",
    [
        {"unknown_permission": True},
        {"kick_members": 1},
        {"kick_members": "true"},
        {"kick_members": None},
    ],
)
def test_server_role_create_rejects_unknown_permissions_and_non_booleans(
    permissions: dict,
):
    with pytest.raises(ValidationError):
        ServerRoleCreate.model_validate(
            {"name": "Cargo", "position": 1, "permissions": permissions}
        )


@pytest.mark.parametrize(
    "field_name,field_value",
    [
        ("server_id", 10),
        ("owner_id", 10),
        ("assigned_by", 10),
        ("is_default", True),
        ("is_system_role", True),
        ("client_extra", "unexpected"),
    ],
)
def test_server_role_create_rejects_internal_and_extra_fields(
    field_name: str,
    field_value: object,
):
    with pytest.raises(ValidationError):
        ServerRoleCreate.model_validate(
            {"name": "Cargo", "position": 1, field_name: field_value}
        )


def test_server_role_create_defaults_permissions_to_empty_object():
    payload = ServerRoleCreate.model_validate(
        {"name": "Cargo", "position": 1}
    )

    assert payload.permissions == {}


def test_server_role_update_accepts_name_only_and_trims_it():
    payload = ServerRoleUpdate.model_validate({"name": "  Moderador  "})

    assert payload.name == "Moderador"
    assert payload.model_fields_set == {"name"}


@pytest.mark.parametrize("name", ["", "   ", " \t\n "])
def test_server_role_update_rejects_empty_or_whitespace_name(name: str):
    with pytest.raises(ValidationError):
        ServerRoleUpdate.model_validate({"name": name})


def test_server_role_update_rejects_null_name():
    with pytest.raises(ValidationError):
        ServerRoleUpdate.model_validate({"name": None})


def test_server_role_update_rejects_name_longer_than_50_characters():
    with pytest.raises(ValidationError):
        ServerRoleUpdate.model_validate({"name": "x" * 51})


def test_server_role_update_accepts_description_only_and_null():
    description = ServerRoleUpdate.model_validate(
        {"description": "Descrição atualizada"}
    )
    clear_description = ServerRoleUpdate.model_validate(
        {"description": None}
    )

    assert description.description == "Descrição atualizada"
    assert description.model_fields_set == {"description"}
    assert clear_description.description is None
    assert clear_description.model_fields_set == {"description"}


def test_server_role_update_rejects_description_longer_than_255_characters():
    with pytest.raises(ValidationError):
        ServerRoleUpdate.model_validate({"description": "x" * 256})


def test_server_role_update_accepts_position_only():
    payload = ServerRoleUpdate.model_validate({"position": 4})

    assert payload.position == 4
    assert payload.model_fields_set == {"position"}


@pytest.mark.parametrize("position", [True, False, 0, -1, None])
def test_server_role_update_rejects_invalid_position(position: object):
    with pytest.raises(ValidationError):
        ServerRoleUpdate.model_validate({"position": position})


def test_server_role_update_accepts_permissions_as_full_object():
    permissions = {"kick_members": True, "ban_members": False}
    payload = ServerRoleUpdate.model_validate({"permissions": permissions})

    assert payload.permissions == permissions
    assert payload.permissions["ban_members"] is False
    assert payload.model_fields_set == {"permissions"}


def test_server_role_update_accepts_empty_permissions_object():
    payload = ServerRoleUpdate.model_validate({"permissions": {}})

    assert payload.permissions == {}
    assert payload.model_fields_set == {"permissions"}


@pytest.mark.parametrize(
    "permissions",
    [
        {"unknown_permission": True},
        {"kick_members": 1},
        {"kick_members": "true"},
        {"kick_members": None},
        None,
    ],
)
def test_server_role_update_rejects_invalid_permissions(permissions: object):
    with pytest.raises(ValidationError):
        ServerRoleUpdate.model_validate({"permissions": permissions})


@pytest.mark.parametrize(
    "field_name,field_value",
    [
        ("server_id", 10),
        ("owner_id", 10),
        ("is_default", True),
        ("is_system_role", True),
        ("created_at", "2026-01-01T00:00:00Z"),
        ("assigned_by", 10),
        ("client_extra", "unexpected"),
    ],
)
def test_server_role_update_rejects_protected_and_extra_fields(
    field_name: str,
    field_value: object,
):
    with pytest.raises(ValidationError):
        ServerRoleUpdate.model_validate(
            {"name": "Moderador", field_name: field_value}
        )


def test_server_role_update_rejects_empty_payload():
    with pytest.raises(ValidationError):
        ServerRoleUpdate.model_validate({})


def test_server_role_update_preserves_omitted_fields_for_service():
    payload = ServerRoleUpdate.model_validate({"name": "Novo nome"})

    assert payload.model_fields_set == {"name"}
    assert payload.name == "Novo nome"
    assert payload.description is None
    assert payload.position is None
    assert payload.permissions is None


def test_server_role_update_accepts_valid_combination_of_fields():
    payload = ServerRoleUpdate.model_validate(
        {
            "name": "  Administrador  ",
            "description": None,
            "position": 12,
            "permissions": {"manage_roles": True, "kick_members": False},
        }
    )

    assert payload.name == "Administrador"
    assert payload.description is None
    assert payload.position == 12
    assert payload.permissions == {
        "manage_roles": True,
        "kick_members": False,
    }
    assert payload.model_fields_set == {
        "name",
        "description",
        "position",
        "permissions",
    }
