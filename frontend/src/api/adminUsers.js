import { apiFetch } from './client.js';

async function readJson(res, fallback) {
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || fallback);
  return data;
}

export async function listAdminUsers() {
  const res = await apiFetch('/api/v1/admin/users');
  return readJson(res, 'Could not load users');
}

export async function listIdentityUsers(params = {}) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') search.set(key, value);
  });
  const suffix = search.toString() ? `?${search.toString()}` : '';
  const res = await apiFetch(`/api/v1/admin/identity/users${suffix}`);
  return readJson(res, 'Could not load identity users');
}

export async function listImportedIdentities(params = {}) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') search.set(key, value);
  });
  const suffix = search.toString() ? `?${search.toString()}` : '';
  const res = await apiFetch(`/api/v1/admin/identity/imported-identities${suffix}`);
  return readJson(res, 'Could not load imported identities');
}

export async function createAdminUser(payload) {
  const res = await apiFetch('/api/v1/admin/users', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  return readJson(res, 'Could not create user');
}

export async function resetUserPin(userId) {
  const res = await apiFetch(`/api/v1/admin/users/${userId}/reset-pin`, { method: 'POST' });
  return readJson(res, 'Could not reset PIN');
}

export async function deactivateUser(userId) {
  const res = await apiFetch(`/api/v1/admin/users/${userId}/deactivate`, { method: 'POST' });
  return readJson(res, 'Could not deactivate user');
}

export async function reactivateUser(userId) {
  const res = await apiFetch(`/api/v1/admin/users/${userId}/reactivate`, { method: 'POST' });
  return readJson(res, 'Could not reactivate user');
}

export async function changeUserRole(userId, role) {
  const res = await apiFetch(`/api/v1/admin/users/${userId}/role`, {
    method: 'PATCH',
    body: JSON.stringify({ role }),
  });
  return readJson(res, 'Could not change role');
}

export async function updateUserProfile(userId, payload) {
  const res = await apiFetch(`/api/v1/admin/users/${userId}/profile`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
  return readJson(res, 'Could not update user profile');
}

export async function updateUserRoom(userId, roomId, role) {
  const res = await apiFetch(`/api/v1/admin/users/${userId}/rooms/${roomId}`, {
    method: 'PATCH',
    body: JSON.stringify({ role }),
  });
  return readJson(res, 'Could not update room membership');
}

export async function removeUserRoom(userId, roomId) {
  const res = await apiFetch(`/api/v1/admin/users/${userId}/rooms/${roomId}`, { method: 'DELETE' });
  return readJson(res, 'Could not remove room membership');
}

export async function updateIdentityUser(userId, payload) {
  const res = await apiFetch(`/api/v1/admin/identity/users/${userId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
  return readJson(res, 'Could not update cleanup fields');
}

export async function updateImportedIdentity(identityId, payload) {
  const res = await apiFetch(`/api/v1/admin/identity/imported-identities/${identityId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
  return readJson(res, 'Could not update imported identity');
}

export async function linkImportedIdentity(identityId, userId) {
  const res = await apiFetch(`/api/v1/admin/identity/imported-identities/${identityId}/link`, {
    method: 'POST',
    body: JSON.stringify({ user_id: userId }),
  });
  return readJson(res, 'Could not link imported identity');
}

export async function unlinkImportedIdentity(identityId) {
  const res = await apiFetch(`/api/v1/admin/identity/imported-identities/${identityId}/unlink`, {
    method: 'POST',
  });
  return readJson(res, 'Could not unlink imported identity');
}
