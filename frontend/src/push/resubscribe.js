// Heal push subscriptions on app startup.
//
// Chrome on Android can rotate the push endpoint, or the server row can go
// missing, without the page ever finding out — the `pushsubscriptionchange`
// event is unreliable in practice. So on every launch, if the user previously
// enabled notifications on this device and permission is still granted,
// re-register the current subscription with the server (and re-subscribe
// first if the browser dropped it). Permission is already granted, so this
// never prompts.
import { apiFetch } from '../api/client.js';

export const PUSH_ENABLED_STORAGE_KEY = 'fh-notifications-enabled';

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

export async function syncPushSubscription() {
  try {
    if (
      typeof window === 'undefined' ||
      !('Notification' in window) ||
      !('serviceWorker' in navigator) ||
      !('PushManager' in window)
    ) return;
    if (Notification.permission !== 'granted') return;
    if (localStorage.getItem(PUSH_ENABLED_STORAGE_KEY) !== 'true') return;

    const reg = await navigator.serviceWorker.ready;
    let subscription = await reg.pushManager.getSubscription();

    if (!subscription) {
      const res = await fetch('/api/v1/push/vapid-public-key');
      if (!res.ok) return;
      const { public_key: publicKey } = await res.json();
      subscription = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(publicKey),
      });
    }

    await apiFetch('/api/v1/push/subscriptions', {
      method: 'POST',
      body: JSON.stringify({
        endpoint: subscription.endpoint,
        p256dh_key: arrayBufferToBase64(subscription.getKey('p256dh')),
        auth_key: arrayBufferToBase64(subscription.getKey('auth')),
        user_agent: navigator.userAgent,
      }),
    });
  } catch {
    // Best-effort: never block app startup over push housekeeping.
  }
}
