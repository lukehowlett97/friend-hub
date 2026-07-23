import React, { useMemo } from 'react';
import './ActivityFeed.css';

// ── Time helper ───────────────────────────────────────────────────────────────

function timeAgo(timestamp) {
  if (!timestamp) return '';
  const diffMs = Date.now() - new Date(timestamp).getTime();
  const mins = Math.floor(diffMs / 60000);
  const hours = Math.floor(diffMs / 3600000);
  const days = Math.floor(diffMs / 86400000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  if (hours < 24) return `${hours}h ago`;
  if (days < 7) return `${days}d ago`;
  return new Date(timestamp).toLocaleDateString();
}

function timeUntilHours(timestamp) {
  if (!timestamp) return Infinity;
  const ms = new Date(timestamp).getTime() - Date.now();
  if (ms < 0) return -1;
  return ms / 3600000;
}

function timestampMs(timestamp) {
  if (!timestamp) return 0;
  const value = new Date(timestamp).getTime();
  return Number.isNaN(value) ? 0 : value;
}

// ── Icon map ──────────────────────────────────────────────────────────────────

const TYPE_ICON = {
  event:    '📅',
  poll:     '🗳️',
  reminder: '⏰',
  photo:    '📷',
  message:  '💬',
  ai:       '✨',
  pin:      '📌',
  idea:     '💡',
  hub_item: '📦',
  note:     '📝',
};

const TYPE_LABEL = {
  event:    'Event',
  poll:     'Poll',
  reminder: 'Reminder',
  photo:    'Photos',
  message:  'Chat',
  ai:       'AI',
  pin:      'Pinned',
  idea:     'Idea',
  hub_item: 'Item',
  note:     'Note',
};

const TYPE_BG = {
  event:    '#d1fae5',
  poll:     '#dbeafe',
  reminder: '#fce7f3',
  photo:    '#fef9c3',
  message:  '#f0f4f8',
  ai:       '#ede9fe',
  pin:      '#fef3c7',
  idea:     '#fef9c3',
  hub_item: '#eef2ff',
  note:     '#f0f4f8',
};

const TYPE_COLOR = {
  event:    '#065f46',
  poll:     '#1e40af',
  reminder: '#9d174d',
  photo:    '#78350f',
  message:  '#415066',
  ai:       '#5b21b6',
  pin:      '#92400e',
  idea:     '#854d0e',
  hub_item: '#3730a3',
  note:     '#415066',
};

// ── CTA labels ────────────────────────────────────────────────────────────────

const TYPE_CTA = {
  event:    'View event',
  poll:     'Vote now',
  reminder: 'View reminder',
  photo:    'Open photos',
  ai:       'View summary',
  pin:      'Open item',
  message:  'Open chat',
  idea:     'View idea',
  hub_item: 'Open item',
  note:     'View note',
};

// ── Route helpers ─────────────────────────────────────────────────────────────

function routeForActivityLog(a) {
  if (a.target_type === 'event') return `/events/${a.target_id}`;
  if (a.target_type === 'poll') return '/polls';
  if (a.target_type === 'reminder') return '/reminders';
  if (a.target_type === 'note') return `/notes/${a.target_id}`;
  if (a.target_type === 'hub_item') return '/items';
  if (a.target_type === 'message') return '/chat';
  if (a.target_type === 'idea') return '/ideas';
  return '/home';
}

// ── Normalisation ─────────────────────────────────────────────────────────────

/**
 * Converts the dashboard object into a sorted array of ActivityItem shapes.
 * Shape: { id, type, title, subtitle, timestamp, route, icon, priority, cta }
 */
export function buildActivityItems(dashboard) {
  if (!dashboard) return [];

  const activity  = dashboard.activity || [];
  const events    = dashboard.upcoming_events || [];
  const polls     = dashboard.active_polls || [];
  const reminders = dashboard.open_reminders || [];
  const pinned    = dashboard.pinned_items || [];

  const items = [];
  const seen  = new Set();

  // Index activity log by target key
  const byKey = new Map();
  for (const a of activity) {
    const k = `${a.target_type}::${a.target_id ?? 'none'}`;
    if (!byKey.has(k)) byKey.set(k, { acts: [], latest: a.created_at });
    const g = byKey.get(k);
    g.acts.push(a);
    if (a.created_at > g.latest) g.latest = a.created_at;
  }

  // ── Events ────────────────────────────────────────────────────────────────
  // Include if: live/tonight (always urgent), OR has recent activity log entry.
  for (const ev of events) {
    const k = `event::${ev.id}`;
    seen.add(k);
    const group = byKey.get(k);
    const hoursUntil = timeUntilHours(ev.starts_at || ev.event_start_at);
    const isLive    = hoursUntil >= 0 && hoursUntil < 2;
    const isTonight = hoursUntil >= 0 && hoursUntil < 12;

    // Skip events with no activity unless they're happening soon
    if (!group && !isLive && !isTonight) continue;

    let priority = group ? 50 : 30;
    if (isLive)    priority = 120;
    else if (isTonight) priority = 100;
    else if (group) priority = 50 + Math.min(group.acts.length * 3, 20);

    const subtitle = isLive
      ? 'Starts very soon'
      : isTonight
        ? 'Tonight'
        : ev.starts_at || ev.event_start_at
          ? new Date(ev.starts_at || ev.event_start_at).toLocaleString([], { weekday: 'short', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })
          : 'Date TBD';

    items.push({
      id: k,
      type: 'event',
      title: ev.title || 'Untitled event',
      subtitle,
      timestamp: group?.latest || ev.created_at,
      route: `/events/${ev.id}`,
      priority,
      cta: isLive ? 'Going live soon' : isTonight ? 'Happening tonight' : TYPE_CTA.event,
    });
  }

  // ── Polls ─────────────────────────────────────────────────────────────────
  // Include if: has votes (i.e. real engagement), OR was recently created.
  for (const poll of polls) {
    const k = `poll::${poll.id}`;
    seen.add(k);
    const group = byKey.get(k);
    const votes = group?.acts.filter((a) => a.action === 'voted').length || 0;

    // Skip polls with no activity and no votes
    if (!group && votes === 0) continue;

    const priority = votes >= 3 ? 95 : votes >= 1 ? 70 : 35;
    const subtitle = votes > 0
      ? `${votes} vote${votes === 1 ? '' : 's'}`
      : poll.options?.length
        ? `${poll.options.length} options`
        : 'Cast your vote';

    items.push({
      id: k,
      type: 'poll',
      title: poll.title || poll.question || 'Poll',
      subtitle,
      timestamp: group?.latest || poll.created_at,
      route: '/polls',
      priority,
      cta: TYPE_CTA.poll,
    });
  }

  // ── Reminders ─────────────────────────────────────────────────────────────
  // Include if: due within 48h (actionable), OR has recent activity log entry.
  for (const r of reminders) {
    const k = `reminder::${r.id}`;
    seen.add(k);
    const group = byKey.get(k);
    const hoursUntil = timeUntilHours(r.due_at);
    const isUrgent = hoursUntil >= 0 && hoursUntil < 24;
    const isSoon   = hoursUntil >= 0 && hoursUntil < 48;

    if (!group && !isSoon) continue;

    const priority = isUrgent ? 85 : isSoon ? 55 : 25;
    const assignees = r.assignees?.map((u) => u.nickname).filter(Boolean) || [];
    const subtitle = [
      r.due_at ? `Due ${new Date(r.due_at).toLocaleDateString()}` : null,
      assignees.length > 0 ? `for ${assignees.slice(0, 2).join(', ')}` : null,
    ].filter(Boolean).join(' · ') || 'Open reminder';

    items.push({
      id: k,
      type: 'reminder',
      title: r.title || r.text || 'Reminder',
      subtitle,
      timestamp: group?.latest || r.due_at || r.created_at,
      route: '/reminders',
      priority,
      cta: TYPE_CTA.reminder,
    });
  }

  // ── Pinned items ──────────────────────────────────────────────────────────
  // Only include pinned items that have recent activity log entries.
  for (const p of pinned) {
    const type = p.type || p.hub_item?.type || 'hub_item';
    const k = `${type}::${p.id}`;
    if (seen.has(k)) continue;
    seen.add(k);
    const group = byKey.get(k);
    if (!group) continue; // no activity — skip

    const route = type === 'event' ? `/events/${p.source_id || p.id}` : type === 'note' ? `/notes/${p.source_id || p.id}` : `/${type}s`;
    items.push({
      id: `pinned::${p.id}`,
      type: 'pin',
      title: p.title || p.question || 'Pinned item',
      subtitle: TYPE_LABEL[type] || type,
      timestamp: group.latest,
      route,
      priority: 40 + Math.min(group.acts.length * 2, 15),
      cta: TYPE_CTA.pin,
    });
  }

  // ── Remaining activity log groups ─────────────────────────────────────────
  // Everything else that had real user activity but wasn't covered above.
  for (const [k, group] of byKey.entries()) {
    if (seen.has(k)) continue;
    const [target_type, target_id] = k.split('::');
    const titleFromSummary = (() => {
      for (const a of group.acts) {
        const m = a.summary?.match(/:\s*(.{1,80})$/);
        if (m) return m[1].trim();
      }
      return null;
    })();
    const actorNames = [...new Set(group.acts.map((a) => a.actor?.nickname).filter(Boolean))];
    const subtitle = actorNames.length > 0
      ? actorNames.slice(0, 2).join(', ') + (actorNames.length > 2 ? ` +${actorNames.length - 2}` : '')
      : 'Activity';
    items.push({
      id: `activity::${k}`,
      type: target_type in TYPE_ICON ? target_type : 'message',
      title: titleFromSummary || TYPE_LABEL[target_type] || 'Activity',
      subtitle,
      timestamp: group.latest,
      route: routeForActivityLog({ target_type, target_id }),
      priority: 15 + Math.min(group.acts.length * 2, 20),
      cta: TYPE_CTA[target_type] || 'View',
    });
  }

  return items.sort((a, b) => b.priority - a.priority);
}

/**
 * Picks the single best item to feature prominently.
 * Returns null if nothing is strong enough.
 */
export function pickFeaturedItem(items) {
  if (!items.length) return null;
  const best = items[0];
  // Only feature if it has genuine urgency/engagement (priority >= 70)
  return best.priority >= 70 ? best : null;
}

function newestFirst(a, b) {
  return timestampMs(b.timestamp) - timestampMs(a.timestamp);
}

// ── FeaturedActivityCard ──────────────────────────────────────────────────────

const GRADIENTS = {
  event:    'linear-gradient(135deg, #f472b6 0%, #8b5cf6 55%, #4f46e5 100%)',
  poll:     'linear-gradient(135deg, #38bdf8 0%, #6366f1 65%, #312e81 100%)',
  reminder: 'linear-gradient(135deg, #fb923c 0%, #ef4444 65%, #7f1d1d 100%)',
  pin:      'linear-gradient(135deg, #facc15 0%, #f97316 65%, #b45309 100%)',
  ai:       'linear-gradient(135deg, #34d399 0%, #06b6d4 60%, #1e3a8a 100%)',
  default:  'linear-gradient(135deg, #475569 0%, #1f2937 100%)',
};

export const FeaturedActivityCard = ({ item, onNavigate }) => {
  if (!item) return null;
  const gradient = GRADIENTS[item.type] || GRADIENTS.default;
  const icon = TYPE_ICON[item.type] || '⚡';

  return (
    <button
      type="button"
      className="featured-card"
      style={{ backgroundImage: gradient }}
      onClick={() => onNavigate(item.route)}
      aria-label={`Featured: ${item.title}`}
    >
      <span className="featured-card__icon" aria-hidden="true">{icon}</span>
      <div className="featured-card__body">
        <span className="featured-card__type">{TYPE_LABEL[item.type] || item.type}</span>
        <strong className="featured-card__title">{item.title}</strong>
        {item.subtitle && <span className="featured-card__sub">{item.subtitle}</span>}
      </div>
      {item.cta && (
        <span className="featured-card__cta">{item.cta} →</span>
      )}
    </button>
  );
};

// ── ActivityFeedRow ───────────────────────────────────────────────────────────

export const ActivityFeedRow = ({ item, onNavigate }) => {
  const bg    = TYPE_BG[item.type]    || '#f0f4f8';
  const color = TYPE_COLOR[item.type] || '#415066';
  const icon  = TYPE_ICON[item.type]  || '•';

  return (
    <button
      type="button"
      className="activity-feed-row"
      onClick={() => onNavigate(item.route)}
      aria-label={item.title}
    >
      <span className="activity-feed-row__icon" style={{ background: bg, color }} aria-hidden="true">
        {icon}
      </span>
      <div className="activity-feed-row__body">
        <span className="activity-feed-row__title">{item.title}</span>
        {item.subtitle && (
          <span className="activity-feed-row__sub">{item.subtitle}</span>
        )}
      </div>
      <span className="activity-feed-row__time">{timeAgo(item.timestamp)}</span>
    </button>
  );
};

// ── RecentActivityFeed ────────────────────────────────────────────────────────

export const RecentActivityFeed = ({ dashboard, onNavigate, maxRows = 6 }) => {
  const allItems = useMemo(() => buildActivityItems(dashboard), [dashboard]);
  const featured = useMemo(() => pickFeaturedItem(allItems), [allItems]);

  // Feed rows: skip the featured item so it's not duplicated
  const feedItems = useMemo(() => {
    const skip = featured?.id;
    return allItems
      .filter((i) => i.id !== skip)
      .sort(newestFirst)
      .slice(0, maxRows);
  }, [allItems, featured, maxRows]);

  return (
    <div className="activity-feed-wrap">
      {featured && (
        <section className="activity-feed-featured">
          <h2 className="activity-feed-section-title">Featured Now</h2>
          <FeaturedActivityCard item={featured} onNavigate={onNavigate} />
        </section>
      )}

      <section className="activity-feed-list-section">
        <h2 className="activity-feed-section-title">Recent Activity</h2>
        {feedItems.length > 0 ? (
          <div className="activity-feed-list">
            {feedItems.map((item) => (
              <ActivityFeedRow key={item.id} item={item} onNavigate={onNavigate} />
            ))}
          </div>
        ) : (
          <p className="activity-feed-empty">No recent activity yet.</p>
        )}
      </section>
    </div>
  );
};

export default RecentActivityFeed;
