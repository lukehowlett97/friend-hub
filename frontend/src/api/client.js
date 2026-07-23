const TOKEN_KEY = 'friendHub.token';
const ROOM_SLUG_KEY = 'friendHub.currentRoomSlug';
const DEMO_TOKEN_KEY = 'friendHub.demoToken';
const DEMO_ROOM_SLUG_KEY = 'friendHub.demoRoomSlug';

export function isDemoMode() {
  return window.sessionStorage.getItem(DEMO_TOKEN_KEY) !== null;
}

export function getToken() {
  return window.sessionStorage.getItem(DEMO_TOKEN_KEY) || localStorage.getItem(TOKEN_KEY);
}

export function setToken(token) {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
  window.sessionStorage.removeItem(DEMO_TOKEN_KEY);
}

export function setDemoToken(token) {
  if (token) window.sessionStorage.setItem(DEMO_TOKEN_KEY, token);
}

export function clearDemoSession() {
  window.sessionStorage.removeItem(DEMO_TOKEN_KEY);
  window.sessionStorage.removeItem(DEMO_ROOM_SLUG_KEY);
}

export function getCurrentRoomSlug() {
  return window.sessionStorage.getItem(DEMO_ROOM_SLUG_KEY) || localStorage.getItem(ROOM_SLUG_KEY);
}

export function setCurrentRoomSlug(slug) {
  if (isDemoMode()) {
    if (slug) window.sessionStorage.setItem(DEMO_ROOM_SLUG_KEY, slug);
    else window.sessionStorage.removeItem(DEMO_ROOM_SLUG_KEY);
    return;
  }
  if (slug) {
    localStorage.setItem(ROOM_SLUG_KEY, slug);
  } else {
    localStorage.removeItem(ROOM_SLUG_KEY);
  }
}

export function clearCurrentRoomSlug() {
  localStorage.removeItem(ROOM_SLUG_KEY);
  window.sessionStorage.removeItem(DEMO_ROOM_SLUG_KEY);
}

export function currentRoomHeaders() {
  const slug = getCurrentRoomSlug();
  return slug ? { 'X-Room-Slug': slug } : {};
}

export async function apiFetch(path, options = {}) {
  const token = getToken();
  const response = await fetch(path, {
    ...options,
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...currentRoomHeaders(),
      ...(options.headers || {}),
    },
  });
  return response;
}
