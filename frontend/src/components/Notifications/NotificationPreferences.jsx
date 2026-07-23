import React, { useEffect, useState } from 'react';
import { apiFetch } from '../../api/client.js';
import './NotificationSettings.css';

const PREFERENCE_LABELS = {
  chat_messages: 'Chat messages',
  chat_mentions: 'Chat mentions',
  polls: 'Polls and votes',
  events: 'New events',
  reminders: 'Reminders',
  comments: 'Comments on your items',
  reactions: 'Reactions to your content',
  hub_bot: 'Hub Bot announcements',
};

const PREFERENCE_DESCRIPTIONS = {
  chat_messages: 'When any new message is sent to the chat',
  chat_mentions: 'When someone @mentions you in chat',
  polls: 'When a new poll is created or voting ends',
  events: 'When someone creates a new event',
  reminders: 'When you are assigned a reminder or a due date approaches',
  comments: 'When someone comments on your ideas, polls, or events',
  reactions: 'When someone reacts to your content',
  hub_bot: 'Messages and summaries from Hub Bot',
};

export default function NotificationPreferences() {
  const [preferences, setPreferences] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(null); // field name being saved
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);

  useEffect(() => {
    loadPreferences();
  }, []);

  const loadPreferences = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await apiFetch('/api/v1/notifications/preferences');
      if (!res.ok) throw new Error('Failed to load preferences');
      const data = await res.json();
      setPreferences(data.preferences);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const togglePreference = async (field) => {
    const newValue = !preferences[field];
    setSaving(field);
    setError(null);
    setSuccess(null);
    try {
      const res = await apiFetch('/api/v1/notifications/preferences', {
        method: 'PUT',
        body: JSON.stringify({ [field]: newValue }),
      });
      if (!res.ok) throw new Error('Failed to update preference');
      const data = await res.json();
      setPreferences(data.preferences);
      setSuccess(`${PREFERENCE_LABELS[field] || field} ${newValue ? 'enabled' : 'disabled'}`);
    } catch (err) {
      setError(err.message || 'Could not update preference');
    } finally {
      setSaving(null);
    }
  };

  if (loading) {
    return (
      <section className="notification-settings">
        <h2>Notification Preferences</h2>
        <p>Loading your preferences…</p>
      </section>
    );
  }

  if (error && !preferences) {
    return (
      <section className="notification-settings">
        <h2>Notification Preferences</h2>
        <p>Could not load preferences.</p>
      </section>
    );
  }

  if (!preferences) return null;

  const preferenceFields = [
    'chat_messages',
    'chat_mentions',
    'polls',
    'events',
    'reminders',
    'comments',
    'reactions',
    'hub_bot',
  ];

  return (
    <section className="notification-settings">
      <h2>Notification Preferences</h2>
      <p>Choose which types of notifications you want to receive on this account.</p>

      {error && <div className="notification-error">{error}</div>}
      {success && <div className="notification-success">{success}</div>}

      <div className="preference-list">
        {preferenceFields.map((field) => (
          <label key={field} className={`preference-row${saving === field ? ' saving' : ''}`}>
            <div className="preference-info">
              <span className="preference-label">{PREFERENCE_LABELS[field] || field}</span>
              <span className="preference-desc">{PREFERENCE_DESCRIPTIONS[field] || ''}</span>
            </div>
            <div className="preference-toggle-wrap">
              <input
                type="checkbox"
                className="preference-toggle-input"
                checked={!!preferences[field]}
                onChange={() => togglePreference(field)}
                disabled={saving !== null}
                id={`pref-${field}`}
              />
              <label
                className={`preference-toggle-switch${preferences[field] ? ' checked' : ''}`}
                htmlFor={`pref-${field}`}
                aria-label={`${PREFERENCE_LABELS[field] || field}: ${preferences[field] ? 'enabled' : 'disabled'}`}
              >
                <span className="preference-toggle-knob" />
              </label>
            </div>
          </label>
        ))}
      </div>

      <div className="preference-push-status">
        <label className="preference-row">
          <div className="preference-info">
            <span className="preference-label">Push delivery</span>
            <span className="preference-desc">Receive these notifications as push alerts on this device</span>
          </div>
          <div className="preference-toggle-wrap">
            <input
              type="checkbox"
              className="preference-toggle-input"
              checked={!!preferences.push_enabled}
              onChange={() => togglePreference('push_enabled')}
              disabled={saving !== null}
              id="pref-push-enabled"
            />
            <label
              className={`preference-toggle-switch${preferences.push_enabled ? ' checked' : ''}`}
              htmlFor="pref-push-enabled"
              aria-label={`Push delivery: ${preferences.push_enabled ? 'enabled' : 'disabled'}`}
            >
              <span className="preference-toggle-knob" />
            </label>
          </div>
        </label>
      </div>
    </section>
  );
}