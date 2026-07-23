import { apiFetch } from '../api/client.js';
import { PUSH_ENABLED_STORAGE_KEY as STORAGE_KEY } from './resubscribe.js';

export function pushSupported() {
  return (
    typeof window !== 'undefined' &&
    'Notification' in window &&
    'serviceWorker' in navigator &&
    'PushManager' in window
  );
}

export function isStandalonePWA() {
  if (typeof window === 'undefined') return false;
  return (
    window.matchMedia?.('(display-mode: standalone)').matches ||
    window.navigator.standalone === true
  );
}

export function isIOS() {
  if (typeof navigator === 'undefined') return false;
  return (
    /iPhone|iPad|iPod/i.test(navigator.userAgent) ||
    (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)
  );
}

export function isSecureContext() {
  if (typeof window === 'undefined') return false;
  return window.isSecureContext;
}

export function unsupportedReason() {
  if (!isSecureContext()) {
    return 'Notifications need an HTTPS connection (or localhost). Open Friend Hub over HTTPS to enable them.';
  }
  if (isIOS() && !isStandalonePWA()) {
    return 'On iPhone/iPad, install Friend Hub first: tap the Share button, choose Add to Home Screen, then open it from the home screen and try again.';
  }
  return "This browser doesn't support push notifications. Try Chrome, Firefox, or Safari.";
}

function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
  const rawData = window.atob(base64);
  const outputArray = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; ++i) outputArray[i] = rawData.charCodeAt(i);
  return outputArray;
}

function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = '';
  for (let i = 0; i < bytes.byteLength; i++) binary += String.fromCharCode(bytes[i]);
  return window.btoa(binary);
}

export async function fetchVapidPublicKey() {
  const res = await fetch('/api/v1/push/vapid-public-key');
  if (!res.ok) return null;
  return (await res.json()).public_key;
}

function swReadyOrTimeout(ms = 7000) {
  return Promise.race([
    navigator.serviceWorker.ready,
    new Promise((_, reject) =>
      setTimeout(
        () => reject(new Error('Service worker did not become ready. Reload the page and try again.')),
        ms,
      ),
    ),
  ]);
}

export async function getActiveSubscription() {
  try {
    const reg = await swReadyOrTimeout(2000);
    return reg.pushManager.getSubscription();
  } catch {
    return null;
  }
}

async function subscribeAndRegister(vapidPublicKey) {
  const reg = await swReadyOrTimeout();
  let subscription = await reg.pushManager.getSubscription();

  if (!subscription) {
    subscription = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(vapidPublicKey),
    });
  }

  const res = await apiFetch('/api/v1/push/subscriptions', {
    method: 'POST',
    body: JSON.stringify({
      endpoint: subscription.endpoint,
      p256dh_key: arrayBufferToBase64(subscription.getKey('p256dh')),
      auth_key: arrayBufferToBase64(subscription.getKey('auth')),
      user_agent: navigator.userAgent,
    }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || 'Failed to register subscription');
  }
  return subscription;
}

export async function restoreServerSubscription(vapidPublicKey) {
  const subscription = await subscribeAndRegister(vapidPublicKey);
  localStorage.setItem(STORAGE_KEY, 'true');
  return subscription;
}

export async function enablePushNotifications() {
  if (!pushSupported()) {
    throw new Error(unsupportedReason());
  }

  const result = Notification.permission === 'granted'
    ? 'granted'
    : await Notification.requestPermission();
  if (result !== 'granted') {
    if (result === 'denied') {
      throw new Error('Notifications are blocked in your browser settings. Re-enable them for this site to use push alerts.');
    }
    throw new Error('Notifications were not enabled.');
  }

  const vapid = await fetchVapidPublicKey();
  if (!vapid) {
    throw new Error('Push notifications are not configured on the server.');
  }

  await restoreServerSubscription(vapid);
  return true;
}

export async function unsubscribeAndUnregister() {
  const subscription = await getActiveSubscription();
  if (!subscription) return;

  await apiFetch(
    `/api/v1/push/subscriptions?endpoint=${encodeURIComponent(subscription.endpoint)}`,
    { method: 'DELETE' },
  ).catch(() => { /* server-side cleanup is best-effort */ });

  await subscription.unsubscribe();
}
