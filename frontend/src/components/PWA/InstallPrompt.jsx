import React, { useState, useEffect } from 'react';
import { canPromptInstall, isIOS, isStandalone, promptInstall, subscribeInstall } from '../../pwa/install.js';
import './InstallPrompt.css';

const STORAGE_KEY   = 'fh-install-dismissed-until';
const COOLDOWN_DAYS = 7;
const SHOW_DELAY_MS = 2500; // don't blast it on first render

function wasDismissed() {
  const until = localStorage.getItem(STORAGE_KEY);
  return until && Date.now() < Number(until);
}

function recordDismissal() {
  const until = Date.now() + COOLDOWN_DAYS * 24 * 60 * 60 * 1000;
  localStorage.setItem(STORAGE_KEY, String(until));
}

// ── Component ────────────────────────────────────────────────────────────────

const InstallPrompt = () => {
  const [mode, setMode]             = useState(null);  // 'android' | 'ios' | null
  const [visible, setVisible]       = useState(false);

  useEffect(() => {
    // Never show if already running as installed PWA or recently dismissed.
    if (isStandalone() || wasDismissed()) return;

    // Android / Chrome: the shared module captures beforeinstallprompt for us.
    const unsubscribe = subscribeInstall((prompt) => {
      if (prompt && !wasDismissed()) {
        setTimeout(() => {
          if (!wasDismissed()) { setMode('android'); setVisible(true); }
        }, SHOW_DELAY_MS);
      }
    });

    // iOS Safari: no browser prompt — show manual instructions instead.
    // Only on iOS and only if we're not already in standalone mode.
    if (isIOS()) {
      const id = setTimeout(() => {
        if (!wasDismissed() && !isStandalone()) {
          setMode('ios');
          setVisible(true);
        }
      }, SHOW_DELAY_MS);
      return () => {
        clearTimeout(id);
        unsubscribe();
      };
    }

    return unsubscribe;
  }, []);

  const handleInstall = async () => {
    if (!canPromptInstall()) return;
    await promptInstall();
    // Whether accepted or dismissed, hide and record.
    handleClose();
  };

  const handleClose = () => {
    recordDismissal();
    setVisible(false);
    setMode(null);
  };

  if (!visible || !mode) return null;

  return (
    <div className="install-prompt" role="banner" aria-label="Install Friend Hub">
      <div className="install-prompt-inner">
        <span className="install-prompt-icon" aria-hidden="true">📱</span>

        {mode === 'android' && (
          <div className="install-prompt-text">
            <strong>Add Friend Hub to your home screen</strong>
            <span>Open the app instantly, without a browser.</span>
          </div>
        )}

        {mode === 'ios' && (
          <div className="install-prompt-text">
            <strong>Add to Home Screen</strong>
            <span>
              Tap the <b>Share</b> button{' '}
              <span className="install-ios-share" aria-label="share icon">⎋</span>
              {' '}then <b>Add to Home Screen</b>.
            </span>
          </div>
        )}

        {mode === 'android' && (
          <button className="install-prompt-action" onClick={handleInstall}>
            Install
          </button>
        )}

        <button
          className="install-prompt-close"
          onClick={handleClose}
          aria-label="Dismiss install prompt"
        >
          ✕
        </button>
      </div>
    </div>
  );
};

export default InstallPrompt;
