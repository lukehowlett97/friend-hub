import React from 'react';
import NotificationSettings from '../components/Notifications/NotificationSettings.jsx';
import NotificationPreferences from '../components/Notifications/NotificationPreferences.jsx';
import RoomSwitcher from '../components/AppShell/RoomSwitcher.jsx';
import { useTheme } from '../theme/ThemeProvider.jsx';
import './FeaturePages.css';

const SettingsPage = () => {
  const { themeId, themes, setThemeId } = useTheme();

  return (
    <section className="page feature-page">
      <header className="page-header">
        <h1>Settings</h1>
        <p className="page-subtitle">Manage your device preferences and notification settings.</p>
      </header>

      <section className="settings-section mobile-settings-room-section">
        <div className="settings-section__header">
          <h2>Room</h2>
          <p>Switch spaces on this device.</p>
        </div>
        <RoomSwitcher />
      </section>

      <section className="settings-section">
        <div className="settings-section__header">
          <h2>Theme</h2>
          <p>Choose how Friend Hub looks on this device.</p>
        </div>
        <div className="theme-picker-grid" role="radiogroup" aria-label="Theme">
          {themes.map((theme) => (
            <button
              key={theme.id}
              type="button"
              className={`theme-option${theme.id === themeId ? ' is-selected' : ''}`}
              onClick={() => setThemeId(theme.id)}
              role="radio"
              aria-checked={theme.id === themeId}
            >
              <span className="theme-option__preview" aria-hidden="true">
                <span style={{ background: theme.colours.background }} />
                <span style={{ background: theme.colours.primary }} />
                <span style={{ background: theme.colours.accent }} />
              </span>
              <span className="theme-option__body">
                <strong>{theme.name}</strong>
                <span>{theme.description}</span>
              </span>
            </button>
          ))}
        </div>
      </section>

      <NotificationSettings />

      <NotificationPreferences />
    </section>
  );
};

export default SettingsPage;
