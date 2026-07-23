import React, { useEffect, useState } from 'react';
import { fetchDashboard, fetchHomeAppearance, fetchMessages } from '../services/api.js';
import UserAvatar from '../components/Chat/UserAvatar.jsx';
import HomeAppearanceModal from '../components/Home/HomeAppearanceModal.jsx';
import GroupNoticeboard from '../components/Chat/GroupNoticeboard.jsx';
import RecentActivityFeed from '../components/Home/ActivityFeed.jsx';
import { enablePushNotifications, pushSupported, unsupportedReason } from '../push/notifications.js';
import { canPromptInstall, isIOS, isStandalone, promptInstall, subscribeInstall } from '../pwa/install.js';
import './FeaturePages.css';

const HELP_SEEN_STORAGE_KEY = 'friendHubHelpSeen';

const itemRoutes = {
  idea: '/ideas',
  poll: '/polls',
  event: '/events',
  reminder: '/reminders',
  note: '/notes',
};

function formatShortDate(value) {
  if (!value) return null;
  return new Date(value).toLocaleString([], {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function getItemTitle(item, fallback = 'Untitled') {
  return item.title || item.question || item.text || fallback;
}

function getItemType(item, fallbackType) {
  return item.hub_item?.type || item.type || fallbackType;
}

function getItemShortId(item) {
  return item.hub_item?.short_id || item.short_id;
}

function getItemTags(item) {
  return item.hub_item?.tags || item.tags || [];
}

function getItemRoute(item, type) {
  const itemType = getItemType(item, type);
  if (itemType === 'event') {
    const eventId = item.source_id || item.hub_item?.source_id || item.id;
    return eventId ? `/events/${eventId}` : '/events';
  }
  if (itemType === 'note') {
    const noteId = item.source_id || item.hub_item?.source_id || item.id;
    return noteId ? `/notes/${noteId}` : '/notes';
  }
  return itemRoutes[itemType] || '/home';
}

function getItemMeta(item, type) {
  const date = formatShortDate(item.due_at || item.starts_at || item.event_start_at || item.deadline_at);
  if (type === 'reminder') {
    const assignees = item.assignees?.map((user) => user.nickname).filter(Boolean).join(', ');
    return [date ? `Due ${date}` : 'No due date', assignees].filter(Boolean).join(' · ');
  }
  if (type === 'event') return date ? `Starts ${date}` : 'No date set';
  if (type === 'poll') {
    const optionCount = item.options?.length || 0;
    return [date ? `Closes ${date}` : null, `${optionCount} option${optionCount === 1 ? '' : 's'}`].filter(Boolean).join(' · ');
  }
  return item.status || null;
}

// ── Activity grouping helpers ────────────────────────────────────────────────

const ACTIVITY_PREFIXES = { idea: 'I', poll: 'P', reminder: 'R', event: 'E', hub_item: 'H', note: 'N', message: '💬' };
const ACTIVITY_LABELS   = { idea: 'Idea', poll: 'Poll', reminder: 'Reminder', event: 'Event', hub_item: 'Item', message: 'Chat', note: 'Note' };
const ACTIVITY_BG       = { idea: '#fef9c3', poll: '#dbeafe', reminder: '#fce7f3', event: '#d1fae5', hub_item: '#eef2ff', message: '#f0f4f8' };
const ACTIVITY_COLOR    = { idea: '#854d0e', poll: '#1e40af', reminder: '#9d174d', event: '#065f46', hub_item: '#667eea', message: '#415066' };

function getActivityGroupRoute(group) {
  if (group.target_type === 'event')    return `/events/${group.target_id}`;
  if (group.target_type === 'idea')     return '/ideas';
  if (group.target_type === 'poll')     return '/polls';
  if (group.target_type === 'reminder') return '/reminders';
  if (group.target_type === 'note')     return `/notes/${group.target_id}`;
  if (group.target_type === 'hub_item') return '/items';
  if (group.target_type === 'message')  return '/chat';
  return '/home';
}

function extractActivityTargetName(activities) {
  for (const a of activities) {
    const m = a.summary?.match(/:\s*(.{1,80})$/);
    if (m) return m[1].trim();
  }
  return null;
}

function groupActivities(activities) {
  const map = new Map();
  for (const a of activities) {
    const key = `${a.target_type}::${a.target_id ?? 'none'}`;
    if (!map.has(key)) {
      map.set(key, { key, target_type: a.target_type, target_id: a.target_id, activities: [], latest_at: a.created_at });
    }
    const g = map.get(key);
    g.activities.push(a);
    if (a.created_at > g.latest_at) g.latest_at = a.created_at;
  }
  return [...map.values()].sort((a, b) => new Date(b.latest_at) - new Date(a.latest_at));
}

function buildActivityLine(activities) {
  const byActor = new Map();
  for (const a of activities) {
    const nick = a.actor?.nickname || 'Someone';
    if (!byActor.has(nick)) byActor.set(nick, {});
    const acts = byActor.get(nick);
    acts[a.action] = (acts[a.action] || 0) + 1;
  }
  return [...byActor.entries()]
    .map(([nick, acts]) => {
      const parts = Object.entries(acts).map(([act, n]) => n > 1 ? `${act} ×${n}` : act);
      return `${nick}: ${parts.join(', ')}`;
    })
    .join(' · ');
}

const ActivityGroupCard = ({ group, onNavigate, formatTime }) => {
  const prefix  = ACTIVITY_PREFIXES[group.target_type];
  const shortId = prefix && group.target_id && prefix !== '💬'
    ? `#${prefix}-${group.target_id}`
    : ACTIVITY_LABELS[group.target_type] || group.target_type;
  const name    = extractActivityTargetName(group.activities);
  const bg      = ACTIVITY_BG[group.target_type]    || '#f0f4f8';
  const color   = ACTIVITY_COLOR[group.target_type] || '#415066';
  const uniqueActors = [...new Map(
    group.activities.filter(a => a.actor).map(a => [a.actor.nickname, a.actor])
  ).values()].slice(0, 3);

  return (
    <button
      type="button"
      className="activity-group-card"
      onClick={() => onNavigate(getActivityGroupRoute(group))}
    >
      <div className="activity-group-avatars">
        {uniqueActors.map(actor => (
          <UserAvatar key={actor.nickname} nickname={actor.nickname} size={26} avatarUrl={actor.avatar_url} />
        ))}
      </div>
      <div className="activity-group-body">
        <div className="activity-group-header">
          <span className="activity-group-tag" style={{ background: bg, color }}>{shortId}</span>
          {name && <span className="activity-group-name">{name}</span>}
          <span className="activity-group-time">{formatTime(group.latest_at)}</span>
        </div>
        <p className="activity-group-line">{buildActivityLine(group.activities)}</p>
      </div>
    </button>
  );
};

const HomeHubItemCard = ({ item, type, onNavigate, compact = false }) => {
  const itemType = getItemType(item, type);
  const shortId = getItemShortId(item);
  const tags = getItemTags(item);
  const meta = getItemMeta(item, itemType);
  const body = item.body || item.description;
  const coverImage = item.cover_photo_url || item.cover_image_url;
  const detail = item.detail || item.hub_item || {};
  const coverX = detail.cover_photo_position_x ?? item.cover_photo_position_x ?? 50;
  const coverY = detail.cover_photo_position_y ?? item.cover_photo_position_y ?? 50;

  return (
    <button type="button" className={`home-hub-card${compact ? ' compact' : ''}${coverImage ? ' has-cover' : ''}`} onClick={() => onNavigate(getItemRoute(item, itemType))}>
      {coverImage && (
        <img
          className="home-hub-card__cover"
          src={coverImage}
          alt=""
          style={{ objectPosition: `${coverX}% ${coverY}%` }}
        />
      )}
      <div className="home-hub-card__content">
        <span className="home-hub-card__eyebrow">
          {shortId ? `${shortId} · ` : ''}{itemType}
        </span>
        <strong>{getItemTitle(item)}</strong>
        {meta && <span className="home-hub-card__meta">{meta}</span>}
        {!compact && body && <p>{body}</p>}
        {!compact && tags.length > 0 && (
          <span className="home-hub-card__tags">
            {tags.slice(0, 3).map((tag) => <em key={tag}>#{tag}</em>)}
          </span>
        )}
      </div>
    </button>
  );
};

const HomeItemSection = ({ title, items, type, empty, onNavigate }) => (
  <section className="dashboard-card home-item-section">
    <div className="home-item-section__header">
      <h2>{title}</h2>
      <button type="button" onClick={() => onNavigate(itemRoutes[type])}>View all</button>
    </div>
    <div className="home-hub-list">
      {items.length > 0
        ? items.map((item) => (
          <HomeHubItemCard
            key={`${type}-${item.id}`}
            item={item}
            type={type}
            onNavigate={onNavigate}
          />
        ))
        : <p className="dashboard-meta">{empty}</p>}
    </div>
  </section>
);

const HomeChatPreview = ({ messages, onNavigate, formatChatTime, getMessagePreview }) => (
  <section className="dashboard-section home-chat-section">
    <div className="section-heading">
      <h2>Latest Chat</h2>
      <button type="button" className="view-all-btn" onClick={() => onNavigate('/chat')}>Open chat</button>
    </div>
    {messages.length > 0 ? (
      <div className="chat-messages-list">
        {messages.map((msg) => (
          <button
            key={msg.id}
            type="button"
            className="chat-message-item"
            onClick={() => onNavigate('/chat')}
          >
            <UserAvatar
              nickname={msg.nickname || 'Friend'}
              size={32}
              avatarUrl={msg.avatar_url}
              avatarEmoji={msg.avatar_emoji || (msg.is_bot ? '🤖' : null)}
            />
            <div className="chat-message-body">
              <div className="chat-message-header">
                <strong>{msg.nickname || 'Friend'}</strong>
                <span className="chat-message-time">{formatChatTime(msg.created_at)}</span>
              </div>
              <p className="chat-message-text">{getMessagePreview(msg.content)}</p>
            </div>
          </button>
        ))}
      </div>
    ) : (
      <div className="placeholder-panel compact">No messages yet. Start chatting!</div>
    )}
  </section>
);

const HomeActivityPreview = ({ activity, onNavigate, formatChatTime }) => (
  <div className="activity-list">
    {activity.length > 0
      ? groupActivities(activity).map((group) => (
        <ActivityGroupCard
          key={group.key}
          group={group}
          onNavigate={onNavigate}
          formatTime={formatChatTime}
        />
      ))
      : <div className="placeholder-panel compact">No activity yet</div>}
  </div>
);

const HomeItemsPreview = ({ items, onNavigate }) => (
  <div className="home-hub-list">
    {items.length > 0
      ? items.map((item) => (
        <HomeHubItemCard key={item.id} item={item} type={item.type} onNavigate={onNavigate} compact />
      ))
      : <div className="placeholder-panel compact">No pinned items yet</div>}
  </div>
);

const HomeEventsPreview = ({ events, onNavigate }) => (
  <div className="home-hub-list">
    {events.length > 0
      ? events.map((item) => (
        <HomeHubItemCard key={`event-${item.id}`} item={item} type="event" onNavigate={onNavigate} compact />
      ))
      : <div className="placeholder-panel compact">No upcoming events</div>}
  </div>
);

const HomePollsPreview = ({ polls, onNavigate }) => (
  <div className="home-hub-list">
    {polls.length > 0
      ? polls.map((item) => (
        <HomeHubItemCard key={`poll-${item.id}`} item={item} type="poll" onNavigate={onNavigate} compact />
      ))
      : <div className="placeholder-panel compact">No active polls</div>}
  </div>
);

const NeedsAttentionSection = ({ title, items, type, empty, onNavigate, limit = 3 }) => (
  <section className="upcoming-block">
    <div className="upcoming-block-header">
      <h3 className="upcoming-block-title">{title}</h3>
      <button type="button" onClick={() => onNavigate(itemRoutes[type])}>View</button>
    </div>
    <div className="upcoming-items">
      {items.length > 0
        ? items.slice(0, limit).map((item) => (
          <HomeHubItemCard key={`${type}-${item.id}`} item={item} type={type} onNavigate={onNavigate} compact />
        ))
        : <div className="placeholder-panel compact">{empty}</div>}
    </div>
  </section>
);

const HomeMobileDashboardGrid = ({ cards, onSelect }) => (
  <div className="mobile-home-card-grid">
    {cards.map((card) => (
      <button
        key={card.id}
        type="button"
        className="mobile-home-card"
        onClick={() => onSelect(card.id)}
      >
        <span className="mobile-home-card__icon">{card.icon}</span>
        <span className="mobile-home-card__body">
          <strong>{card.title}</strong>
          <span>{card.status}</span>
          <em>{card.preview}</em>
        </span>
      </button>
    ))}
  </div>
);

const HomeMobileDetailPanel = ({ card, onBack }) => (
  <section className="mobile-home-detail-panel">
    <div className="mobile-home-detail-header">
      <button type="button" onClick={onBack} aria-label="Back to dashboard cards">‹</button>
      <span className="mobile-home-card__icon">{card.icon}</span>
      <div>
        <h2>{card.title}</h2>
        <p>{card.status}</p>
      </div>
      <button type="button" onClick={onBack} aria-label="Close detail panel">×</button>
    </div>
    <div className="mobile-home-detail-scroll">
      {card.content}
    </div>
  </section>
);

const HomeCoverHeader = ({
  appearance,
  messages,
  pinnedItems,
  groupNotice,
  onOpenSettings,
  onOpenPinned,
  onOpenHelp,
  onOpenCover,
}) => {
  const coverUrl = appearance?.cover_photo_url || null;
  const x = typeof appearance?.cover_position_x === 'number' ? appearance.cover_position_x : 50;
  const y = typeof appearance?.cover_position_y === 'number' ? appearance.cover_position_y : 50;
  const todayCount = (() => {
    const now = new Date();
    const yr = now.getFullYear(), m = now.getMonth(), d = now.getDate();
    return messages.filter((msg) => {
      if (!msg.created_at) return false;
      const dt = new Date(msg.created_at);
      return dt.getFullYear() === yr && dt.getMonth() === m && dt.getDate() === d;
    }).length;
  })();
  const subtitle = `${todayCount} message${todayCount === 1 ? '' : 's'} today`;
  const pinnedCount = pinnedItems?.length || 0;
  const firstPinned = pinnedItems?.[0];
  // Prefer the group notice message; fall back to summarising pinned items.
  const notice = (groupNotice || '').trim();
  const pinnedLabel = notice
    ? notice
    : firstPinned
      ? (pinnedCount > 1
        ? `Pinned: ${getItemTitle(firstPinned)} +${pinnedCount - 1} more`
        : `Pinned: ${getItemTitle(firstPinned)}`)
      : null;

  return (
    <header className={`home-cover-header${coverUrl ? ' has-cover' : ''}`}>
      {coverUrl && (
        <img
          className="home-cover-header__image"
          src={coverUrl}
          alt=""
          style={{ objectPosition: `${x}% ${y}%` }}
        />
      )}
      {coverUrl && onOpenCover && (
        <button
          type="button"
          className="home-cover-header__cover-trigger"
          onClick={() => onOpenCover(coverUrl)}
          aria-label="View cover image"
        />
      )}
      <div className="home-cover-header__overlay" />
      <div className="home-cover-header__content">
        <h1 className="home-cover-header__title">Friend Hub</h1>
        <p className="home-cover-header__subtitle">{subtitle}</p>
        {pinnedLabel && (
          <button
            type="button"
            className="home-cover-header__pinned"
            onClick={onOpenPinned}
            aria-label={notice ? 'Open noticeboard' : `Open pinned items (${pinnedCount})`}
          >
            <span aria-hidden="true">📌</span>
            <span className="home-cover-header__pinned-text">{pinnedLabel}</span>
          </button>
        )}
      </div>
      <div className="home-cover-header__actions">
        <button
          type="button"
          className="home-cover-header__icon-btn"
          onClick={onOpenHelp}
          aria-label="Open Friend Hub help"
        >
          <span aria-hidden="true">?</span>
        </button>
        <button
          type="button"
          className="home-cover-header__icon-btn"
          onClick={onOpenSettings}
          aria-label="Edit homepage appearance"
        >
          <span aria-hidden="true">⚙︎</span>
        </button>
      </div>
    </header>
  );
};

const helpSlides = [
  {
    eyebrow: 'Start here',
    title: 'Welcome to Friend Hub',
    body: 'Friend Hub is the home for group chat, events, polls, reminders, photos, and shared activity.',
  },
  {
    eyebrow: 'Hub Bot',
    title: 'Ask @hub',
    body: 'Mention @hub in chat to ask questions, create reminders, summarise activity, or search old messages.',
    examples: [
      '@hub summarise today',
      '@hub remind us about football Friday',
      '@hub who mentioned BBQ?',
      '@hub create a poll for Saturday plans',
    ],
  },
  {
    eyebrow: 'Find things',
    title: 'Search',
    body: 'Search helps you find old messages, polls, events, ideas, photos, and shared plans without scrolling back through chat.',
  },
  {
    eyebrow: 'Install',
    title: 'Add to Home Screen',
    body: 'Install Friend Hub like an app for quicker access. In most mobile browsers, open the browser menu and choose Add to Home Screen or Install app.',
    install: true,
  },
  {
    eyebrow: 'Stay updated',
    title: 'Notifications',
    body: 'Push notifications can send reminders, mentions, chat updates, and Hub Bot alerts to this device.',
    notification: true,
  },
];

const HelpOnboardingModal = ({ open, onClose }) => {
  const [index, setIndex] = useState(0);
  const [notificationBusy, setNotificationBusy] = useState(false);
  const [notificationMessage, setNotificationMessage] = useState('');
  const [notificationError, setNotificationError] = useState('');
  const [installAvailable, setInstallAvailable] = useState(canPromptInstall());
  const [installMessage, setInstallMessage] = useState('');

  useEffect(() => {
    if (!open) return;
    setIndex(0);
    setNotificationMessage('');
    setNotificationError('');
    setInstallMessage('');
  }, [open]);

  // Track whether a native install prompt is available (it can arrive late).
  useEffect(() => subscribeInstall((prompt) => setInstallAvailable(!!prompt)), []);

  useEffect(() => {
    if (!open) return;
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') onClose();
      if (event.key === 'ArrowRight') setIndex((current) => Math.min(helpSlides.length - 1, current + 1));
      if (event.key === 'ArrowLeft') setIndex((current) => Math.max(0, current - 1));
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  const slide = helpSlides[index];
  const isLast = index === helpSlides.length - 1;

  const handleEnableNotifications = async () => {
    setNotificationBusy(true);
    setNotificationMessage('');
    setNotificationError('');
    try {
      await enablePushNotifications();
      setNotificationMessage('Notifications are enabled for this device.');
    } catch (err) {
      setNotificationError(err.message || 'Could not enable notifications.');
    } finally {
      setNotificationBusy(false);
    }
  };

  const handleInstall = async () => {
    setInstallMessage('');
    const outcome = await promptInstall();
    if (outcome === 'accepted') {
      setInstallMessage('Installing Friend Hub…');
    } else if (outcome === 'dismissed') {
      setInstallMessage('Install cancelled — you can add it any time from your browser menu.');
    }
  };

  const finish = () => {
    onClose();
  };

  return (
    <div
      className="help-modal-backdrop"
      role="presentation"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section
        className="help-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="friend-hub-help-title"
      >
        <button
          type="button"
          className="help-modal__close"
          onClick={onClose}
          aria-label="Close help"
        >
          ×
        </button>

        <div className="help-modal__visual" aria-hidden="true">
          <span>{index + 1}</span>
        </div>

        <div className="help-modal__body">
          <span className="help-modal__eyebrow">{slide.eyebrow}</span>
          <h2 id="friend-hub-help-title">{slide.title}</h2>
          <p>{slide.body}</p>

          {slide.examples && (
            <div className="help-modal__examples" aria-label="Hub Bot example prompts">
              {slide.examples.map((example) => (
                <code key={example}>{example}</code>
              ))}
            </div>
          )}

          {slide.install && (
            <div className="help-modal__notification">
              {isStandalone() ? (
                <span className="help-modal__success">Friend Hub is already installed on this device.</span>
              ) : installAvailable ? (
                <button
                  type="button"
                  className="help-modal__primary"
                  onClick={handleInstall}
                >
                  Add to Home Screen
                </button>
              ) : isIOS() ? (
                <p>Tap the <b>Share</b> button, then <b>Add to Home Screen</b>.</p>
              ) : (
                <p>Open your browser menu and choose <b>Add to Home Screen</b> or <b>Install app</b>.</p>
              )}
              {installMessage && <span className="help-modal__success">{installMessage}</span>}
            </div>
          )}

          {slide.notification && (
            <div className="help-modal__notification">
              {pushSupported() ? (
                <button
                  type="button"
                  className="help-modal__primary"
                  onClick={handleEnableNotifications}
                  disabled={notificationBusy || Notification.permission === 'denied'}
                >
                  {notificationBusy ? 'Enabling…' : 'Enable notifications'}
                </button>
              ) : (
                <p>{unsupportedReason()}</p>
              )}
              {notificationMessage && <span className="help-modal__success">{notificationMessage}</span>}
              {notificationError && <span className="help-modal__error">{notificationError}</span>}
            </div>
          )}
        </div>

        <div className="help-modal__footer">
          <div className="help-modal__dots" aria-label={`Slide ${index + 1} of ${helpSlides.length}`}>
            {helpSlides.map((item, dotIndex) => (
              <button
                key={item.title}
                type="button"
                className={dotIndex === index ? 'is-active' : ''}
                onClick={() => setIndex(dotIndex)}
                aria-label={`Go to slide ${dotIndex + 1}: ${item.title}`}
              />
            ))}
          </div>
          <div className="help-modal__controls">
            <button
              type="button"
              className="help-modal__secondary"
              onClick={() => setIndex((current) => Math.max(0, current - 1))}
              disabled={index === 0}
            >
              Back
            </button>
            <button
              type="button"
              className="help-modal__primary"
              onClick={isLast ? finish : () => setIndex((current) => Math.min(helpSlides.length - 1, current + 1))}
            >
              {isLast ? 'Done' : 'Next'}
            </button>
          </div>
        </div>
      </section>
    </div>
  );
};

const HomeSearchStrip = ({ onNavigate }) => (
  <button
    type="button"
    className="home-search-strip"
    onClick={() => onNavigate('/search')}
    aria-label="Search"
  >
    <span className="home-search-strip__icon" aria-hidden="true">🔍</span>
    <span className="home-search-strip__label">Search events, polls, ideas…</span>
    <span className="home-search-strip__kbd" aria-hidden="true">Search</span>
  </button>
);

const MobileHomeDashboard = ({
  dashboard,
  appearance,
  messages,
  groupNotice,
  onNavigate,
  onOpenAppearance,
  onOpenPinned,
  onOpenHelp,
  onOpenCover,
  formatChatTime,
  getMessagePreview,
}) => {
  const pinnedItems = dashboard?.pinned_items || [];

  return (
    <div className="mobile-home-dashboard">
      <HomeCoverHeader
        appearance={appearance}
        messages={messages}
        pinnedItems={pinnedItems}
        groupNotice={groupNotice}
        onOpenSettings={onOpenAppearance}
        onOpenPinned={onOpenPinned}
        onOpenHelp={onOpenHelp}
        onOpenCover={onOpenCover}
      />

      <HomeChatPreview
        messages={messages}
        onNavigate={onNavigate}
        formatChatTime={formatChatTime}
        getMessagePreview={getMessagePreview}
      />

      <section className="dashboard-section home-activity-section">
        <RecentActivityFeed dashboard={dashboard} onNavigate={onNavigate} />
      </section>

      <HomeSearchStrip onNavigate={onNavigate} />
    </div>
  );
};

const DesktopHomeDashboard = ({
  dashboard,
  appearance,
  counts,
  messages,
  groupNotice,
  onNavigate,
  onOpenAppearance,
  onOpenPinned,
  onOpenHelp,
  onOpenCover,
  formatChatTime,
  getMessagePreview,
}) => (
  <div className="home-layout desktop-home-dashboard">
    <HomeCoverHeader
      appearance={appearance}
      messages={messages}
      pinnedItems={dashboard?.pinned_items || []}
      groupNotice={groupNotice}
      onOpenSettings={onOpenAppearance}
      onOpenPinned={onOpenPinned}
      onOpenHelp={onOpenHelp}
      onOpenCover={onOpenCover}
    />
    <div className="home-main-column">
      <HomeChatPreview
        messages={messages}
        onNavigate={onNavigate}
        formatChatTime={formatChatTime}
        getMessagePreview={getMessagePreview}
      />

      <section className="dashboard-section home-activity-section">
        <RecentActivityFeed dashboard={dashboard} onNavigate={onNavigate} />
      </section>
    </div>

    <aside className="dashboard-section home-needs-section">
      <h2>Needs Attention</h2>

      <NeedsAttentionSection
        title="Upcoming Events"
        items={dashboard?.upcoming_events || []}
        type="event"
        empty="No upcoming events"
        onNavigate={onNavigate}
      />
      <NeedsAttentionSection
        title="Active Polls"
        items={dashboard?.active_polls || []}
        type="poll"
        empty="No active polls"
        onNavigate={onNavigate}
      />
      <NeedsAttentionSection
        title="Open Reminders"
        items={dashboard?.open_reminders || []}
        type="reminder"
        empty="No open reminders"
        onNavigate={onNavigate}
      />
    </aside>
  </div>
);

const CoverImageModal = ({ url, onClose }) => {
  useEffect(() => {
    if (!url) return undefined;
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [url, onClose]);

  if (!url) return null;

  return (
    <div className="cover-image-modal" role="dialog" aria-modal="true" aria-label="Cover image">
      <button className="cover-image-modal__backdrop" type="button" aria-label="Close" onClick={onClose} />
      <div className="cover-image-modal__content">
        <button className="cover-image-modal__close" type="button" aria-label="Close" onClick={onClose}>✕</button>
        <img className="cover-image-modal__image" src={url} alt="Hub cover" />
      </div>
    </div>
  );
};

const HomePage = ({ onNavigate }) => {
  const [dashboard, setDashboard] = useState(null);
  const [groupNotice, setGroupNotice] = useState('');
  const [messages, setMessages] = useState([]);
  const [appearance, setAppearance] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [appearanceOpen, setAppearanceOpen] = useState(false);
  const [pinnedModalOpen, setPinnedModalOpen] = useState(false);
  const [helpModalOpen, setHelpModalOpen] = useState(false);
  const [coverPreviewUrl, setCoverPreviewUrl] = useState(null);

  useEffect(() => {
    Promise.all([
      fetchDashboard(),
      fetchMessages(20),
      fetchHomeAppearance().catch(() => null),
    ])
      .then(([dashboardData, messagesData, appearanceData]) => {
        setDashboard(dashboardData);
        setGroupNotice(dashboardData?.group_notice || '');
        setMessages(messagesData.messages || []);
        setAppearance(appearanceData);
        setError(null);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (loading) return;
    try {
      if (localStorage.getItem(HELP_SEEN_STORAGE_KEY) !== 'true') {
        setHelpModalOpen(true);
      }
    } catch {
      // localStorage can be unavailable in strict browser modes.
    }
  }, [loading]);

  const closeHelpModal = () => {
    try {
      localStorage.setItem(HELP_SEEN_STORAGE_KEY, 'true');
    } catch {
      // Best-effort only.
    }
    setHelpModalOpen(false);
  };

  const counts = dashboard?.counts || {};

  const formatChatTime = (timestamp) => {
    if (!timestamp) return '';
    const date = new Date(timestamp);
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 1) return 'just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays < 7) return `${diffDays}d ago`;
    return date.toLocaleDateString();
  };

  const getMessagePreview = (text, maxLength = 140) => {
    if (!text) return '';
    return text.length > maxLength ? `${text.substring(0, maxLength)}…` : text;
  };

  return (
    <section className="page home-dashboard">
      {error && <div className="inline-error">{error}</div>}
      {loading && <div className="inline-notice">Loading…</div>}

      {!loading && (
        <>
          <DesktopHomeDashboard
            dashboard={dashboard}
            appearance={appearance}
            counts={counts}
            messages={messages}
            groupNotice={groupNotice}
            onNavigate={onNavigate}
            onOpenAppearance={() => setAppearanceOpen(true)}
            onOpenPinned={() => setPinnedModalOpen(true)}
            onOpenHelp={() => setHelpModalOpen(true)}
            onOpenCover={setCoverPreviewUrl}
            formatChatTime={formatChatTime}
            getMessagePreview={getMessagePreview}
          />
          <MobileHomeDashboard
            dashboard={dashboard}
            appearance={appearance}
            messages={messages}
            groupNotice={groupNotice}
            onNavigate={onNavigate}
            onOpenAppearance={() => setAppearanceOpen(true)}
            onOpenPinned={() => setPinnedModalOpen(true)}
            onOpenHelp={() => setHelpModalOpen(true)}
            onOpenCover={setCoverPreviewUrl}
            formatChatTime={formatChatTime}
            getMessagePreview={getMessagePreview}
          />
        </>
      )}

      <HomeAppearanceModal
        open={appearanceOpen}
        appearance={appearance}
        onClose={() => setAppearanceOpen(false)}
        onUpdated={(next) => setAppearance(next)}
      />

      <GroupNoticeboard
        open={pinnedModalOpen}
        onlineUsers={[]}
        pinnedItems={dashboard?.pinned_items || []}
        loading={false}
        groupNotice={groupNotice}
        onNoticeChange={setGroupNotice}
        onClose={() => setPinnedModalOpen(false)}
      />

      <HelpOnboardingModal
        open={helpModalOpen}
        onClose={closeHelpModal}
      />

      <CoverImageModal
        url={coverPreviewUrl}
        onClose={() => setCoverPreviewUrl(null)}
      />
    </section>
  );
};

export default HomePage;
