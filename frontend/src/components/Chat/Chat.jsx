import React, { useCallback, useState, useEffect, useRef } from 'react';
import MessageList from './MessageList';
import MessageInput from './MessageInput.jsx';
import OnlineUsers from './OnlineUsers.jsx';
import TypingIndicator from './TypingIndicator.jsx';
import ChatMessageToast from '../Notifications/ChatMessageToast.jsx';
import useWebSocket from '../../hooks/useWebSocket';
import { fetchDashboard, fetchEvents, fetchPolls, fetchMembers, uploadPhoto, fetchGroupNotice, pinMessage } from '../../services/api';
import { useTheme } from '../../theme/ThemeProvider.jsx';
import { useAuth } from '../../auth/AuthProvider.jsx';
import PhotoModal from '../Photos/PhotoModal.jsx';
import AgendaModal from './AgendaModal.jsx';
import PinnedLiveAgendaBanner from './PinnedLiveAgendaBanner.jsx';
import GroupNoticeboard from './GroupNoticeboard.jsx';
import LiveStatusIndicator from '../Live/LiveStatusIndicator.jsx';
import OnlineMembersModal from '../Members/OnlineMembersModal.jsx';
import RoomOverview from './RoomOverview.jsx';
import RoomTitleButton from './RoomTitleButton.jsx';
import ChatHelpModal from './ChatHelpModal.jsx';
import { navigate as navigateTo } from '../../utils/navigate.js';
import './Chat.css';

const CHAT_TEXT_SIZE_KEY = 'friendHub.chatTextSize';
const CHAT_BUBBLE_SPACING_KEY = 'friendHub.chatBubbleSpacing';
const CHAT_BUBBLE_COLOR_KEY = 'friendHub.chatBubbleColor';
const CHAT_BACKGROUND_KEY = 'friendHub.chatBackground';
const CHAT_QUICK_EMOJIS_KEY = 'friendHub.quickEmojis';
const CHAT_STICKY_INPUT_KEY = 'friendHub.chatStickyInput';
const DEFAULT_QUICK_EMOJIS = ['😀', '👍', '❤️', '😂', '🔥', '🎉'];
const CHAT_TEXT_SIZE_OPTIONS = {
  small: { label: 'Small', value: '13px' },
  medium: { label: 'Medium', value: '14px' },
  large: { label: 'Large', value: '16px' },
};
const CHAT_BUBBLE_SPACING_OPTIONS = {
  compact: { label: 'Compact', value: '0.08rem' },
  normal: { label: 'Normal', value: '0.35rem' },
  roomy: { label: 'Roomy', value: '0.58rem' },
};
const CHAT_BUBBLE_COLOR_OPTIONS = {
  slate: { label: 'Slate', value: '#516b82', text: '#ffffff' },
  blue: { label: 'Blue', value: '#2563eb', text: '#ffffff' },
  teal: { label: 'Teal', value: '#0f766e', text: '#ffffff' },
  green: { label: 'Green', value: '#15803d', text: '#ffffff' },
  rose: { label: 'Rose', value: '#e11d48', text: '#ffffff' },
  amber: { label: 'Amber', value: '#b45309', text: '#ffffff' },
};
const CHAT_BACKGROUND_MODES = {
  default: 'Default',
  colour: 'Colour',
  gradient: 'Gradient',
  pattern: 'Pattern',
};
const CHAT_BACKGROUND_DEFAULT = {
  mode: 'default',
  pattern: {
    id: 'classic-doodles',
    opacity: 0.08,
    scale: 1,
    colour: '#20352a',
  },
  scope: 'global',
};
const CHAT_BACKGROUND_COLOUR_PRESETS = ['#f7f2e8', '#e8f2ee', '#eaf0fb', '#f6eaf1', '#202b42', '#172033'];
const CHAT_BACKGROUND_GRADIENT_PRESETS = [
  { label: 'Dawn', from: '#fff7ed', to: '#e0f2fe' },
  { label: 'Mint', from: '#e8f5e9', to: '#fef9c3' },
  { label: 'Lilac', from: '#f5e8ff', to: '#e0f2fe' },
  { label: 'Coral', from: '#ffe4e6', to: '#fff7ed' },
  { label: 'Deep', from: '#172033', to: '#0f172a' },
  { label: 'Forest', from: '#eaf3e8', to: '#dcead7' },
];
const CHAT_BACKGROUND_PATTERN_PRESETS = {
  'classic-doodles': { label: 'Doodles', tile: 120 },
  social: { label: 'Social', tile: 104 },
  music: { label: 'Music', tile: 108 },
  football: { label: 'Football', tile: 112 },
  party: { label: 'Party', tile: 110 },
  nature: { label: 'Nature', tile: 112 },
};
const CHAT_BACKGROUND_PATTERN_COLOURS = ['#20352a', '#5168d9', '#2f6b4f', '#3f6f8f', '#7c3aed', '#f9734d'];
const CHAT_PATTERN_MAX_OPACITY = 0.5;

function clampNumber(value, min, max, fallback) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(max, Math.max(min, parsed));
}

function normaliseChatBackgroundSettings(value) {
  const source = value && typeof value === 'object' ? value : {};
  const mode = CHAT_BACKGROUND_MODES[source.mode] ? source.mode : CHAT_BACKGROUND_DEFAULT.mode;
  const fallbackPattern = CHAT_BACKGROUND_DEFAULT.pattern;
  const pattern = source.pattern && typeof source.pattern === 'object' ? source.pattern : {};
  const gradient = source.gradient && typeof source.gradient === 'object' ? source.gradient : {};

  return {
    mode,
    colour: typeof source.colour === 'string' ? source.colour : CHAT_BACKGROUND_COLOUR_PRESETS[0],
    gradient: {
      from: typeof gradient.from === 'string' ? gradient.from : CHAT_BACKGROUND_GRADIENT_PRESETS[0].from,
      to: typeof gradient.to === 'string' ? gradient.to : CHAT_BACKGROUND_GRADIENT_PRESETS[0].to,
    },
    pattern: {
      id: CHAT_BACKGROUND_PATTERN_PRESETS[pattern.id] ? pattern.id : fallbackPattern.id,
      opacity: clampNumber(pattern.opacity, 0, CHAT_PATTERN_MAX_OPACITY, fallbackPattern.opacity),
      scale: clampNumber(pattern.scale, 0.75, 2, fallbackPattern.scale),
      colour: typeof pattern.colour === 'string' ? pattern.colour : fallbackPattern.colour,
    },
    scope: source.scope === 'room' ? 'room' : 'global',
  };
}

function getStoredChatBackground() {
  try {
    return normaliseChatBackgroundSettings(JSON.parse(window.localStorage.getItem(CHAT_BACKGROUND_KEY)));
  } catch {
    return normaliseChatBackgroundSettings(CHAT_BACKGROUND_DEFAULT);
  }
}

function svgDataUri(svgContent) {
  return `url("data:image/svg+xml,${encodeURIComponent(svgContent)}")`;
}

function getPatternSvg(id, colour) {
  if (id === 'social') {
    return `<svg xmlns="http://www.w3.org/2000/svg" width="104" height="104" viewBox="0 0 104 104"><g fill="none" stroke="${colour}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 28c0-5 4-9 10-9h14c6 0 10 4 10 9v8c0 5-4 9-10 9h-8l-10 8 2-8h-8c-6 0-10-4-10-9z"/><path d="M69 58c9 0 16 6 16 14s-7 14-16 14-16-6-16-14 7-14 16-14z"/><path d="M62 72h14M69 65v14"/><path d="M76 22l4 8 8 1-6 6 1 9-7-4-8 4 2-9-6-6 8-1z"/></g></svg>`;
  }
  if (id === 'music') {
    return `<svg xmlns="http://www.w3.org/2000/svg" width="108" height="108" viewBox="0 0 108 108"><g fill="none" stroke="${colour}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M30 71V28l34-7v43"/><circle cx="24" cy="74" r="8"/><circle cx="58" cy="66" r="8"/><path d="M30 39l34-7"/><path d="M77 31c8 5 10 15 3 22"/><path d="M82 22c14 9 17 26 5 39"/></g></svg>`;
  }
  if (id === 'football') {
    return `<svg xmlns="http://www.w3.org/2000/svg" width="112" height="112" viewBox="0 0 112 112"><g fill="none" stroke="${colour}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="39" cy="39" r="22"/><path d="M39 24l9 7-4 11H34l-4-11z"/><path d="M30 31l-10 3M48 31l10 3M34 42l-7 10M44 42l7 10"/><path d="M71 71h25v16H71z"/><path d="M71 79H58M96 79h8M83 71V60M83 87v11"/></g></svg>`;
  }
  if (id === 'party') {
    return `<svg xmlns="http://www.w3.org/2000/svg" width="110" height="110" viewBox="0 0 110 110"><g fill="none" stroke="${colour}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M23 78l14-45 25 32z"/><path d="M31 53l15 6"/><path d="M70 23c10 6 11 17 1 24"/><path d="M83 18c4 8 3 15-4 20"/><path d="M78 70l5 8 9 2-7 6 1 9-8-4-8 4 2-9-7-6 9-2z"/><path d="M22 24l6 6M88 55l8-2M54 19l2-9"/></g></svg>`;
  }
  if (id === 'nature') {
    return `<svg xmlns="http://www.w3.org/2000/svg" width="112" height="112" viewBox="0 0 112 112"><g fill="none" stroke="${colour}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M27 76c23-5 36-20 41-47 17 17 8 46-16 54-13 4-22 1-25-7z"/><path d="M37 70c10-9 20-19 30-35"/><path d="M74 74c8 0 15-7 15-15 0-5-3-10-8-12-3-8-11-13-20-11"/><path d="M22 31c4-8 14-11 22-7 6 3 9 9 8 15"/></g></svg>`;
  }
  return `<svg xmlns="http://www.w3.org/2000/svg" width="120" height="120" viewBox="0 0 120 120"><g fill="none" stroke="${colour}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 27c0-5 4-9 9-9h14c5 0 9 4 9 9v8c0 5-4 9-9 9h-7l-10 8 2-8h-8c-5 0-9-4-9-9z"/><path d="M73 22l5 10 11 2-8 8 2 11-10-5-10 5 2-11-8-8 11-2z"/><path d="M24 82c9-10 20-10 29 0 7-8 16-9 24-3"/><path d="M86 73c6 0 11 5 11 11s-5 11-11 11-11-5-11-11 5-11 11-11z"/><path d="M82 84h8M86 80v8"/></g></svg>`;
}

function getChatBackgroundStyle(settings) {
  const value = normaliseChatBackgroundSettings(settings);
  if (value.mode === 'colour') {
    return { backgroundColor: value.colour };
  }
  if (value.mode === 'gradient') {
    return { background: `linear-gradient(145deg, ${value.gradient.from}, ${value.gradient.to})` };
  }
  if (value.mode === 'pattern') {
    const opacity = clampNumber(value.pattern.opacity, 0, CHAT_PATTERN_MAX_OPACITY, CHAT_BACKGROUND_DEFAULT.pattern.opacity);
    const scale = clampNumber(value.pattern.scale, 0.75, 2, CHAT_BACKGROUND_DEFAULT.pattern.scale);
    const tile = CHAT_BACKGROUND_PATTERN_PRESETS[value.pattern.id]?.tile || 120;
    return {
      backgroundColor: 'color-mix(in srgb, var(--color-surface-alt) 74%, var(--color-background))',
      backgroundImage: svgDataUri(getPatternSvg(value.pattern.id, value.pattern.colour)),
      backgroundRepeat: 'repeat',
      backgroundSize: `${Math.round(tile * scale)}px ${Math.round(tile * scale)}px`,
      opacity,
    };
  }
  return {};
}

function getStoredOption(key, options, fallback) {
  const stored = window.localStorage.getItem(key);
  return options[stored] ? stored : fallback;
}

function getPinnedItemRoute(item) {
  const type = item.type || item.hub_item?.type;
  if (type === 'event') return `/events/${item.source_id || item.hub_item?.source_id || item.id}`;
  if (type === 'idea') return '/ideas';
  if (type === 'poll') return '/polls';
  if (type === 'reminder') return '/reminders';
  return '/items';
}

function getPinnedSourceId(item) {
  return Number(item.source_id || item.hub_item?.source_id || item.id);
}

function formatPinnedDate(value) {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat(undefined, {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(date);
}

function getPinnedTitle(item) {
  const detail = item.detail || {};
  return detail.question || detail.title || item.question || item.title || 'Pinned item';
}

function getPinnedMeta(item) {
  const detail = item.detail || {};
  if ((item.type || detail.type) === 'event') return formatPinnedDate(detail.starts_at || item.event_start_at);
  if ((item.type || detail.type) === 'poll') {
    const totalVotes = detail.total_votes ?? detail.options?.reduce((sum, option) => sum + (option.vote_count || 0), 0);
    return `${totalVotes || 0} vote${totalVotes === 1 ? '' : 's'}`;
  }
  return formatPinnedDate(item.due_at || item.event_start_at || item.event_end_at || item.created_at);
}

function enrichPinnedItems(items, events, polls) {
  const eventsById = new Map((events || []).map((event) => [Number(event.id), event]));
  const pollsById = new Map((polls || []).map((poll) => [Number(poll.id), poll]));

  return items.map((item) => {
    const type = item.type || item.source_type;
    const sourceId = getPinnedSourceId(item);
    if (type === 'event') return { ...item, detail: eventsById.get(sourceId) || null };
    if (type === 'poll') return { ...item, detail: pollsById.get(sourceId) || null };
    return item;
  });
}

const PinnedItemCard = ({ item, onOpen }) => {
  const type = item.type || item.source_type || 'item';
  const detail = item.detail || {};
  const coverUrl = detail.cover_photo_url || item.cover_photo_url || item.cover_image_url;
  const coverX = detail.cover_photo_position_x ?? item.cover_photo_position_x ?? 50;
  const coverY = detail.cover_photo_position_y ?? item.cover_photo_position_y ?? 50;
  const title = getPinnedTitle(item);
  const meta = getPinnedMeta(item);
  const body = detail.description || item.body;
  const tags = detail.tags || item.tags || [];
  const pollOptions = type === 'poll' ? (detail.options || []) : [];
  const totalVotes = type === 'poll'
    ? (detail.total_votes ?? pollOptions.reduce((sum, option) => sum + (option.vote_count || 0), 0))
    : 0;

  return (
    <button type="button" className={`pinned-item-card pinned-item-card--${type}${coverUrl ? ' has-cover' : ''}`} onClick={onOpen}>
      {coverUrl && (
        <img
          className="pinned-item-card__cover"
          src={coverUrl}
          alt=""
          style={{ objectPosition: `${coverX}% ${coverY}%` }}
        />
      )}
      <div className="pinned-item-card__content">
        <div className="pinned-item-card__topline">
          <span className="pinned-item-card__type">{item.short_id ? `${item.short_id} · ` : ''}{type}</span>
          {meta && <span className="pinned-item-card__meta">{meta}</span>}
        </div>
        <strong className="pinned-item-card__title">{title}</strong>

        {type === 'event' && (
          <div className="pinned-event-details">
            {detail.location && <span>{detail.location}</span>}
            {(detail.yes_count || detail.maybe_count || detail.no_count) !== undefined && (
              <span>{detail.yes_count || 0} yes · {detail.maybe_count || 0} maybe · {detail.no_count || 0} no</span>
            )}
          </div>
        )}

        {type === 'poll' && pollOptions.length > 0 && (
          <div className="pinned-poll-options">
            {pollOptions.slice(0, 4).map((option) => {
              const votes = option.vote_count || 0;
              const pct = totalVotes ? Math.round((votes / totalVotes) * 100) : 0;
              return (
                <span key={option.id || option.label} className="pinned-poll-option">
                  <span className="pinned-poll-option__fill" style={{ width: `${pct}%` }} />
                  <span className="pinned-poll-option__label">{option.label}</span>
                  <strong>{votes}</strong>
                </span>
              );
            })}
          </div>
        )}

        {body && <p>{body}</p>}
        {tags.length > 0 && (
          <span className="pinned-item-card__tags">
            {tags.slice(0, 3).map((tag) => <em key={tag}>#{tag}</em>)}
          </span>
        )}
      </div>
    </button>
  );
};

const GroupInfoPanel = ({ open, onlineUsers, pinnedItems, loading, onClose, onNavigate }) => {
  if (!open) return null;
  return (
    <div className="chat-info-panel-backdrop" role="presentation" onClick={onClose}>
      <aside
        className="chat-info-panel"
        role="dialog"
        aria-modal="true"
        aria-label="Group info"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="chat-info-panel__header">
          <div>
            <h2>Group info</h2>
            <p>{onlineUsers.length} online now</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close group info">×</button>
        </div>

        <section className="chat-info-panel__section">
          <h3>Online</h3>
          {onlineUsers.length > 0 ? (
            <div className="chat-info-panel__chips">
              {onlineUsers.slice(0, 8).map((member) => (
                <span key={member.session_id || member.nickname} className="chat-info-panel__chip">
                  {member.nickname || 'Friend'}
                </span>
              ))}
            </div>
          ) : (
            <p className="chat-info-panel__empty">No one else is online right now.</p>
          )}
        </section>

        <section className="chat-info-panel__section">
          <h3>Pinned items</h3>
          {loading ? (
            <p className="chat-info-panel__empty">Loading pinned items…</p>
          ) : pinnedItems.length > 0 ? (
            <div className="chat-info-panel__list">
              {pinnedItems.slice(0, 5).map((item) => (
                <PinnedItemCard
                  key={item.id}
                  item={item}
                  onOpen={() => {
                    onClose();
                    onNavigate(getPinnedItemRoute(item));
                  }}
                />
              ))}
            </div>
          ) : (
            <p className="chat-info-panel__empty">No pinned items yet.</p>
          )}
        </section>
      </aside>
    </div>
  );
};

const ChatSettingsModal = ({
  open,
  chatTextSize,
  bubbleSpacing,
  bubbleColor,
  chatBackground,
  themeColours,
  quickEmojis,
  stickyInput,
  onTextSizeChange,
  onBubbleSpacingChange,
  onBubbleColorChange,
  onChatBackgroundChange,
  onQuickEmojisChange,
  onStickyInputChange,
  onClose,
}) => {
  const [editingSlotIdx, setEditingSlotIdx] = React.useState(null);
  const [themePickerOpen, setThemePickerOpen] = React.useState(false);
  const { themeId, themes, setThemeId } = useTheme();
  const activeTheme = themes.find((t) => t.id === themeId);
  const background = normaliseChatBackgroundSettings(chatBackground);
  const colourPresets = Array.from(new Set([
    themeColours.surfaceAlt,
    themeColours.background,
    themeColours.botMessage,
    themeColours.surface,
    ...CHAT_BACKGROUND_COLOUR_PRESETS,
  ].filter(Boolean))).slice(0, 8);
  const patternColourPresets = Array.from(new Set([
    themeColours.text,
    themeColours.primary,
    themeColours.accent,
    ...CHAT_BACKGROUND_PATTERN_COLOURS,
  ].filter(Boolean))).slice(0, 8);
  const updateBackground = (patch) => {
    onChatBackgroundChange(normaliseChatBackgroundSettings({
      ...background,
      ...patch,
      pattern: { ...background.pattern, ...(patch.pattern || {}) },
      gradient: { ...background.gradient, ...(patch.gradient || {}) },
    }));
  };
  useEffect(() => {
    if (!open) return undefined;
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="chat-settings-backdrop" role="presentation" onClick={onClose}>
      <aside
        className="chat-settings-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="chat-settings-title"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="chat-settings-sticky-top">
          <div className="chat-settings-modal__header">
            <div>
              <h2 id="chat-settings-title">Chat settings</h2>
              <p>Adjust how messages look on this device.</p>
            </div>
            <button type="button" className="chat-settings-modal__close" onClick={onClose} aria-label="Close chat settings">×</button>
          </div>

          <div className="chat-settings-preview-sticky">
            <div
              className="chat-background-preview"
              aria-hidden="true"
              style={{
                '--preview-font-size': (CHAT_TEXT_SIZE_OPTIONS[chatTextSize] || CHAT_TEXT_SIZE_OPTIONS.medium).value,
                '--preview-gap': (CHAT_BUBBLE_SPACING_OPTIONS[bubbleSpacing] || CHAT_BUBBLE_SPACING_OPTIONS.normal).value,
              }}
            >
              <div className="chat-background-preview__layer" style={getChatBackgroundStyle(background)} />
              <div className="chat-background-preview__bubble chat-background-preview__bubble--in">Looks good?</div>
              <div
                className="chat-background-preview__bubble chat-background-preview__bubble--out"
                style={{ background: CHAT_BUBBLE_COLOR_OPTIONS[bubbleColor]?.value }}
              >
                Readable, and sized to match your chat.
              </div>
            </div>
          </div>
        </div>

        <section className="chat-settings-section">
          <button
            type="button"
            className="chat-settings-collapse-toggle"
            onClick={() => setThemePickerOpen((open) => !open)}
            aria-expanded={themePickerOpen}
            aria-controls="chat-settings-theme-grid"
          >
            <span className="chat-settings-collapse-toggle__label">
              <h3>Theme</h3>
              {!themePickerOpen && activeTheme && (
                <span className="chat-settings-collapse-toggle__value">{activeTheme.name}</span>
              )}
            </span>
            <span className="chat-settings-collapse-toggle__chevron" aria-hidden="true">
              {themePickerOpen ? '▴' : '▾'}
            </span>
          </button>
          {themePickerOpen && (
            <>
              <p className="chat-settings-hint">Applies across the whole app on this device.</p>
              <div
                id="chat-settings-theme-grid"
                className="chat-settings-theme-grid theme-picker-grid"
                role="radiogroup"
                aria-label="Theme"
              >
                {themes.map((themeOption) => (
                  <button
                    key={themeOption.id}
                    type="button"
                    className={`theme-option${themeOption.id === themeId ? ' is-selected' : ''}`}
                    onClick={() => setThemeId(themeOption.id)}
                    role="radio"
                    aria-checked={themeOption.id === themeId}
                  >
                    <span className="theme-option__preview" aria-hidden="true">
                      <span style={{ background: themeOption.colours.background }} />
                      <span style={{ background: themeOption.colours.primary }} />
                      <span style={{ background: themeOption.colours.accent }} />
                    </span>
                    <span className="theme-option__body">
                      <strong>{themeOption.name}</strong>
                      <span>{themeOption.description}</span>
                    </span>
                  </button>
                ))}
              </div>
            </>
          )}
        </section>

        <section className="chat-settings-section">
          <h3>Text size</h3>
          <div className="chat-settings-segmented" role="radiogroup" aria-label="Chat text size">
            {Object.entries(CHAT_TEXT_SIZE_OPTIONS).map(([value, option]) => (
              <button
                key={value}
                type="button"
                className={chatTextSize === value ? 'active' : ''}
                onClick={() => onTextSizeChange(value)}
                role="radio"
                aria-checked={chatTextSize === value}
              >
                {option.label}
              </button>
            ))}
          </div>
        </section>

        <section className="chat-settings-section">
          <h3>Input bar</h3>
          <label className="chat-settings-checkbox">
            <input
              type="checkbox"
              checked={!!stickyInput}
              onChange={(event) => onStickyInputChange(event.target.checked)}
            />
            <span className="chat-settings-checkbox__body">
              <span className="chat-settings-checkbox__label">Sticky input bar</span>
              <span className="chat-settings-checkbox__hint">Keep the message bar visible while scrolling (don’t hide on swipe).</span>
            </span>
          </label>
        </section>

        <section className="chat-settings-section">
          <h3>Bubble spacing</h3>
          <div className="chat-settings-segmented" role="radiogroup" aria-label="Vertical space between bubbles">
            {Object.entries(CHAT_BUBBLE_SPACING_OPTIONS).map(([value, option]) => (
              <button
                key={value}
                type="button"
                className={bubbleSpacing === value ? 'active' : ''}
                onClick={() => onBubbleSpacingChange(value)}
                role="radio"
                aria-checked={bubbleSpacing === value}
              >
                {option.label}
              </button>
            ))}
          </div>
        </section>

        <section className="chat-settings-section">
          <h3>Your bubble colour</h3>
          <div className="chat-settings-swatches" role="radiogroup" aria-label="Your chat bubble colour">
            {Object.entries(CHAT_BUBBLE_COLOR_OPTIONS).map(([value, option]) => (
              <button
                key={value}
                type="button"
                className={bubbleColor === value ? 'active' : ''}
                onClick={() => onBubbleColorChange(value)}
                role="radio"
                aria-checked={bubbleColor === value}
                aria-label={option.label}
                title={option.label}
                style={{ '--swatch-color': option.value }}
              />
            ))}
          </div>
        </section>

        <section className="chat-settings-section chat-background-settings">
          <h3>Chat background</h3>
          <div className="chat-settings-segmented chat-background-mode" role="radiogroup" aria-label="Chat background mode">
            {Object.entries(CHAT_BACKGROUND_MODES).map(([value, label]) => (
              <button
                key={value}
                type="button"
                className={background.mode === value ? 'active' : ''}
                onClick={() => updateBackground({ mode: value })}
                role="radio"
                aria-checked={background.mode === value}
              >
                {label}
              </button>
            ))}
          </div>

          {background.mode === 'colour' && (
            <div className="chat-background-control">
              <div className="chat-settings-swatches chat-settings-swatches--compact" role="radiogroup" aria-label="Chat background colour">
                {colourPresets.map((colour) => (
                  <button
                    key={colour}
                    type="button"
                    className={background.colour === colour ? 'active' : ''}
                    onClick={() => updateBackground({ colour })}
                    role="radio"
                    aria-checked={background.colour === colour}
                    aria-label={`Use ${colour} background`}
                    title={colour}
                    style={{ '--swatch-color': colour }}
                  />
                ))}
              </div>
            </div>
          )}

          {background.mode === 'gradient' && (
            <div className="chat-background-gradient-grid" role="radiogroup" aria-label="Chat background gradient">
              {CHAT_BACKGROUND_GRADIENT_PRESETS.map((gradient) => {
                const selected = background.gradient.from === gradient.from && background.gradient.to === gradient.to;
                return (
                  <button
                    key={gradient.label}
                    type="button"
                    className={selected ? 'active' : ''}
                    onClick={() => updateBackground({ gradient: { from: gradient.from, to: gradient.to } })}
                    role="radio"
                    aria-checked={selected}
                    aria-label={gradient.label}
                    title={gradient.label}
                    style={{ '--gradient-from': gradient.from, '--gradient-to': gradient.to }}
                  />
                );
              })}
            </div>
          )}

          {background.mode === 'pattern' && (
            <div className="chat-background-control">
              <div className="chat-pattern-preset-grid" role="radiogroup" aria-label="Chat background pattern">
                {Object.entries(CHAT_BACKGROUND_PATTERN_PRESETS).map(([id, option]) => (
                  <button
                    key={id}
                    type="button"
                    className={background.pattern.id === id ? 'active' : ''}
                    onClick={() => updateBackground({ pattern: { id } })}
                    role="radio"
                    aria-checked={background.pattern.id === id}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
              <label className="chat-settings-range">
                <span>Opacity</span>
                <input
                  type="range"
                  min="0"
                  max={CHAT_PATTERN_MAX_OPACITY}
                  step="0.01"
                  value={background.pattern.opacity}
                  onChange={(event) => updateBackground({ pattern: { opacity: event.target.value } })}
                />
                <strong>{Math.round(background.pattern.opacity * 100)}%</strong>
              </label>
              <label className="chat-settings-range">
                <span>Scale</span>
                <input
                  type="range"
                  min="0.75"
                  max="2"
                  step="0.05"
                  value={background.pattern.scale}
                  onChange={(event) => updateBackground({ pattern: { scale: event.target.value } })}
                />
                <strong>{background.pattern.scale.toFixed(2)}x</strong>
              </label>
              <div className="chat-settings-swatches chat-settings-swatches--compact" role="radiogroup" aria-label="Chat pattern colour">
                {patternColourPresets.map((colour) => (
                  <button
                    key={colour}
                    type="button"
                    className={background.pattern.colour === colour ? 'active' : ''}
                    onClick={() => updateBackground({ pattern: { colour } })}
                    role="radio"
                    aria-checked={background.pattern.colour === colour}
                    aria-label={`Use ${colour} pattern colour`}
                    title={colour}
                    style={{ '--swatch-color': colour }}
                  />
                ))}
              </div>
            </div>
          )}

        </section>

        <section className="chat-settings-section">
          <h3>Quick reactions</h3>
          <p className="chat-settings-hint">Tap a slot to change that emoji.</p>
          <div className="chat-settings-quick-emojis">
            {quickEmojis.map((emoji, idx) => (
              <button
                key={idx}
                type="button"
                className={`quick-emoji-slot${editingSlotIdx === idx ? ' editing' : ''}`}
                onClick={() => setEditingSlotIdx(editingSlotIdx === idx ? null : idx)}
                aria-label={`Quick reaction slot ${idx + 1}: ${emoji}`}
              >
                {emoji}
              </button>
            ))}
          </div>
          {editingSlotIdx !== null && (
            <div className="quick-emoji-edit-grid">
              {['😀','😂','😍','😭','😤','🥰','😎','🤔','😅','🤩','😬','🥺','😱','🙃','😴','🤗','😡','🥲',
                '👍','👎','❤️','🔥','🎉','💯','✅','❌','🙏','👏','💪','🤝','👀','💀','🫶','😮','🎊','🌟','💥'].map((e) => (
                <button
                  key={e}
                  type="button"
                  className="quick-emoji-option"
                  onClick={() => {
                    const next = [...quickEmojis];
                    next[editingSlotIdx] = e;
                    onQuickEmojisChange(next);
                    setEditingSlotIdx(null);
                  }}
                >
                  {e}
                </button>
              ))}
            </div>
          )}
        </section>
      </aside>
    </div>
  );
};

const Chat = ({ targetMessageId = null, highlightedMessageIds = [], draftMessage = '' }) => {
  const { theme } = useTheme();
  const { user } = useAuth();
  const isAdmin = !!(user?.is_admin || user?.is_owner);
  const [replyTo, setReplyTo]               = useState(null);
  const [editingMessage, setEditingMessage] = useState(null);
  const [photoUploadError, setPhotoUploadError] = useState(null);
  const [openPhoto, setOpenPhoto] = useState(null);
  const [isAgendaOpen, setIsAgendaOpen] = useState(false);
  const [liveBannerOpen, setLiveBannerOpen] = useState(false);
  const [onlineMembersOpen, setOnlineMembersOpen] = useState(false);
  const [roomOverviewOpen, setRoomOverviewOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [roomName, setRoomName] = useState('');
  const [members, setMembers] = useState([]);
  const [membersLoading, setMembersLoading] = useState(false);
  const [membersError, setMembersError] = useState('');
  const [latestToastMessage, setLatestToastMessage] = useState(null);
  const [groupInfoOpen, setGroupInfoOpen] = useState(false);
  const [chatSettingsOpen, setChatSettingsOpen] = useState(false);
  const [pinnedItems, setPinnedItems] = useState([]);
  const [groupNotice, setGroupNotice] = useState('');
  const [isLoadingGroupInfo, setIsLoadingGroupInfo] = useState(false);
  const [chatTextSize, setChatTextSize] = useState(() => (
    getStoredOption(CHAT_TEXT_SIZE_KEY, CHAT_TEXT_SIZE_OPTIONS, 'medium')
  ));
  const [bubbleSpacing, setBubbleSpacing] = useState(() => (
    getStoredOption(CHAT_BUBBLE_SPACING_KEY, CHAT_BUBBLE_SPACING_OPTIONS, 'normal')
  ));
  const [bubbleColor, setBubbleColor] = useState(() => (
    getStoredOption(CHAT_BUBBLE_COLOR_KEY, CHAT_BUBBLE_COLOR_OPTIONS, 'slate')
  ));
  const [chatBackground, setChatBackground] = useState(getStoredChatBackground);
  const [quickEmojis, setQuickEmojis] = useState(() => {
    try {
      const stored = JSON.parse(window.localStorage.getItem(CHAT_QUICK_EMOJIS_KEY));
      if (Array.isArray(stored) && stored.length === 6) return stored;
    } catch {}
    return DEFAULT_QUICK_EMOJIS;
  });
  const [stickyInput, setStickyInput] = useState(() => (
    window.localStorage.getItem(CHAT_STICKY_INPUT_KEY) === 'true'
  ));
  const previousLastMessageIdRef = useRef(null);
  const toastTimerRef = useRef(null);

  const {
    isConnected,
    isConnecting,
    isLoadingHistory,
    isLoadingOlder,
    hasOlderMessages,
    messages,
    sessionId,
    connectionError,
    onlineUsers,
    typingUsers,
    connect,
    disconnect,
    sendMessage,
    sendTyping,
    sendStopTyping,
    loadOlderMessages,
    toggleReaction,
    deleteMessage,
    editMessage,
    updateMessageReactions,
    updateMessagePinned,
  } = useWebSocket();

  useEffect(() => {
    connect(targetMessageId);
    return () => disconnect();
  }, [connect, disconnect, targetMessageId]);

  useEffect(() => () => clearTimeout(toastTimerRef.current), []);

  useEffect(() => {
    if (!onlineMembersOpen) return undefined;
    let cancelled = false;
    setMembersLoading(true);
    setMembersError('');
    fetchMembers()
      .then((data) => {
        if (!cancelled) setMembers(data.members || []);
      })
      .catch((err) => {
        if (!cancelled) {
          setMembers([]);
          setMembersError(err.message || 'Failed to load members');
        }
      })
      .finally(() => {
        if (!cancelled) setMembersLoading(false);
      });
    return () => { cancelled = true; };
  }, [onlineMembersOpen]);

  useEffect(() => {
    const option = CHAT_TEXT_SIZE_OPTIONS[chatTextSize] ? chatTextSize : 'medium';
    window.localStorage.setItem(CHAT_TEXT_SIZE_KEY, option);
  }, [chatTextSize]);

  useEffect(() => {
    const option = CHAT_BUBBLE_SPACING_OPTIONS[bubbleSpacing] ? bubbleSpacing : 'normal';
    window.localStorage.setItem(CHAT_BUBBLE_SPACING_KEY, option);
  }, [bubbleSpacing]);

  useEffect(() => {
    const option = CHAT_BUBBLE_COLOR_OPTIONS[bubbleColor] ? bubbleColor : 'slate';
    window.localStorage.setItem(CHAT_BUBBLE_COLOR_KEY, option);
  }, [bubbleColor]);

  useEffect(() => {
    window.localStorage.setItem(CHAT_BACKGROUND_KEY, JSON.stringify(normaliseChatBackgroundSettings(chatBackground)));
  }, [chatBackground]);

  useEffect(() => {
    window.localStorage.setItem(CHAT_QUICK_EMOJIS_KEY, JSON.stringify(quickEmojis));
  }, [quickEmojis]);

  useEffect(() => {
    window.localStorage.setItem(CHAT_STICKY_INPUT_KEY, String(stickyInput));
    // When the input is pinned, ensure any in-progress hidden state is cleared.
    if (stickyInput) {
      document.body.classList.remove('mobile-nav-hidden');
    }
  }, [stickyInput]);

  useEffect(() => () => {
    document.body.classList.remove('mobile-nav-hidden');
  }, []);

  useEffect(() => {
    const setVisualViewportHeight = () => {
      const height = window.visualViewport?.height || window.innerHeight;
      document.documentElement.style.setProperty('--visual-viewport-height', `${height}px`);
    };

    setVisualViewportHeight();
    window.visualViewport?.addEventListener('resize', setVisualViewportHeight);
    window.visualViewport?.addEventListener('scroll', setVisualViewportHeight);
    window.addEventListener('resize', setVisualViewportHeight);

    return () => {
      window.visualViewport?.removeEventListener('resize', setVisualViewportHeight);
      window.visualViewport?.removeEventListener('scroll', setVisualViewportHeight);
      window.removeEventListener('resize', setVisualViewportHeight);
      document.documentElement.style.removeProperty('--visual-viewport-height');
    };
  }, []);

  useEffect(() => {
    const lastMessage = messages[messages.length - 1];

    if (!lastMessage) {
      previousLastMessageIdRef.current = null;
      setLatestToastMessage(null);
      return;
    }

    const previousLastMessageId = previousLastMessageIdRef.current;
    previousLastMessageIdRef.current = lastMessage.id;

    if (
      isLoadingHistory ||
      isLoadingOlder ||
      lastMessage.id === previousLastMessageId ||
      lastMessage.type !== 'chat' ||
      !lastMessage.isLive ||
      lastMessage.isMe
    ) {
      return;
    }

    setLatestToastMessage(lastMessage);
    clearTimeout(toastTimerRef.current);
    toastTimerRef.current = setTimeout(() => {
      setLatestToastMessage(null);
    }, 3600);
  }, [messages, isLoadingHistory, isLoadingOlder]);

  const handleReconnect = () => connect();

  const handleReply = (messageId, content, nickname) => {
    setReplyTo({ id: messageId, content, nickname });
  };

  const handleClearReply = () => setReplyTo(null);

  const handleToggleReaction = (messageId, emoji) => toggleReaction(messageId, emoji);

  const handleDeleteMessage = (messageId) => deleteMessage(messageId);

  const handlePinMessage = async (messageId, nextPinned) => {
    // Optimistic; revert on failure.
    updateMessagePinned(messageId, nextPinned);
    try {
      await pinMessage(messageId, nextPinned);
    } catch (err) {
      updateMessagePinned(messageId, !nextPinned);
      console.error('Pin failed:', err);
    }
  };

  const handleEditMessage = (msg) => {
    setEditingMessage({ id: msg.id, content: msg.content });
    setReplyTo(null);
  };

  const handleCancelEdit = () => setEditingMessage(null);

  const handleUploadPhoto = async (file) => {
    try {
      setPhotoUploadError(null);
      const data = await uploadPhoto(file);
      const photo = data.photo;
      if (!photo?.url) {
        setPhotoUploadError('Upload returned no photo URL');
        return;
      }
      const message = `Photo: ${photo.original_filename || file.name}\n${photo.url}`;
      console.log('Uploading photo - sending message:', { filename: photo.original_filename, url: photo.url, fullMessage: message });
      sendMessage(message);
    } catch (err) {
      setPhotoUploadError(err.message);
      console.error('Photo upload error:', err);
    }
  };

  const handleSendGif = (gif) => {
    if (!gif?.url) return;
    const label = (gif.title || 'GIF').replace(/\s+/g, ' ').trim();
    sendMessage(`GIF: ${label}\n${gif.url}`);
  };

  const handleOpenPhoto = (photo) => {
    setOpenPhoto({ ...photo, showSeeInPhotos: true });
  };

  const handleSummarise = () => {
    sendMessage('/summarise past 24 hours');
  };

  const handleDismissToast = () => {
    clearTimeout(toastTimerRef.current);
    const msg = latestToastMessage;
    if (msg?.content?.startsWith('Photo: ')) {
      const lines = msg.content.split('\n');
      if (lines.length >= 2) {
        const url = lines[1].trim();
        if (url.startsWith('/uploads/photos/')) {
          const label = lines[0].replace('Photo: ', '').trim() || 'Shared photo';
          setOpenPhoto({ url, label, showSeeInPhotos: true });
          setLatestToastMessage(null);
          return;
        }
      }
    }
    setLatestToastMessage(null);
  };

  const openGroupInfo = async () => {
    setGroupInfoOpen(true);
    if (isLoadingGroupInfo) return;
    setIsLoadingGroupInfo(true);
    try {
      const [dashboard, eventsData, pollsData, noticeData] = await Promise.all([
        fetchDashboard(),
        fetchEvents().catch(() => ({ events: [] })),
        fetchPolls().catch(() => ({ polls: [] })),
        fetchGroupNotice().catch(() => ({ notice: '' })),
      ]);
      setPinnedItems(enrichPinnedItems(
        dashboard?.pinned_items || [],
        eventsData?.events || [],
        pollsData?.polls || [],
      ));
      setGroupNotice(dashboard?.group_notice || noticeData?.notice || '');
    } catch {
      setPinnedItems([]);
    } finally {
      setIsLoadingGroupInfo(false);
    }
  };

  const handleMobileNavVisibility = useCallback((hidden) => {
    // When the input bar is pinned, never hide on swipe.
    document.body.classList.toggle('mobile-nav-hidden', hidden && !stickyInput);
  }, [stickyInput]);

  const statusText  = isConnecting     ? 'Connecting…'
    : connectionError                  ? connectionError
    : isConnected                      ? 'Online'
    : 'Offline';

  const inputPlaceholder = isLoadingHistory ? 'Loading…'
    : isConnecting                          ? 'Connecting…'
    : !isConnected                          ? 'Not connected…'
    : 'Type a message…';

  const selectedTextSize = CHAT_TEXT_SIZE_OPTIONS[chatTextSize] || CHAT_TEXT_SIZE_OPTIONS.medium;
  const selectedBubbleSpacing = CHAT_BUBBLE_SPACING_OPTIONS[bubbleSpacing] || CHAT_BUBBLE_SPACING_OPTIONS.normal;
  const selectedBubbleColor = CHAT_BUBBLE_COLOR_OPTIONS[bubbleColor] || CHAT_BUBBLE_COLOR_OPTIONS.slate;
  const selectedChatBackground = normaliseChatBackgroundSettings(chatBackground);
  const onlineSessionIds = new Set(onlineUsers.map((user) => user.session_id).filter(Boolean));
  const visibleMembers = members
    .filter((member) => !member.invite_pending)
    .map((member) => ({
      ...member,
      is_online: onlineSessionIds.has(member.session_id) || !!member.is_online,
    }));

  return (
    <div
      className={[
        'chat-wrapper',
        `chat-text-${CHAT_TEXT_SIZE_OPTIONS[chatTextSize] ? chatTextSize : 'medium'}`,
        `chat-spacing-${CHAT_BUBBLE_SPACING_OPTIONS[bubbleSpacing] ? bubbleSpacing : 'normal'}`,
      ].join(' ')}
      style={{
        '--chat-message-font-size': selectedTextSize.value,
        '--chat-bubble-spacing': selectedBubbleSpacing.value,
        '--chat-own-message-color': selectedBubbleColor.value,
        '--chat-own-message-text-color': selectedBubbleColor.text,
      }}
    >

      {/* ── Main chat column ── */}
      <div className="chat-container">
        <ChatMessageToast
          key={latestToastMessage?.id || 'empty-toast'}
          message={latestToastMessage}
          onClick={handleDismissToast}
        />

        <div className="chat-header">
          <div className="chat-header__room">
            <RoomTitleButton
              onOpenOverview={() => setRoomOverviewOpen(true)}
              onResolveName={setRoomName}
            />
            <p className="chat-header__subtitle">
              {onlineUsers.length > 0
                ? `${onlineUsers.length} live`
                : statusText}
            </p>
          </div>
          <div className="connection-status">
            <div className="header-buttons">
              <LiveStatusIndicator
                onToggle={() => setLiveBannerOpen(v => !v)}
                isExpanded={liveBannerOpen}
                onLiveChange={(isLive) => {
                  if (!isLive) setLiveBannerOpen(false);
                }}
              />
              <button
                type="button"
                className="chat-help-btn"
                onClick={() => setHelpOpen(true)}
                aria-label="What you can do here"
                title="Help"
              >
                <span aria-hidden="true">?</span>
              </button>
              <button
                type="button"
                className="chat-agenda-btn"
                onClick={() => setIsAgendaOpen(true)}
                title="Schedule a council motion"
              >
                <span aria-hidden="true">⚖️</span> Agenda
              </button>
              {!isConnected && !isConnecting && (
                <button onClick={handleReconnect} className="reconnect-btn">
                  Reconnect
                </button>
              )}
            </div>
          </div>
        </div>

        {isLoadingHistory && (
          <div className="loading-bar">Loading history…</div>
        )}

        {photoUploadError && (
          <div className="loading-bar error">{photoUploadError}</div>
        )}

        <div className={`live-banner-collapsible${liveBannerOpen ? '' : ' collapsed'}`}>
          <PinnedLiveAgendaBanner
            onNavigate={(path) => navigateTo(path)}
            onOpenPinned={openGroupInfo}
          />
        </div>

        <div className="chat-shell">
          <div className="chat-background" aria-hidden="true" style={getChatBackgroundStyle(selectedChatBackground)} />
          <MessageList
            messages={messages}
            currentSessionId={sessionId}
            onReply={handleReply}
            onToggleReaction={handleToggleReaction}
            onDeleteMessage={handleDeleteMessage}
            onEditMessage={handleEditMessage}
            onPinMessage={handlePinMessage}
            canPin={isAdmin}
            onOpenPhoto={handleOpenPhoto}
            targetMessageId={targetMessageId}
            highlightedMessageIds={highlightedMessageIds}
            hasOlderMessages={hasOlderMessages}
            isLoadingOlder={isLoadingOlder}
            loadOlderMessages={loadOlderMessages}
            onMobileNavVisibilityChange={handleMobileNavVisibility}
            quickEmojis={quickEmojis}
          />

          <TypingIndicator typingUsers={typingUsers} currentSessionId={sessionId} />
        </div>

        <MessageInput
          onSendMessage={sendMessage}
          onEditMessage={editMessage}
          initialDraft={draftMessage}
          onTyping={sendTyping}
          onStopTyping={sendStopTyping}
          onUploadPhoto={handleUploadPhoto}
          onSendGif={handleSendGif}
          onSummarise={handleSummarise}
          disabled={!isConnected || isLoadingHistory}
          placeholder={inputPlaceholder}
          replyTo={replyTo}
          onClearReply={handleClearReply}
          editingMessage={editingMessage}
          onCancelEdit={handleCancelEdit}
        />
      </div>

      {/* ── Online users sidebar ── */}
      <OnlineUsers users={onlineUsers} currentSessionId={sessionId} />

      <PhotoModal photo={openPhoto} onClose={() => setOpenPhoto(null)} />

      <ChatSettingsModal
        open={chatSettingsOpen}
        chatTextSize={CHAT_TEXT_SIZE_OPTIONS[chatTextSize] ? chatTextSize : 'medium'}
        bubbleSpacing={CHAT_BUBBLE_SPACING_OPTIONS[bubbleSpacing] ? bubbleSpacing : 'normal'}
        bubbleColor={CHAT_BUBBLE_COLOR_OPTIONS[bubbleColor] ? bubbleColor : 'slate'}
        chatBackground={selectedChatBackground}
        themeColours={theme.colours}
        quickEmojis={quickEmojis}
        stickyInput={stickyInput}
        onTextSizeChange={setChatTextSize}
        onBubbleSpacingChange={setBubbleSpacing}
        onBubbleColorChange={setBubbleColor}
        onChatBackgroundChange={setChatBackground}
        onQuickEmojisChange={setQuickEmojis}
        onStickyInputChange={setStickyInput}
        onClose={() => setChatSettingsOpen(false)}
      />

      {isAgendaOpen && (
        <AgendaModal onClose={() => setIsAgendaOpen(false)} />
      )}

      <GroupNoticeboard
        open={groupInfoOpen}
        onlineUsers={onlineUsers}
        pinnedItems={pinnedItems}
        loading={isLoadingGroupInfo}
        groupNotice={groupNotice}
        onNoticeChange={setGroupNotice}
        onClose={() => setGroupInfoOpen(false)}
      />

      {onlineMembersOpen && (
        <OnlineMembersModal
          users={visibleMembers}
          loading={membersLoading}
          error={membersError}
          onlineCount={onlineUsers.length}
          currentSessionId={sessionId}
          onNavigate={(path) => navigateTo(path)}
          onClose={() => setOnlineMembersOpen(false)}
        />
      )}

      <RoomOverview
        open={roomOverviewOpen}
        roomName={roomName}
        onlineUsers={onlineUsers}
        currentSessionId={sessionId}
        onClose={() => setRoomOverviewOpen(false)}
        onNavigate={(path) => navigateTo(path)}
        onOpenPhoto={(photo) => setOpenPhoto(photo)}
        onOpenSearch={() => navigateTo('/search')}
        onOpenHelp={() => setHelpOpen(true)}
        onOpenPinned={openGroupInfo}
        onOpenChatSettings={() => setChatSettingsOpen(true)}
      />

      <ChatHelpModal open={helpOpen} onClose={() => setHelpOpen(false)} />

    </div>
  );
};

export default Chat;
