from typing import Literal, get_args


ServerPermissionKey = Literal[
    "kick_members",
    "ban_members",
    "unban_members",
    "manage_invites",
    "manage_roles",
    "mention_everyone",
]

SERVER_PERMISSION_KEYS = frozenset(get_args(ServerPermissionKey))
