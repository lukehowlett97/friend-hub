export const MEMBER_ROLES = ['member', 'admin', 'owner'];

export function canManageMembers(role) {
  return role === 'owner' || role === 'admin';
}

export function canAssignRole(requesterRole, targetRole, requestedRole) {
  if (requesterRole === 'owner') return true;
  if (requesterRole !== 'admin') return false;
  return targetRole !== 'owner' && requestedRole !== 'owner';
}

export function rolesAssignableBy(requesterRole, targetRole) {
  if (requesterRole === 'owner') return ['owner', 'admin', 'member'];
  if (requesterRole === 'admin' && targetRole !== 'owner') return ['admin', 'member'];
  return [];
}
