import React, { useCallback, useEffect, useRef, useState } from 'react';
import UserAvatar from './UserAvatar.jsx';
import {
  fetchRoomOverview,
  fetchMembers,
  fetchDashboard,
  fetchEvents,
  fetchMessages,
} from '../../services/api.js';
import { buildChatMessageHref } from '../../utils/chatLinks.js';
import './RoomOverview.css';

const ACTIVITY_WINDOWS = [
  { key: 'past_hour', label: 'Past hour' },
  { key: 'past_3_hours', label: 'Past 3h' },
  { key: 'today', label: 'Today' },
  { key: 'this_week', label: 'This week' },
];

function getPinnedTitle(item) {
  const detail = item.detail || {};
  return detail.question || detail.title || item.question || item.title || 'Pinned item';
}

function getPinnedRoute(item) {
  const type = item.type || item.source_type;
  const sourceId = Number(item.source_id || item.hub_item?.source_id || item.id);
  if (type === 'event') return `/events/${sourceId}`;
  if (type === 'idea') return '/ideas';
  if (type === 'poll') return '/polls';
  if (type === 'reminder') return '/reminders';
  return '/items';
}

function formatRelativeEventTime(startValue, endValue = null) {
  if (!startValue) return null;
  const start = new Date(startValue);
  const end = endValue ? new Date(endValue) : null;
  if (Number.isNaN(start.getTime())) return null;

  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const startDay = new Date(start.getFullYear(), start.getMonth(), start.getDate());
  const dayDiff = Math.round((startDay - startOfToday) / 86400000);
  const time = new Intl.DateTimeFormat(undefined, {
    hour: 'numeric',
    minute: '2-digit',
  }).format(start);

  if (end && !Number.isNaN(end.getTime()) && now >= start && now <= end) {
    return `now, until ${new Intl.DateTimeFormat(undefined, {
      hour: 'numeric',
      minute: '2-digit',
    }).format(end)}`;
  }

  if (now > start) {
    const minutesAgo = Math.max(1, Math.round((now - start) / 60000));
    if (minutesAgo < 90) return `started ${minutesAgo}m ago`;
    const hoursAgo = Math.round(minutesAgo / 60);
    if (hoursAgo < 36) return `started ${hoursAgo}h ago`;
    return `started ${Math.round(hoursAgo / 24)}d ago`;
  }

  if (dayDiff === 0) return `today, ${time}`;
  if (dayDiff === 1) return `tomorrow, ${time}`;
  return `in ${dayDiff} days, ${time}`;
}

function buildUpcoming(events) {
  const now = Date.now();
  return (events || [])
    .map((event) => ({
      id: event.id,
      title: event.title || 'Event',
      startAt: event.starts_at || event.event_start_at || event.start_at,
      endAt: event.ends_at || event.event_end_at || event.end_at,
    }))
    .filter((event) => {
      if (!event.startAt) return false;
      const t = new Date(event.startAt).getTime();
      const end = event.endAt ? new Date(event.endAt).getTime() : null;
      if (Number.isNaN(t)) return false;
      if (Number.isFinite(end)) return end >= now;
      return t >= now;
    })
    .sort((a, b) => new Date(a.startAt) - new Date(b.startAt))
    .slice(0, 12);
}

const SectionHeading = ({ title, action }) => (
  <div className="room-overview__section-head">
    <h3>{title}</h3>
    {action}
  </div>
);

const RoomOverview = ({
  open,
  roomName,
  onlineUsers = [],
  currentSessionId,
  onClose,
  onNavigate,
  onOpenPhoto,
  onOpenSearch,
  onOpenHelp,
  onOpenPinned,
  onOpenChatSettings,
}) => {
  const [overview, setOverview] = useState(null);
  const [members, setMembers] = useState([]);
  const [pinnedItems, setPinnedItems] = useState([]);
  const [upcoming, setUpcoming] = useState([]);
  const [upcomingPage, setUpcomingPage] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const sheetRef = useRef(null);
  const closeRef = useRef(null);

  const load = useCallback(() => {
    let cancelled = false;
    setLoading(true);
    setError('');
    Promise.all([
      fetchRoomOverview(),
      fetchMembers().catch(() => ({ members: [] })),
      fetchDashboard().catch(() => ({ pinned_items: [] })),
      fetchEvents().catch(() => ({ events: [] })),
    ])
      .then(([ov, mem, dash, ev]) => {
        if (cancelled) return;
        setOverview(ov);
        setMembers((mem.members || []).filter((m) => !m.invite_pending));
        setPinnedItems((dash.pinned_items || []).slice(0, 4));
        setUpcoming(buildUpcoming(ev.events));
        setUpcomingPage(0);
      })
      .catch((err) => {
        if (!cancelled) setError(err.message || 'Failed to load room overview');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!open) return undefined;
    const cleanup = load();
    return cleanup;
  }, [open, load]);

  // Focus the close button on open + Escape to close.
  useEffect(() => {
    if (!open) return undefined;
    closeRef.current?.focus();
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  const onlineSessionIds = new Set(onlineUsers.map((u) => u.session_id).filter(Boolean));
  const liveCount = onlineUsers.length;
  const memberCount = overview?.members ?? members.length;
  const importedMemberCount = overview?.imported_members ?? 0;
  const activity = overview?.activity || {};
  const activityWindows = overview?.activity_windows || {};
  const recentPhotos = overview?.recent_photos || [];
  const contributors = overview?.top_contributors || [];
  const upcomingPageSize = 2;
  const upcomingPageCount = Math.max(1, Math.ceil(upcoming.length / upcomingPageSize));
  const visibleUpcoming = upcoming.slice(
    upcomingPage * upcomingPageSize,
    (upcomingPage + 1) * upcomingPageSize,
  );

  const go = (path) => {
    onClose();
    onNavigate(path);
  };

  const openProfile = (member) => {
    if (member.username) go(`/profile/${member.username}`);
    else if (member.session_id === currentSessionId) go('/profile');
  };

  // Jump to the earliest loaded message in a time window. Falls back to opening
  // the room search if no message is found in range.
  const jumpToWindow = async (windowKey) => {
    const since = activityWindows[windowKey];
    if (!since) return;
    try {
      const data = await fetchMessages(50, { start_at: since });
      const msgs = data.messages || [];
      // Messages return newest-first; the last entry is the oldest in range.
      const oldest = msgs[msgs.length - 1];
      if (oldest?.id) {
        go(buildChatMessageHref(oldest.id));
        return;
      }
    } catch {
      /* fall through to search */
    }
    if (onOpenSearch) {
      onClose();
      onOpenSearch();
    }
  };

  const handleBackdrop = (e) => {
    if (e.target === e.currentTarget) onClose();
  };

  return (
    <div className="room-overview__backdrop" role="presentation" onClick={handleBackdrop}>
      <section
        className="room-overview"
        role="dialog"
        aria-modal="true"
        aria-label={`${roomName || 'Room'} overview`}
        ref={sheetRef}
      >
        <div className="room-overview__grabber" aria-hidden="true" />

        {/* ── Room header ── */}
        <header className="room-overview__header">
          <button
            type="button"
            className="room-overview__identity"
            onClick={() => go('/settings')}
            aria-label="Open room settings"
          >
            <span className="room-overview__avatar" aria-hidden="true">
              {(roomName || '?').charAt(0).toUpperCase()}
            </span>
            <span className="room-overview__identity-text">
              <strong className="room-overview__name">{roomName || 'Room'}</strong>
              <span className="room-overview__subtitle">
                <button
                  type="button"
                  className="room-overview__stat-link"
                  onClick={(e) => { e.stopPropagation(); go('/members'); }}
                >
                  {memberCount} member{memberCount === 1 ? '' : 's'}
                </button>
                {liveCount > 0 && (
                  <>
                    {' · '}
                    <span className="room-overview__live">{liveCount} live</span>
                  </>
                )}
                {importedMemberCount > 0 && (
                  <>
                    {' · '}
                    <span>{importedMemberCount} imported</span>
                  </>
                )}
              </span>
            </span>
          </button>
          <button
            type="button"
            className="room-overview__close"
            onClick={onClose}
            aria-label="Close room overview"
            ref={closeRef}
          >
            ×
          </button>
        </header>

        {/* ── Quick actions ── */}
        <div className="room-overview__quick">
          <button type="button" className="room-overview__quick-btn" onClick={() => { onClose(); onOpenSearch?.(); }}>
            <span aria-hidden="true">🔍</span> Search
          </button>
          <button type="button" className="room-overview__quick-btn" onClick={() => go('/members')}>
            <span aria-hidden="true">👥</span> Members
          </button>
          {onOpenPinned && (
            <button type="button" className="room-overview__quick-btn" onClick={() => { onClose(); onOpenPinned(); }}>
              <span aria-hidden="true">📍</span> Pinned &amp; live
            </button>
          )}
          {onOpenChatSettings && (
            <button type="button" className="room-overview__quick-btn" onClick={() => { onClose(); onOpenChatSettings(); }}>
              <span aria-hidden="true">⚙</span> Chat settings
            </button>
          )}
          <button type="button" className="room-overview__quick-btn" onClick={() => go('/settings')}>
            <span aria-hidden="true">⚙</span> Settings
          </button>
          {onOpenHelp && (
            <button type="button" className="room-overview__quick-btn" onClick={() => { onClose(); onOpenHelp(); }}>
              <span aria-hidden="true">?</span> Help
            </button>
          )}
        </div>

        {error && (
          <div className="room-overview__error">
            {error}
            <button type="button" onClick={load}>Retry</button>
          </div>
        )}

        {/* ── Activity snapshot ── */}
        <section className="room-overview__section">
          <SectionHeading title="Activity" />
          <div className="room-overview__activity">
            {ACTIVITY_WINDOWS.map(({ key, label }) => (
              <button
                key={key}
                type="button"
                className="room-overview__activity-chip"
                onClick={() => jumpToWindow(key)}
                disabled={loading}
                aria-label={`${label}: ${activity[key] ?? 0} messages — jump to chat`}
              >
                <span className="room-overview__activity-count">
                  {loading ? '·' : (activity[key] ?? 0)}
                </span>
                <span className="room-overview__activity-label">{label}</span>
              </button>
            ))}
          </div>
        </section>

        {/* ── Pinned items ── */}
        <section className="room-overview__section">
          <SectionHeading
            title="Pinned"
            action={
              <button type="button" className="room-overview__view-all" onClick={() => go('/items')}>
                View all
              </button>
            }
          />
          {loading ? (
            <div className="room-overview__skeleton room-overview__skeleton--row" />
          ) : pinnedItems.length > 0 ? (
            <ul className="room-overview__pinned">
              {pinnedItems.map((item) => (
                <li key={item.id || item.short_id}>
                  <button type="button" className="room-overview__pinned-card" onClick={() => go(getPinnedRoute(item))}>
                    <span className="room-overview__pinned-type">{item.type || item.source_type || 'item'}</span>
                    <span className="room-overview__pinned-title">{getPinnedTitle(item)}</span>
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="room-overview__empty">No pinned messages.</p>
          )}
        </section>

        {/* ── Recent photos ── */}
        <section className="room-overview__section">
          <SectionHeading
            title="Recent photos"
            action={
              <button type="button" className="room-overview__view-all" onClick={() => go('/photos')}>
                View all
              </button>
            }
          />
          {loading ? (
            <div className="room-overview__skeleton room-overview__skeleton--strip" />
          ) : recentPhotos.length > 0 ? (
            <div className="room-overview__photos" role="list">
              {recentPhotos.map((photo) => (
                <button
                  key={photo.id}
                  type="button"
                  className="room-overview__photo"
                  role="listitem"
                  onClick={() => {
                    onClose();
                    onOpenPhoto?.({
                      url: photo.url,
                      label: photo.label,
                      caption: photo.caption,
                      created_at: photo.created_at,
                      original_sender: photo.uploaded_by,
                      showSeeInPhotos: true,
                    });
                  }}
                  aria-label={photo.label || 'Shared photo'}
                >
                  <img src={photo.thumbnail_url} alt={photo.label || 'Shared photo'} loading="lazy" />
                </button>
              ))}
            </div>
          ) : (
            <p className="room-overview__empty">No photos yet.</p>
          )}
        </section>

        {/* ── Coming up ── */}
        <section className="room-overview__section">
          <SectionHeading
            title="Coming up"
            action={
              <div className="room-overview__upcoming-actions">
                <button type="button" className="room-overview__view-all" onClick={() => go('/calendar')}>
                  Calendar
                </button>
                {upcoming.length > upcomingPageSize && (
                  <div className="room-overview__pager" aria-label="Browse upcoming events">
                    <button
                      type="button"
                      onClick={() => setUpcomingPage((page) => Math.max(0, page - 1))}
                      disabled={upcomingPage === 0}
                      aria-label="Previous upcoming events"
                    >
                      ‹
                    </button>
                    <span>{upcomingPage + 1}/{upcomingPageCount}</span>
                    <button
                      type="button"
                      onClick={() => setUpcomingPage((page) => Math.min(upcomingPageCount - 1, page + 1))}
                      disabled={upcomingPage >= upcomingPageCount - 1}
                      aria-label="Next upcoming events"
                    >
                      ›
                    </button>
                  </div>
                )}
              </div>
            }
          />
          {loading ? (
            <div className="room-overview__skeleton room-overview__skeleton--row" />
          ) : upcoming.length > 0 ? (
            <ul className="room-overview__upcoming">
              {visibleUpcoming.map((event) => (
                <li key={event.id}>
                  <button type="button" className="room-overview__upcoming-card" onClick={() => go(`/events/${event.id}`)}>
                    <span className="room-overview__upcoming-title">{event.title}</span>
                    <span className="room-overview__upcoming-when">{formatRelativeEventTime(event.startAt, event.endAt)}</span>
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="room-overview__empty">Nothing coming up.</p>
          )}
        </section>

        {/* ── Top contributors ── */}
        {(loading || contributors.length > 0) && (
          <section className="room-overview__section">
            <SectionHeading
              title="Top contributors this week"
              action={
                <button type="button" className="room-overview__view-all" onClick={() => go('/stats')}>
                  Stats
                </button>
              }
            />
            {loading ? (
              <div className="room-overview__skeleton room-overview__skeleton--row" />
            ) : (
              <ul className="room-overview__contributors">
                {contributors.map((c) => {
                  const member = members.find((m) => m.nickname === c.nickname);
                  return (
                    <li key={c.nickname}>
                      <button
                        type="button"
                        className="room-overview__contributor"
                        onClick={() => member ? openProfile(member) : null}
                        disabled={!member?.username}
                        title={member?.username ? `View ${c.nickname}'s profile` : c.nickname}
                      >
                        <UserAvatar nickname={c.nickname} size={40} avatarUrl={c.avatar_url} avatarEmoji={c.avatar_emoji} />
                        <span className="room-overview__contributor-name">{c.nickname}</span>
                        <span className="room-overview__contributor-count">{c.message_count}</span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </section>
        )}

        {/* ── Members preview ── */}
        <section className="room-overview__section">
          <SectionHeading
            title="Members"
            action={
              <button type="button" className="room-overview__view-all" onClick={() => go('/members')}>
                View all
              </button>
            }
          />
          {loading ? (
            <div className="room-overview__skeleton room-overview__skeleton--row" />
          ) : members.length > 0 ? (
            <div className="room-overview__members" role="list">
              {members.slice(0, 12).map((member) => {
                const isOnline = onlineSessionIds.has(member.session_id) || member.is_online;
                return (
                  <button
                    key={member.session_id || member.username}
                    type="button"
                    className="room-overview__member"
                    role="listitem"
                    onClick={() => openProfile(member)}
                    disabled={!member.username && member.session_id !== currentSessionId}
                    title={`View ${member.nickname}'s profile`}
                  >
                    <span className="room-overview__member-avatar">
                      <UserAvatar nickname={member.nickname} size={44} avatarUrl={member.avatar_url} avatarEmoji={member.avatar_emoji} />
                      {isOnline && <span className="room-overview__member-dot" aria-label="Online" />}
                    </span>
                    <span className="room-overview__member-name">{member.nickname}</span>
                  </button>
                );
              })}
            </div>
          ) : (
            <p className="room-overview__empty">No members yet.</p>
          )}
        </section>
      </section>
    </div>
  );
};

export default RoomOverview;
