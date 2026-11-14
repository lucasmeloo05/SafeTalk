from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app.models import Server, ServerMember, ServerMemberRole, ServerRole
from app.services.server_authorization_service import (
    get_member_hierarchy_level,
    get_effective_server_permissions,
    has_server_permission,
    is_hierarchy_comparison_approved,
    resolve_server_permissions,
)


def _create_server_membership(
    db_session,
    member_user: dict,
    *,
    owner_user: dict | None = None,
    status: str = "ACTIVE",
) -> tuple[Server, ServerMember, dict]:
    owner = owner_user or member_user
    server = Server(owner_id=owner["id"], name="Servidor de autorização")
    membership = ServerMember(
        user_id=member_user["id"],
        status=status,
        left_at=datetime.now(timezone.utc) if status == "LEFT" else None,
    )
    db_session.add(server)
    db_session.flush()
    membership.server_id = server.id
    db_session.add(membership)
    db_session.flush()
    return server, membership, owner


def _assign_role(db_session, server, membership, assigned_by, permissions):
    role = ServerRole(
        server_id=server.id,
        name=f"Cargo {len(server.name)} {db_session.query(ServerRole).count()}",
        position=1,
        permissions=permissions,
    )
    db_session.add(role)
    db_session.flush()
    db_session.add(
        ServerMemberRole(
            member_id=membership.id,
            role_id=role.id,
            server_id=server.id,
            assigned_by=assigned_by["id"],
        )
    )
    db_session.flush()
    return role


def test_permissions_union_everyone_and_individual_roles(
    db_session, create_user
):
    member = create_user()
    server, membership, owner = _create_server_membership(db_session, member)
    server.everyone_permissions = {"manage_invites": True}
    _assign_role(
        db_session,
        server,
        membership,
        owner,
        {"kick_members": True},
    )

    resolved = resolve_server_permissions(db_session, server.id, member["id"])

    assert resolved.permissions == frozenset({"manage_invites", "kick_members"})
    assert get_effective_server_permissions(
        db_session, server.id, member["id"]
    ) == resolved.permissions


def test_permissions_union_multiple_individual_roles(db_session, create_user):
    member = create_user()
    server, membership, owner = _create_server_membership(db_session, member)
    _assign_role(
        db_session, server, membership, owner, {"kick_members": True}
    )
    _assign_role(
        db_session, server, membership, owner, {"ban_members": True}
    )

    permissions = get_effective_server_permissions(
        db_session, server.id, member["id"]
    )

    assert permissions == frozenset({"kick_members", "ban_members"})


def test_unban_members_grant_from_individual_role_is_effective(
    db_session, create_user
):
    member = create_user()
    server, membership, owner = _create_server_membership(db_session, member)
    _assign_role(
        db_session,
        server,
        membership,
        owner,
        {"unban_members": True},
    )

    permissions = get_effective_server_permissions(
        db_session, server.id, member["id"]
    )

    assert "unban_members" in permissions


def test_false_grant_does_not_revoke_true_grant_from_another_role(
    db_session, create_user
):
    member = create_user()
    server, membership, owner = _create_server_membership(db_session, member)
    _assign_role(
        db_session, server, membership, owner, {"manage_roles": True}
    )
    _assign_role(
        db_session, server, membership, owner, {"manage_roles": False}
    )

    resolved = resolve_server_permissions(db_session, server.id, member["id"])

    assert has_server_permission(resolved, "manage_roles") is True


def test_member_without_individual_roles_receives_everyone_grants(
    db_session, create_user
):
    member = create_user()
    server, _, _ = _create_server_membership(db_session, member)
    server.everyone_permissions = {"mention_everyone": True}

    permissions = get_effective_server_permissions(
        db_session, server.id, member["id"]
    )

    assert permissions == frozenset({"mention_everyone"})


def test_member_without_grants_has_empty_effective_permissions(
    db_session, create_user
):
    member = create_user()
    server, _, _ = _create_server_membership(db_session, member)

    resolved = resolve_server_permissions(db_session, server.id, member["id"])

    assert resolved.permissions == frozenset()
    assert has_server_permission(resolved, "ban_members") is False


def test_owner_authority_is_identified_separately_from_role_grants(
    db_session, create_user
):
    owner = create_user()
    server, _, _ = _create_server_membership(db_session, owner)

    resolved = resolve_server_permissions(db_session, server.id, owner["id"])

    assert resolved.is_owner is True
    assert resolved.permissions == frozenset()
    assert has_server_permission(resolved, "manage_roles") is False


def test_left_member_cannot_resolve_server_permissions(db_session, create_user):
    member = create_user()
    owner = create_user()
    server, _, _ = _create_server_membership(
        db_session, member, owner_user=owner, status="LEFT"
    )
    server.everyone_permissions = {"ban_members": True}

    with pytest.raises(HTTPException) as error:
        resolve_server_permissions(db_session, server.id, member["id"])

    assert error.value.status_code == 404


def test_user_without_server_membership_cannot_resolve_permissions(
    db_session, create_user
):
    owner = create_user()
    outsider = create_user()
    server, _, _ = _create_server_membership(db_session, owner)

    with pytest.raises(HTTPException) as error:
        resolve_server_permissions(db_session, server.id, outsider["id"])

    assert error.value.status_code == 404


def test_roles_from_another_server_do_not_affect_resolution(
    db_session, create_user
):
    local_member = create_user()
    local_server, _, local_owner = _create_server_membership(
        db_session, local_member
    )
    foreign_member = create_user()
    foreign_server, foreign_membership, foreign_owner = _create_server_membership(
        db_session, foreign_member
    )
    _assign_role(
        db_session,
        foreign_server,
        foreign_membership,
        foreign_owner,
        {"ban_members": True},
    )

    permissions = get_effective_server_permissions(
        db_session, local_server.id, local_member["id"]
    )

    assert permissions == frozenset()
    assert local_server.id != foreign_server.id
    assert local_owner["id"] != foreign_owner["id"]


def test_unknown_json_keys_never_become_effective_permissions(
    db_session, create_user
):
    member = create_user()
    server, membership, owner = _create_server_membership(db_session, member)
    server.everyone_permissions = {"private_channel_access": True}
    _assign_role(
        db_session,
        server,
        membership,
        owner,
        {"unlisted_capability": True},
    )

    resolved = resolve_server_permissions(db_session, server.id, member["id"])

    assert resolved.permissions == frozenset()
    assert has_server_permission(resolved, "private_channel_access") is False


def test_member_without_individual_roles_has_hierarchy_level_zero(
    db_session, create_user
):
    member = create_user()
    server, _, _ = _create_server_membership(db_session, member)

    assert get_member_hierarchy_level(db_session, server.id, member["id"]) == 0


def test_member_with_one_role_has_that_roles_position(db_session, create_user):
    member = create_user()
    server, membership, owner = _create_server_membership(db_session, member)
    role = _assign_role(
        db_session, server, membership, owner, {"kick_members": True}
    )
    role.position = 7
    db_session.flush()

    assert get_member_hierarchy_level(db_session, server.id, member["id"]) == 7


def test_member_hierarchy_uses_highest_of_multiple_roles(
    db_session, create_user
):
    member = create_user()
    server, membership, owner = _create_server_membership(db_session, member)
    lower_role = _assign_role(
        db_session, server, membership, owner, {"kick_members": True}
    )
    higher_role = _assign_role(
        db_session, server, membership, owner, {"ban_members": True}
    )
    lower_role.position = 2
    higher_role.position = 9
    db_session.flush()

    assert (
        get_member_hierarchy_level(db_session, server.id, member["id"]) == 9
    )


def test_member_hierarchy_accepts_multiple_roles_at_same_position(
    db_session, create_user
):
    member = create_user()
    server, membership, owner = _create_server_membership(db_session, member)
    first_role = _assign_role(
        db_session, server, membership, owner, {"kick_members": True}
    )
    second_role = _assign_role(
        db_session, server, membership, owner, {"ban_members": True}
    )
    first_role.position = 4
    second_role.position = 4
    db_session.flush()

    assert (
        get_member_hierarchy_level(db_session, server.id, member["id"]) == 4
    )


def test_everyone_permissions_do_not_affect_member_hierarchy(
    db_session, create_user
):
    member = create_user()
    server, _, _ = _create_server_membership(db_session, member)
    server.everyone_permissions = {"manage_roles": True, "ban_members": True}

    assert get_member_hierarchy_level(db_session, server.id, member["id"]) == 0


def test_left_member_cannot_have_hierarchy_level_resolved(
    db_session, create_user
):
    member = create_user()
    server, _, _ = _create_server_membership(
        db_session, member, status="LEFT"
    )

    with pytest.raises(HTTPException) as error:
        get_member_hierarchy_level(db_session, server.id, member["id"])

    assert error.value.status_code == 404


def test_member_active_only_in_another_server_is_not_resolved(
    db_session, create_user
):
    member = create_user()
    other_owner = create_user()
    requested_server, _, _ = _create_server_membership(
        db_session, other_owner
    )
    other_server, _, _ = _create_server_membership(
        db_session, member, owner_user=other_owner
    )

    with pytest.raises(HTTPException) as error:
        get_member_hierarchy_level(
            db_session, requested_server.id, member["id"]
        )

    assert error.value.status_code == 404
    assert requested_server.id != other_server.id


def test_role_from_another_server_does_not_influence_hierarchy(
    db_session, create_user
):
    target = create_user()
    local_server, local_membership, local_owner = _create_server_membership(
        db_session, target
    )
    other_user = create_user()
    foreign_server, foreign_membership, foreign_owner = (
        _create_server_membership(db_session, other_user)
    )
    foreign_role = _assign_role(
        db_session,
        foreign_server,
        foreign_membership,
        foreign_owner,
        {"manage_roles": True},
    )
    foreign_role.position = 100
    db_session.flush()

    assert (
        get_member_hierarchy_level(db_session, local_server.id, target["id"])
        == 0
    )
    assert local_membership.server_id != foreign_role.server_id
    assert local_owner["id"] != foreign_owner["id"]


def test_owner_without_individual_roles_has_zero_level_and_separate_authority(
    db_session, create_user
):
    owner = create_user()
    server, _, _ = _create_server_membership(db_session, owner)

    level = get_member_hierarchy_level(db_session, server.id, owner["id"])
    resolved = resolve_server_permissions(db_session, server.id, owner["id"])

    assert level == 0
    assert resolved.is_owner is True
    assert resolved.permissions == frozenset()


def _create_hierarchy_memberships(
    db_session,
    owner: dict,
    actor: dict,
    target: dict,
    *,
    actor_status: str = "ACTIVE",
    target_status: str = "ACTIVE",
) -> tuple[Server, ServerMember, ServerMember]:
    server = Server(owner_id=owner["id"], name="Servidor de hierarquia")
    db_session.add(server)
    db_session.flush()

    memberships: dict[int, ServerMember] = {}
    for user, member_status in (
        (actor, actor_status),
        (target, target_status),
    ):
        if user["id"] in memberships:
            continue
        memberships[user["id"]] = ServerMember(
            server_id=server.id,
            user_id=user["id"],
            status=member_status,
            left_at=(
                datetime.now(timezone.utc)
                if member_status == "LEFT"
                else None
            ),
        )
    db_session.add_all(memberships.values())
    db_session.flush()
    return server, memberships[actor["id"]], memberships[target["id"]]


def _assign_role_at_position(
    db_session,
    server: Server,
    membership: ServerMember,
    assigned_by: dict,
    position: int,
) -> ServerRole:
    role = _assign_role(
        db_session,
        server,
        membership,
        assigned_by,
        {},
    )
    role.position = position
    db_session.flush()
    return role


def test_hierarchy_comparison_allows_actor_strictly_above_target(
    db_session, create_user
):
    owner = create_user()
    actor = create_user()
    target = create_user()
    server, actor_membership, target_membership = _create_hierarchy_memberships(
        db_session, owner, actor, target
    )
    _assign_role_at_position(
        db_session, server, actor_membership, owner, 5
    )
    _assign_role_at_position(
        db_session, server, target_membership, owner, 2
    )

    assert is_hierarchy_comparison_approved(
        db_session, server.id, actor["id"], target["id"]
    ) is True
    actor_permissions = get_effective_server_permissions(
        db_session, server.id, actor["id"]
    )
    assert actor_permissions == frozenset()


def test_hierarchy_comparison_rejects_equal_positions(db_session, create_user):
    owner, actor, target = (create_user() for _ in range(3))
    server, actor_membership, target_membership = _create_hierarchy_memberships(
        db_session, owner, actor, target
    )
    _assign_role_at_position(
        db_session, server, actor_membership, owner, 4
    )
    _assign_role_at_position(
        db_session, server, target_membership, owner, 4
    )

    assert is_hierarchy_comparison_approved(
        db_session, server.id, actor["id"], target["id"]
    ) is False


def test_hierarchy_comparison_rejects_actor_below_target(db_session, create_user):
    owner, actor, target = (create_user() for _ in range(3))
    server, actor_membership, target_membership = _create_hierarchy_memberships(
        db_session, owner, actor, target
    )
    _assign_role_at_position(
        db_session, server, actor_membership, owner, 1
    )
    _assign_role_at_position(
        db_session, server, target_membership, owner, 6
    )

    assert is_hierarchy_comparison_approved(
        db_session, server.id, actor["id"], target["id"]
    ) is False


def test_members_at_level_zero_are_not_hierarchically_above_each_other(
    db_session, create_user
):
    owner, actor, target = (create_user() for _ in range(3))
    server, _, _ = _create_hierarchy_memberships(
        db_session, owner, actor, target
    )

    assert is_hierarchy_comparison_approved(
        db_session, server.id, actor["id"], target["id"]
    ) is False


def test_level_zero_actor_is_not_above_member_with_role(db_session, create_user):
    owner, actor, target = (create_user() for _ in range(3))
    server, _, target_membership = _create_hierarchy_memberships(
        db_session, owner, actor, target
    )
    _assign_role_at_position(
        db_session, server, target_membership, owner, 1
    )

    assert is_hierarchy_comparison_approved(
        db_session, server.id, actor["id"], target["id"]
    ) is False


def test_hierarchy_comparison_uses_actors_highest_of_multiple_roles(
    db_session, create_user
):
    owner, actor, target = (create_user() for _ in range(3))
    server, actor_membership, target_membership = _create_hierarchy_memberships(
        db_session, owner, actor, target
    )
    _assign_role_at_position(
        db_session, server, actor_membership, owner, 2
    )
    _assign_role_at_position(
        db_session, server, actor_membership, owner, 8
    )
    _assign_role_at_position(
        db_session, server, target_membership, owner, 7
    )

    assert is_hierarchy_comparison_approved(
        db_session, server.id, actor["id"], target["id"]
    ) is True


def test_everyone_permissions_do_not_change_hierarchy_comparison(
    db_session, create_user
):
    owner, actor, target = (create_user() for _ in range(3))
    server, _, _ = _create_hierarchy_memberships(
        db_session, owner, actor, target
    )
    server.everyone_permissions = {"manage_roles": True, "kick_members": True}

    assert is_hierarchy_comparison_approved(
        db_session, server.id, actor["id"], target["id"]
    ) is False


def test_owner_passes_hierarchy_gate_for_active_common_member(db_session, create_user):
    owner, target = (create_user() for _ in range(2))
    server, _, target_membership = _create_hierarchy_memberships(
        db_session, owner, owner, target
    )
    _assign_role_at_position(
        db_session, server, target_membership, owner, 100
    )

    assert is_hierarchy_comparison_approved(
        db_session, server.id, owner["id"], target["id"]
    ) is True


def test_common_member_fails_hierarchy_gate_against_owner(db_session, create_user):
    owner, actor = (create_user() for _ in range(2))
    server, actor_membership, _ = _create_hierarchy_memberships(
        db_session, owner, actor, owner
    )
    _assign_role_at_position(
        db_session, server, actor_membership, owner, 100
    )

    assert is_hierarchy_comparison_approved(
        db_session, server.id, actor["id"], owner["id"]
    ) is False


def test_actor_cannot_pass_hierarchy_gate_against_self(db_session, create_user):
    owner, actor = (create_user() for _ in range(2))
    server, _, _ = _create_hierarchy_memberships(
        db_session, owner, actor, actor
    )

    assert is_hierarchy_comparison_approved(
        db_session, server.id, actor["id"], actor["id"]
    ) is False


@pytest.mark.parametrize("inactive_side", ["actor", "target"])
def test_hierarchy_comparison_rejects_left_actor_or_target(
    db_session, create_user, inactive_side: str
):
    owner, actor, target = (create_user() for _ in range(3))
    server, _, _ = _create_hierarchy_memberships(
        db_session,
        owner,
        actor,
        target,
        actor_status="LEFT" if inactive_side == "actor" else "ACTIVE",
        target_status="LEFT" if inactive_side == "target" else "ACTIVE",
    )

    with pytest.raises(HTTPException) as error:
        is_hierarchy_comparison_approved(
            db_session, server.id, actor["id"], target["id"]
        )

    assert error.value.status_code == 404


@pytest.mark.parametrize("inactive_side", ["actor", "target"])
def test_hierarchy_comparison_rejects_member_from_another_server(
    db_session, create_user, inactive_side: str
):
    owner, actor, target = (create_user() for _ in range(3))
    server, _, _ = _create_hierarchy_memberships(
        db_session,
        owner,
        actor,
        target,
    )
    other_server = Server(owner_id=owner["id"], name="Outro servidor")
    db_session.add(other_server)
    db_session.flush()
    foreign_user = actor if inactive_side == "actor" else target
    db_session.add(
        ServerMember(
            server_id=other_server.id,
            user_id=foreign_user["id"],
            status="ACTIVE",
        )
    )
    if inactive_side == "actor":
        db_session.query(ServerMember).filter_by(
            server_id=server.id,
            user_id=actor["id"],
        ).delete()
    else:
        db_session.query(ServerMember).filter_by(
            server_id=server.id,
            user_id=target["id"],
        ).delete()
    db_session.flush()

    with pytest.raises(HTTPException) as error:
        is_hierarchy_comparison_approved(
            db_session, server.id, actor["id"], target["id"]
        )

    assert error.value.status_code == 404
