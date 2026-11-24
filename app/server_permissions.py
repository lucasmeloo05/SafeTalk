import json
from typing import Literal, get_args

from fastapi import HTTPException


ServerPermissionKey = Literal[
    "kick_members",
    "ban_members",
    "unban_members",
    "manage_invites",
    "manage_roles",
    "mention_everyone",
]

SERVER_PERMISSION_KEYS = frozenset(get_args(ServerPermissionKey))


def check_expected_permissions(header: str | None, stored: dict) -> None:
    """Compare the client's base with the locked row's effective catalog flags."""
    if header is None:
        raise HTTPException(428, detail="Informe X-Expected-Permissions.")
    try:
        expected = json.loads(header)
    except (ValueError, RecursionError):
        expected = None
    if not isinstance(expected, dict) or any(
        key not in SERVER_PERMISSION_KEYS or type(value) is not bool
        for key, value in expected.items()
    ):
        raise HTTPException(422, detail="X-Expected-Permissions inválido.")
    if any((expected.get(key) is True) != (stored.get(key) is True)
           for key in SERVER_PERMISSION_KEYS):
        raise HTTPException(409, detail={"code": "permissions_conflict"})
