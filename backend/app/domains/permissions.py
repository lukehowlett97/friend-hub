from app.models.member import MemberRole


MANAGE_MEMBERS = "manage_members"
MANAGE_ROLES = "manage_roles"

ROLE_PERMISSIONS = {
    MemberRole.owner: {MANAGE_MEMBERS, MANAGE_ROLES},
    MemberRole.admin: {MANAGE_MEMBERS},
    MemberRole.member: set(),
}


def normalize_role(role: str | MemberRole | None) -> MemberRole:
    if isinstance(role, MemberRole):
        return role
    if role in {item.value for item in MemberRole}:
        return MemberRole(role)
    return MemberRole.member


def role_has_permission(role: str | MemberRole | None, permission: str) -> bool:
    return permission in ROLE_PERMISSIONS[normalize_role(role)]


def can_assign_role(
    requester_role: str | MemberRole | None,
    target_role: str | MemberRole | None,
    requested_role: str | MemberRole | None,
) -> bool:
    requester = normalize_role(requester_role)
    target = normalize_role(target_role)
    requested = normalize_role(requested_role)

    if requester == MemberRole.owner:
        return True

    if requester != MemberRole.admin:
        return False

    return target != MemberRole.owner and requested != MemberRole.owner
