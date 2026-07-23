const TOKEN_KEY = 'friendHub.token';
const ROOM_SLUG_KEY = 'friendHub.currentRoomSlug';
const DEMO_MODE_KEY = 'friendHub.demoMode';
const DEMO_ROOM_SLUG_KEY = 'friendHub.demoRoomSlug';

export function isDemoMode() {
  return window.sessionStorage.getItem(DEMO_MODE_KEY) === '1';
}

export function clearToken() {
  // Remove credentials created by older releases. Authentication is now
  // cookie-only, using the server's HttpOnly session cookie.
  localStorage.removeItem(TOKEN_KEY);
  window.sessionStorage.removeItem('friendHub.demoToken');
}

export function setDemoMode() {
  window.sessionStorage.setItem(DEMO_MODE_KEY, '1');
}

export function clearDemoSession() {
  window.sessionStorage.removeItem(DEMO_MODE_KEY);
  window.sessionStorage.removeItem('friendHub.demoToken');
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
  clearToken();
  const response = await fetch(path, {
    ...options,
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...currentRoomHeaders(),
      ...(options.headers || {}),
    },
  });
  return response;
}
