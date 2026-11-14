import pytest
from pydantic import ValidationError

from app.schemas import ServerRoleCreate


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
