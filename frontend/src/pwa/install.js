// Shared access to the browser's `beforeinstallprompt` event.
//
// The event fires once, early, and can only be captured by a listener that is
// already registered. Several places want to trigger install (the onboarding
// tour, the install banner), so we capture it once here and hand it out, rather
// than letting whichever component mounts first consume it.

let deferredPrompt = null;
const subscribers = new Set();

function notify() {
  subscribers.forEach((fn) => fn(deferredPrompt));
}

if (typeof window !== 'undefined') {
  window.addEventListener('beforeinstallprompt', (event) => {
    event.preventDefault();
    deferredPrompt = event;
    notify();
  });
  // Once installed, the prompt is spent — clear it so UI can hide install CTAs.
  window.addEventListener('appinstalled', () => {
    deferredPrompt = null;
    notify();
  });
}

export function isStandalone() {
  if (typeof window === 'undefined') return false;
  return (
    window.matchMedia('(display-mode: standalone)').matches ||
    window.navigator.standalone === true
  );
}

export function isIOS() {
  if (typeof navigator === 'undefined') return false;
  return /iphone|ipad|ipod/i.test(navigator.userAgent);
}

// Whether a native (Android/Chrome) install prompt is currently available.
export function canPromptInstall() {
  return deferredPrompt !== null;
}

// Trigger the native install dialog. Returns the user's choice outcome
// ('accepted' | 'dismissed'), or null if no prompt was available.
export async function promptInstall() {
  if (!deferredPrompt) return null;
  deferredPrompt.prompt();
  const { outcome } = await deferredPrompt.userChoice;
  // A prompt can only be used once.
  deferredPrompt = null;
  notify();
  return outcome;
}

// Subscribe to availability changes; returns an unsubscribe function and
// immediately reports the current value.
export function subscribeInstall(fn) {
  subscribers.add(fn);
  fn(deferredPrompt);
  return () => subscribers.delete(fn);
}
