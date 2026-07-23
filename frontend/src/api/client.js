const TOKEN_KEY = 'friendHub.token';
const ROOM_SLUG_KEY = 'friendHub.currentRoomSlug';

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token) {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

export function getCurrentRoomSlug() {
  return localStorage.getItem(ROOM_SLUG_KEY);
}

export function setCurrentRoomSlug(slug) {
  if (slug) {
    localStorage.setItem(ROOM_SLUG_KEY, slug);
  } else {
    localStorage.removeItem(ROOM_SLUG_KEY);
  }
}

export function clearCurrentRoomSlug() {
  localStorage.removeItem(ROOM_SLUG_KEY);
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
