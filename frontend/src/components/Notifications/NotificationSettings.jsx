import React, { useEffect, useCallback, useState } from 'react';
import { apiFetch } from '../../api/client.js';
import { PUSH_ENABLED_STORAGE_KEY as STORAGE_KEY } from '../../push/resubscribe.js';
import {
  fetchVapidPublicKey,
  getActiveSubscription,
  isIOS,
  isSecureContext,
  isStandalonePWA,
  pushSupported,
  restoreServerSubscription,
  unsubscribeAndUnregister,
  unsupportedReason,
} from '../../push/notifications.js';
import './NotificationSettings.css';

export default function NotificationSettings() {
  const [supported, setSupported]       = useState(false);
  const [permission, setPermission]     = useState('default');
  const [enabled, setEnabled]           = useState(false);
  const [busy, setBusy]                 = useState(false);
  const [error, setError]               = useState(null);
  const [success, setSuccess]           = useState(null);
  const [serverConfigured, setServerConfigured] = useState(true);
  const [subscribed, setSubscribed]     = useState(false);
  const [refreshing, setRefreshing]     = useState(false);

  const refreshStatus = useCallback(async () => {
    if (!pushSupported()) return;
    setRefreshing(true);
    setError(null);
    try {
      setPermission(Notification.permission);
      const key = await fetchVapidPublicKey();
      setServerConfigured(!!key);
      if (key) {
        const sub = await getActiveSubscription();
        const stored = localStorage.getItem(STORAGE_KEY) === 'true';
        const locallyEnabled = !!sub && stored && Notification.permission === 'granted';
        if (locallyEnabled) {
          await restoreServerSubscription(key);
        }
        setSubscribed(!!sub);
        setEnabled(locallyEnabled);
      }
    } catch {
      // silently ignore
    } finally {
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    setSupported(pushSupported());
    if (!pushSupported()) return;
    refreshStatus();
  }, [refreshStatus]);

  const enable = async () => {
    setBusy(true);
    setError(null);
    setSuccess(null);
    try {
      const result = Notification.permission === 'granted'
        ? 'granted'
        : await Notification.requestPermission();
      setPermission(result);
      if (result !== 'granted') {
        if (result === 'denied') {
          setError('Notifications are blocked in your browser settings. You need to re-enable them for this site in your browser preferences.');
        }
        return;
      }

      const vapid = await fetchVapidPublicKey();
      if (!vapid) {
        setServerConfigured(false);
        throw new Error('Push notifications are not configured on the server');
      }
      await restoreServerSubscription(vapid);
      setEnabled(true);
      setSubscribed(true);
      setSuccess('Notifications enabled for this device.');
    } catch (err) {
      setError(err.message || 'Could not enable notifications');
    } finally {
      setBusy(false);
    }
  };

  const disable = async () => {
    setBusy(true);
    setError(null);
    setSuccess(null);
    try {
      await unsubscribeAndUnregister();
      localStorage.setItem(STORAGE_KEY, 'false');
      setEnabled(false);
      setSubscribed(false);
      setSuccess('Notifications disabled for this device.');
    } catch (err) {
      setError(err.message || 'Could not disable notifications');
    } finally {
      setBusy(false);
    }
  };

  const sendTest = async () => {
    setBusy(true);
    setError(null);
    setSuccess(null);
    try {
      const vapid = await fetchVapidPublicKey();
      if (!vapid) {
        setServerConfigured(false);
        throw new Error('Push notifications are not configured on the server');
      }
      await restoreServerSubscription(vapid);
      setEnabled(true);
      setSubscribed(true);

      const res = await apiFetch('/api/v1/push/test', { method: 'POST' });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || 'Test push failed');
      }
      setSuccess('Test push sent! Check your device notification.');
    } catch (err) {
      setError(err.message || 'Could not send test push');
    } finally {
      setBusy(false);
    }
  };

  if (!supported) {
    return (
      <section className="notification-settings">
        <h2>Push Notifications</h2>
        <p>{unsupportedReason()}</p>
      </section>
    );
  }
  if (!serverConfigured) {
    return (
      <section className="notification-settings">
        <h2>Push Notifications</h2>
        <p>Push notifications are not configured for this server yet. An administrator needs to set VAPID keys in the server environment.</p>
      </section>
    );
  }

  return (
    <section className="notification-settings">
      <div className="notif-header-row">
        <h2>Push Notifications</h2>
        <button
          type="button"
          className="notif-refresh-btn"
          onClick={refreshStatus}
          disabled={refreshing}
          title="Refresh status"
          aria-label="Refresh notification status"
        >
          {refreshing ? '⟳' : '↻'}
        </button>
      </div>
      <p>Get notified about mentions, events, and important updates even when Friend Hub isn't open.</p>

      <div className="notification-status">
        {permission === 'granted' && enabled && subscribed ? (
          <div className="status-enabled">
            <span className="status-icon">🔔</span>
            <div>
              <span>Notifications enabled on this device</span>
              <small>Subscription active</small>
            </div>
          </div>
        ) : permission === 'denied' ? (
          <div className="status-denied">
            <span className="status-icon">🚫</span>
            <div>
              <span>Notifications blocked by browser</span>
              <small>Friend Hub cannot send notifications until you re-enable them in your browser or site settings (look for the lock or info icon next to the URL bar, find "Notifications", and set to "Allow").</small>
            </div>
          </div>
        ) : (
          <div className="status-default">
            <span className="status-icon">🔕</span>
            <div>
              <span>Notifications not enabled</span>
              {permission === 'default' && (
                <small>Tap "Enable Notifications" below to get started.</small>
              )}
              {subscribed && !enabled && (
                <small>Found an old subscription — re-enable to activate.</small>
              )}
            </div>
          </div>
        )}
      </div>

      {error && <div className="notification-error">{error}</div>}
      {success && <div className="notification-success">{success}</div>}

      <div className="notification-buttons">
        <button
          type="button"
          className="notification-toggle"
          onClick={enabled ? disable : enable}
          disabled={busy || permission === 'denied'}
        >
          {busy ? 'Working…' : enabled ? 'Disable Notifications' : 'Enable Notifications'}
        </button>

        {enabled && (
          <button
            type="button"
            className="notification-secondary"
            onClick={sendTest}
            disabled={busy}
          >
            Send test
          </button>
        )}
      </div>

      {isIOS() && !isStandalonePWA() && (
        <div className="notification-ios-warning" role="alert">
          <strong>📱 iOS needs a Home Screen install</strong>
          <p>On iPhone/iPad, install Friend Hub to your Home Screen first:</p>
          <ol>
            <li>Tap the <strong>Share button</strong> (square with arrow) in Safari</li>
            <li>Scroll down and tap <strong>Add to Home Screen</strong></li>
            <li>Open Friend Hub from the Home Screen, then enable notifications here</li>
          </ol>
        </div>
      )}

      {!isIOS() && !isSecureContext() && (
        <div className="notification-ios-warning" role="alert">
          <strong>🔒 HTTPS required</strong>
          <p>Push notifications need a secure connection (HTTPS or localhost). Open Friend Hub over HTTPS to enable them.</p>
        </div>
      )}
    </section>
  );
}
