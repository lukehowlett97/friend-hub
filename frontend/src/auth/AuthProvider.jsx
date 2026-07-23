import React, { createContext, useCallback, useContext, useEffect, useState } from 'react';
import { claimInvite as apiClaimInvite, createDemoSession, fetchMe, logoutApi, pinLogin as apiPinLogin, register as apiRegister } from '../api/auth.js';
import { apiFetch, getCurrentRoomSlug, setCurrentRoomSlug, clearCurrentRoomSlug, clearDemoSession, isDemoMode } from '../api/client.js';

const AuthContext = createContext(null);

const USER_CACHE_KEY = 'friendHub.user';

async function autoSelectRoom() {
  try {
    const res = await apiFetch('/api/v1/rooms');
    if (!res.ok) return;
    const data = await res.json();
    const rooms = data.rooms || [];
    if (rooms.length === 0) return;
    const currentSlug = getCurrentRoomSlug();
    const stillValid = currentSlug && rooms.some(r => r.slug === currentSlug);
    if (!stillValid) {
      // Prefer rooms where user is owner/admin, then by creation order
      const roleOrder = { owner: 0, admin: 1, member: 2 };
      const sorted = [...rooms].sort((a, b) => (roleOrder[a.role] ?? 3) - (roleOrder[b.role] ?? 3));
      setCurrentRoomSlug(sorted[0].slug);
    }
  } catch {
    // network error — leave slug as-is
  }
}

function readCachedUser() {
  try {
    if (isDemoMode()) {
      const rawDemo = window.sessionStorage.getItem(USER_CACHE_KEY);
      return rawDemo ? JSON.parse(rawDemo) : null;
    }
    const raw = localStorage.getItem(USER_CACHE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function writeCachedUser(user) {
  try {
    const storage = isDemoMode() ? window.sessionStorage : localStorage;
    if (user) storage.setItem(USER_CACHE_KEY, JSON.stringify(user));
    else storage.removeItem(USER_CACHE_KEY);
  } catch { /* storage quota */ }
}

export function AuthProvider({ children }) {
  // Seed from cache so there's no loading flash on refresh when already logged in.
  const [user, setUser] = useState(readCachedUser);
  // Only show a loading state when there's no cached user to render immediately.
  const [isLoading, setIsLoading] = useState(!readCachedUser());

  const updateUser = useCallback((u) => {
    setUser(u);
    writeCachedUser(u);
  }, []);

  useEffect(() => {
    const demoPath = window.location.pathname === '/demo';
    const authRequest = demoPath && !isDemoMode() ? createDemoSession() : fetchMe();
    authRequest
      .then(async u => {
        updateUser(u);
        if (u) {
          if (u.is_guest) setCurrentRoomSlug('demo');
          else await autoSelectRoom();
        }
      })
      .catch(() => {
        // Network error — keep cached user, WS will re-verify when server is back.
      })
      .finally(() => setIsLoading(false));
  }, [updateUser]);

  const register = async (credentials) => {
    const u = await apiRegister(credentials);
    updateUser(u);
    await autoSelectRoom();
    return u;
  };

  const claimInvite = async (credentials) => {
    const u = await apiClaimInvite(credentials);
    updateUser(u);
    await autoSelectRoom();
    return u;
  };

  const pinLogin = async (credentials) => {
    const u = await apiPinLogin(credentials);
    updateUser(u);
    await autoSelectRoom();
    return u;
  };

  const logout = async () => {
    await logoutApi();
    clearCurrentRoomSlug();
    clearDemoSession();
    updateUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, isLoading, isAuthenticated: !!user, register, claimInvite, pinLogin, logout, updateUser }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider');
  return ctx;
}
