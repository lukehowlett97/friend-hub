/// <reference lib="webworker" />
/* global self, clients */

import { precacheAndRoute, cleanupOutdatedCaches } from 'workbox-precaching';
import { registerRoute, NavigationRoute } from 'workbox-routing';
import { NetworkOnly } from 'workbox-strategies';

// Workbox precaches every Vite build asset. In dev the manifest is empty,
// which is fine — push handlers below still register.
precacheAndRoute(self.__WB_MANIFEST || []);
cleanupOutdatedCaches();

// SPA fallback for client-side routes; never for API/WS/uploads.
registerRoute(
  new NavigationRoute(
    async () => {
      const cache = await caches.open('workbox-precache-v2');
      return (await cache.match('/index.html')) || fetch('/index.html');
    },
    { denylist: [/^\/api\//, /^\/ws\//, /^\/uploads\//] },
  ),
);

// All dynamic routes go directly to network — uploads are auth-gated so must
// not be cached (stale cache could serve media to a different session).
registerRoute(({ url }) => url.pathname.startsWith('/api/'), new NetworkOnly());
registerRoute(({ url }) => url.pathname.startsWith('/ws/'), new NetworkOnly());
registerRoute(({ url }) => url.pathname.startsWith('/uploads/'), new NetworkOnly());

// ── Push notifications ──────────────────────────────────────────────────────

self.addEventListener('push', (event) => {
  let data = {};
  try {
    if (event.data) data = event.data.json();
  } catch {
    data = { title: 'Friend Hub', body: event.data ? event.data.text() : '' };
  }

  const title = data.title || 'Friend Hub';
  const targetData = data.data || {};
  const tag =
    data.tag ||
    (targetData.target_type && targetData.target_id
      ? `fh-${targetData.target_type}-${targetData.target_id}`
      : undefined);

  const options = {
    body: data.body || '',
    icon: data.icon || '/icons/notification-icon.svg',
    badge: data.badge || '/icons/notification-badge.svg',
    data: targetData,
    tag,
    renotify: !!data.renotify,
    timestamp: data.timestamp || Date.now(),
  };

  if (targetData.url) {
    options.actions = [{ action: 'open', title: targetData.action_title || 'Open' }];
  }

  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();

  const targetUrl = (event.notification.data && event.notification.data.url) || '/home';
  const fullUrl = new URL(targetUrl, self.location.origin).href;

  event.waitUntil((async () => {
    const allClients = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    for (const client of allClients) {
      if (client.url.startsWith(self.location.origin)) {
        await client.focus();
        if ('navigate' in client) {
          try { await client.navigate(fullUrl); } catch { /* ignore */ }
        }
        return;
      }
    }
    await self.clients.openWindow(fullUrl);
  })());
});

// Chrome (and other push services) can rotate a push endpoint at any time;
// when that happens the old subscription silently stops working. Re-subscribe
// and re-register with the server. Auth rides on the session cookie — the SW
// cannot read the bearer token in localStorage. Best-effort: if it fails
// (e.g. no session cookie), the app-startup re-sync heals it on next launch.
function swUrlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
  const rawData = atob(base64);
  const outputArray = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; ++i) outputArray[i] = rawData.charCodeAt(i);
  return outputArray;
}

function swArrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = '';
  for (let i = 0; i < bytes.byteLength; i++) binary += String.fromCharCode(bytes[i]);
  return btoa(binary);
}

self.addEventListener('pushsubscriptionchange', (event) => {
  event.waitUntil((async () => {
    try {
      let subscription = event.newSubscription || null;
      if (!subscription) {
        let applicationServerKey =
          (event.oldSubscription && event.oldSubscription.options &&
            event.oldSubscription.options.applicationServerKey) || null;
        if (!applicationServerKey) {
          const res = await fetch('/api/v1/push/vapid-public-key');
          if (!res.ok) return;
          applicationServerKey = swUrlBase64ToUint8Array((await res.json()).public_key);
        }
        subscription = await self.registration.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey,
        });
      }
      await fetch('/api/v1/push/subscriptions', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          endpoint: subscription.endpoint,
          p256dh_key: swArrayBufferToBase64(subscription.getKey('p256dh')),
          auth_key: swArrayBufferToBase64(subscription.getKey('auth')),
          user_agent: navigator.userAgent,
        }),
      });
    } catch {
      // best-effort — startup re-sync covers this path
    }
  })());
});

// Take control of clients immediately when the SW updates so push handlers
// from the new version start receiving events without a tab reload.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));
