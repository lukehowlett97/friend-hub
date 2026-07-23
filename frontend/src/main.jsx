// src/main.jsx
import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App.jsx';
// Register the beforeinstallprompt listener as early as possible so the
// onboarding tour and install banner can offer a working install button.
import './pwa/install.js';

// Register the workbox-generated service worker (autoUpdate strategy is
// configured in vite.config.js). Runs in dev too — vite-plugin-pwa's
// devOptions:{enabled:true} makes that safe — so push subscription works
// on `npm run dev` without needing a production build.
import('virtual:pwa-register').then(async ({ registerSW }) => {
  registerSW({ immediate: true });
  // Re-register the push subscription with the server on every launch —
  // heals endpoint rotation and lost server rows without user action.
  const { syncPushSubscription } = await import('./push/resubscribe.js');
  syncPushSubscription();
}).catch(() => { /* no-op when PWA plugin is unavailable */ });

ReactDOM.createRoot(document.getElementById('root')).render(
  <App />
);
