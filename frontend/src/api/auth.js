import { apiFetch, setToken, clearToken } from './client.js';

export async function register({ username, nickname, invite_code }) {
  const res = await apiFetch('/api/v1/auth/register', {
    method: 'POST',
    body: JSON.stringify({ username, nickname, invite_code }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || 'Registration failed');
  setToken(data.token);
  return data.user;
}

export async function claimInvite({ invite_code, pin, pin_confirm }) {
  const res = await apiFetch('/api/v1/auth/claim-invite', {
    method: 'POST',
    body: JSON.stringify({ invite_code, pin, pin_confirm }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || 'Invite claim failed');
  if (data.token) setToken(data.token);
  return data.user;
}

// Validates an invite code without consuming it. Returns { valid, display_name }.
// Used by the /join landing page to greet the invitee and detect expired codes.
export async function peekInvite(inviteCode) {
  const res = await apiFetch(`/api/v1/auth/invite/${encodeURIComponent(inviteCode)}`);
  if (!res.ok) return { valid: false, display_name: null };
  return res.json().catch(() => ({ valid: false, display_name: null }));
}

export async function pinLogin({ username, pin }) {
  const res = await apiFetch('/api/v1/auth/pin-login', {
    method: 'POST',
    body: JSON.stringify({ username, pin }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || 'Login failed. Check your details and try again.');
  if (data.token) setToken(data.token);
  return data.user;
}

// Returns the user object on success, null on 401 (token invalid/expired),
// or throws on network / server errors so the caller can distinguish them.
export async function fetchMe() {
  const res = await apiFetch('/api/v1/auth/me');
  if (res.status === 401) return null;
  if (!res.ok) throw new Error('server_unavailable');
  const data = await res.json().catch(() => null);
  return data?.user ?? null;
}

export async function logoutApi() {
  await apiFetch('/api/v1/auth/logout', { method: 'POST' });
  clearToken();
}
