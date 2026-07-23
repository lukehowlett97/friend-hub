import React, { useEffect, useMemo, useRef, useState } from 'react';
import UserAvatar from '../Chat/UserAvatar.jsx';
import './ActivityStories.css';

// ── Time helpers ─────────────────────────────────────────────────────────────

function timeAgo(timestamp) {
  if (!timestamp) return '';
  const date = new Date(timestamp);
  const diffMs = Date.now() - date.getTime();
  const mins = Math.floor(diffMs / 60000);
  const hours = Math.floor(diffMs / 3600000);
  const days = Math.floor(diffMs / 86400000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  if (hours < 24) return `${hours}h ago`;
  if (days < 7) return `${days}d ago`;
  return date.toLocaleDateString();
}

function timeUntilParts(timestamp) {
  if (!timestamp) return null;
  const ms = new Date(timestamp).getTime() - Date.now();
  if (ms < 0) return { past: true, ms };
  return {
    past: false,
    ms,
    mins: Math.floor(ms / 60000),
    hours: Math.floor(ms / 3600000),
    days: Math.floor(ms / 86400000),
  };
}

function shortUntil(timestamp) {
  const t = timeUntilParts(timestamp);
  if (!t || t.past) return null;
  if (t.mins < 60) return `${t.mins}m`;
  if (t.hours < 24) return `${t.hours}h`;
  return `${t.days}d`;
}

function friendlyDate(timestamp) {
  if (!timestamp) return null;
  const date = new Date(timestamp);
  return date.toLocaleString([], { weekday: 'short', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
}

// ── Social-language translation ─────────────────────────────────────────────

function summarizeActivity(activities) {
  if (!activities?.length) return null;
  const counts = {};
  const actors = new Set();
  for (const a of activities) {
    counts[a.action] = (counts[a.action] || 0) + 1;
    if (a.actor?.nickname) actors.add(a.actor.nickname);
  }
  const parts = [];
  if (counts.voted) parts.push(`${counts.voted} vote${counts.voted === 1 ? '' : 's'}`);
  if (counts.commented) parts.push(`${counts.commented} comment${counts.commented === 1 ? '' : 's'}`);
  if (counts.created && counts.created > 1) parts.push(`${counts.created} new`);
  if (counts.updated && parts.length === 0) {
    parts.push(counts.updated >= 3 ? 'Plans evolving fast' : 'Just updated');
  }
  if (parts.length === 0 && actors.size > 0) {
    parts.push(`${actors.size} ${actors.size === 1 ? 'person' : 'people'} active`);
  }
  return parts.join(' · ') || null;
}

function detectMomentum(activities, createdAt) {
  if (!activities?.length) return null;
  const actors = new Set(activities.map((a) => a.actor?.nickname).filter(Boolean));
  if (activities.length >= 5 && actors.size >= 3) return '🔥 Gaining traction';
  if (activities.length >= 8) return '🔥 Heating up';
  if (actors.size >= 3) return '👥 Everyone’s chiming in';
  if (createdAt) {
    const hoursOld = (Date.now() - new Date(createdAt).getTime()) / 3600000;
    if (hoursOld < 6 && activities.length >= 2) return '✨ Just kicked off';
    if (hoursOld > 72 && activities.length >= 2) return '↩️ Revived';
  }
  return null;
}

// Pick a soft gradient based on the target type so empty cards still feel alive.
const GRADIENTS = {
  event:    'linear-gradient(155deg, #f472b6 0%, #8b5cf6 55%, #4f46e5 100%)',
  poll:     'linear-gradient(155deg, #38bdf8 0%, #6366f1 65%, #312e81 100%)',
  reminder: 'linear-gradient(155deg, #fb923c 0%, #ef4444 65%, #7f1d1d 100%)',
  pinned:   'linear-gradient(155deg, #facc15 0%, #f97316 65%, #b45309 100%)',
  ai:       'linear-gradient(155deg, #34d399 0%, #06b6d4 60%, #1e3a8a 100%)',
  idea:     'linear-gradient(155deg, #fde68a 0%, #f59e0b 55%, #92400e 100%)',
  default:  'linear-gradient(155deg, #475569 0%, #1f2937 100%)',
};

// ── Story building ──────────────────────────────────────────────────────────

function buildStories(dashboard) {
  const activity = dashboard?.activity || [];
  const events = dashboard?.upcoming_events || [];
  const polls = dashboard?.active_polls || [];
  const reminders = dashboard?.open_reminders || [];
  const pinned = dashboard?.pinned_items || [];

  const byKey = new Map();
  for (const a of activity) {
    const k = `${a.target_type}::${a.target_id ?? 'none'}`;
    if (!byKey.has(k)) byKey.set(k, []);
    byKey.get(k).push(a);
  }

  const seen = new Set();
  const stories = [];

  // Live/tonight events first
  for (const ev of events) {
    const t = timeUntilParts(ev.starts_at || ev.event_start_at);
    const acts = byKey.get(`event::${ev.id}`) || [];
    const isLive = t && !t.past && t.hours < 2;
    const isTonight = t && !t.past && t.hours < 12;
    let priority = 50;
    if (isLive) priority = 120;
    else if (isTonight) priority = 100;
    else if (acts.length >= 3) priority = 75;
    stories.push({ kind: 'event', key: `event::${ev.id}`, priority, data: ev, activity: acts });
    seen.add(`event::${ev.id}`);
  }

  // Polls — surface socially active ones
  for (const poll of polls) {
    const acts = byKey.get(`poll::${poll.id}`) || [];
    const votes = acts.filter((a) => a.action === 'voted').length;
    let priority = 40;
    if (votes >= 3) priority = 95;
    else if (votes >= 1) priority = 70;
    stories.push({ kind: 'poll', key: `poll::${poll.id}`, priority, data: poll, activity: acts, voteCount: votes });
    seen.add(`poll::${poll.id}`);
  }

  // Reminders due soon
  for (const r of reminders) {
    const t = timeUntilParts(r.due_at);
    const acts = byKey.get(`reminder::${r.id}`) || [];
    let priority = 30;
    if (t && !t.past && t.hours < 24) priority = 85;
    stories.push({ kind: 'reminder', key: `reminder::${r.id}`, priority, data: r, activity: acts });
    seen.add(`reminder::${r.id}`);
  }

  // Pinned items not already covered
  for (const p of pinned) {
    const type = p.type || p.hub_item?.type;
    const k = `${type}::${p.id}`;
    if (seen.has(k)) continue;
    stories.push({ kind: 'pinned', key: `pinned::${p.id}`, priority: 45, data: p, activity: byKey.get(k) || [] });
  }

  // Remaining activity groups — fold into generic story cards
  for (const [k, acts] of byKey.entries()) {
    if (seen.has(k)) continue;
    if (acts.length === 0) continue;
    const [target_type, target_id] = k.split('::');
    stories.push({
      kind: 'activity',
      key: `activity::${k}`,
      priority: 15 + Math.min(acts.length * 2, 20),
      data: { target_type, target_id, activities: acts },
      activity: acts,
    });
  }

  return stories.sort((a, b) => b.priority - a.priority).slice(0, 10);
}

// ── Shared shell ────────────────────────────────────────────────────────────

function getPinnedRoute(item) {
  const type = item.type || item.hub_item?.type || 'item';
  if (type === 'event') return `/events/${item.source_id || item.id}`;
  return `/${type}s`;
}

function getStoryRoute(story) {
  if (!story) return '/home';
  if (story.kind === 'event') return `/events/${story.data.id}`;
  if (story.kind === 'poll') return '/polls';
  if (story.kind === 'reminder') return '/reminders';
  if (story.kind === 'pinned') return getPinnedRoute(story.data);
  if (story.kind === 'activity') {
    const { target_type, target_id } = story.data;
    return ROUTE_FOR_TARGET[target_type]?.(target_id) || '/home';
  }
  return '/home';
}

const coverPositionStyle = (item = {}) => {
  const detail = item.detail || item.hub_item || {};
  const x = detail.cover_photo_position_x ?? item.cover_photo_position_x ?? 50;
  const y = detail.cover_photo_position_y ?? item.cover_photo_position_y ?? 50;
  return { objectPosition: `${x}% ${y}%` };
};

const StoryShell = ({ coverImage, coverPosition, gradient, onClick, badge, badgeTone = 'default', countLabel, children }) => (
  <button type="button" className="story-card" onClick={onClick} style={{ backgroundImage: gradient }}>
    <div className="story-card__media">
      {coverImage && <img className="story-card__image" src={coverImage} alt="" loading="lazy" style={coverPosition} />}
      <div className="story-card__veil" />
      {badge && (
        <span className={`story-card__badge tone-${badgeTone}`}>
          {badge}
        </span>
      )}
      {countLabel && <span className="story-card__count">{countLabel}</span>}
    </div>
    <div className="story-card__body">{children}</div>
  </button>
);

const StoryAvatars = ({ actors, size = 28, max = 4 }) => {
  const unique = useMemo(() => (
    [...new Map(
      (actors || []).filter((a) => a?.nickname).map((a) => [a.nickname, a]),
    ).values()].slice(0, max)
  ), [actors, max]);
  if (unique.length === 0) return null;
  return (
    <div className="story-card__avatars">
      {unique.map((a) => (
        <span key={a.nickname} className="story-card__avatar">
          <UserAvatar nickname={a.nickname} avatarUrl={a.avatar_url} size={size} />
        </span>
      ))}
    </div>
  );
};

// ── Card variants ───────────────────────────────────────────────────────────

const EventStoryCard = ({ story, onNavigate, countLabel }) => {
  const ev = story.data;
  const cover = ev.cover_photo_url || ev.cover_image_url;
  const startsAt = ev.starts_at || ev.event_start_at;
  const t = timeUntilParts(startsAt);
  const isLive = t && !t.past && t.hours < 2;
  const isTonight = t && !t.past && t.hours < 12;
  const headline = isLive
    ? `Starts in ${shortUntil(startsAt)}`
    : isTonight
      ? `Tonight · ${shortUntil(startsAt)}`
      : friendlyDate(startsAt) || 'Date TBD';
  const momentum = detectMomentum(story.activity, ev.created_at);
  const summary = summarizeActivity(story.activity) || momentum || null;
  const details = [headline, ev.location].filter(Boolean).join(' · ');
  const actors = (story.activity || []).map((a) => a.actor).filter(Boolean);
  const badge = isLive ? 'Live soon' : isTonight ? 'Tonight' : 'Event';

  return (
    <StoryShell
      coverImage={cover}
      coverPosition={coverPositionStyle(ev)}
      gradient={GRADIENTS.event}
      badge={badge}
      badgeTone={isLive ? 'live' : 'default'}
      countLabel={countLabel}
      onClick={() => onNavigate(getStoryRoute(story))}
    >
      <h3 className="story-card__title">{ev.title || 'Untitled event'}</h3>
      <p className="story-card__sub">{details}</p>
      {summary && <div className="story-card__eyebrow">{summary}</div>}
      <StoryAvatars actors={actors} />
    </StoryShell>
  );
};

const PollStoryCard = ({ story, onNavigate, countLabel }) => {
  const poll = story.data;
  const optionCount = poll.options?.length || 0;
  const voteCount = story.voteCount || 0;
  const closesIn = shortUntil(poll.deadline_at);
  const actors = (story.activity || []).map((a) => a.actor).filter(Boolean);
  const headline = closesIn ? `Closes in ${closesIn}` : 'Poll open';
  const summary = voteCount > 0
    ? `${voteCount} ${voteCount === 1 ? 'vote' : 'votes'} · ${optionCount} options`
    : (detectMomentum(story.activity, poll.created_at) || 'Cast your vote');
  const isHot = voteCount >= 3;

  return (
    <StoryShell
      gradient={GRADIENTS.poll}
      badge={isHot ? '🔥 Hot poll' : 'Poll'}
      badgeTone={isHot ? 'hot' : 'default'}
      countLabel={countLabel}
      onClick={() => onNavigate(getStoryRoute(story))}
    >
      <div className="story-card__eyebrow">{headline}</div>
      <h3 className="story-card__title">{poll.title || poll.question || 'Untitled poll'}</h3>
      <p className="story-card__sub">{summary}</p>
      <div className="story-card__progress">
        <span style={{ width: `${Math.min(100, voteCount * 15 + 10)}%` }} />
      </div>
      <StoryAvatars actors={actors} />
    </StoryShell>
  );
};

const ReminderStoryCard = ({ story, onNavigate, countLabel }) => {
  const r = story.data;
  const t = timeUntilParts(r.due_at);
  const due = shortUntil(r.due_at);
  const isUrgent = t && !t.past && t.hours < 24;
  const assignees = r.assignees?.map((u) => u.nickname).filter(Boolean) || [];
  const headline = due
    ? (isUrgent ? `Due in ${due}` : `Due in ${due}`)
    : 'No due date';
  const summary = assignees.length > 0
    ? `For ${assignees.slice(0, 2).join(', ')}${assignees.length > 2 ? ` +${assignees.length - 2}` : ''}`
    : 'Lightweight nudge';

  return (
    <StoryShell
      gradient={GRADIENTS.reminder}
      badge={isUrgent ? '⏰ Due soon' : 'Reminder'}
      badgeTone={isUrgent ? 'urgent' : 'default'}
      countLabel={countLabel}
      onClick={() => onNavigate(getStoryRoute(story))}
    >
      <div className="story-card__eyebrow">{headline}</div>
      <h3 className="story-card__title">{r.title || 'Reminder'}</h3>
      <p className="story-card__sub">{summary}</p>
      <StoryAvatars actors={(r.assignees || []).map((u) => ({ nickname: u.nickname, avatar_url: u.avatar_url }))} />
    </StoryShell>
  );
};

const PinnedStoryCard = ({ story, onNavigate, countLabel }) => {
  const item = story.data;
  const type = item.type || item.hub_item?.type || 'item';
  const momentum = detectMomentum(story.activity, item.created_at);
  const summary = summarizeActivity(story.activity) || momentum || 'Pinned for the group';

  return (
    <StoryShell
      coverImage={item.cover_photo_url || item.cover_image_url}
      coverPosition={coverPositionStyle(item)}
      gradient={GRADIENTS.pinned}
      badge="📌 Pinned"
      countLabel={countLabel}
      onClick={() => onNavigate(getStoryRoute(story))}
    >
      <div className="story-card__eyebrow">{type.toUpperCase()}</div>
      <h3 className="story-card__title">{item.title || item.question || 'Pinned item'}</h3>
      <p className="story-card__sub">{summary}</p>
      <StoryAvatars actors={(story.activity || []).map((a) => a.actor).filter(Boolean)} />
    </StoryShell>
  );
};

const ROUTE_FOR_TARGET = {
  event: (id) => `/events/${id}`,
  idea: () => '/ideas',
  poll: () => '/polls',
  reminder: () => '/reminders',
  hub_item: () => '/items',
  message: () => '/chat',
  note: (id) => `/notes/${id}`,
};

const TARGET_LABEL = {
  event: 'Event', idea: 'Idea', poll: 'Poll', reminder: 'Reminder',
  hub_item: 'Item', message: 'Chat', note: 'Note',
};

const GenericActivityCard = ({ story, onNavigate, countLabel }) => {
  const { target_type, target_id } = story.data;
  const acts = story.activity;
  const targetName = (() => {
    for (const a of acts) {
      const m = a.summary?.match(/:\s*(.{1,80})$/);
      if (m) return m[1].trim();
    }
    return TARGET_LABEL[target_type] || 'Activity';
  })();
  const momentum = detectMomentum(acts, acts[acts.length - 1]?.created_at);
  const summary = summarizeActivity(acts) || 'Recent updates';
  const actors = acts.map((a) => a.actor).filter(Boolean);
  const latest = acts.reduce((m, a) => (a.created_at > m ? a.created_at : m), acts[0]?.created_at);

  return (
    <StoryShell
      gradient={GRADIENTS[target_type] || GRADIENTS.default}
      badge={momentum || TARGET_LABEL[target_type] || 'Activity'}
      badgeTone={momentum ? 'hot' : 'default'}
      countLabel={countLabel}
      onClick={() => onNavigate(getStoryRoute(story))}
    >
      <div className="story-card__eyebrow">{timeAgo(latest)}</div>
      <h3 className="story-card__title">{targetName}</h3>
      <p className="story-card__sub">{summary}</p>
      <StoryAvatars actors={actors} />
    </StoryShell>
  );
};

const CARD_BY_KIND = {
  event: EventStoryCard,
  poll: PollStoryCard,
  reminder: ReminderStoryCard,
  pinned: PinnedStoryCard,
  activity: GenericActivityCard,
};

// ── Main carousel ───────────────────────────────────────────────────────────

const EmptyStory = () => (
  <div className="story-empty">
    <div className="story-empty__glow" />
    <p className="story-empty__title">Quiet right now</p>
    <p className="story-empty__sub">When plans, polls or messages start moving, you’ll see them here.</p>
  </div>
);

export const ActivityStories = ({ dashboard, onNavigate }) => {
  const stories = useMemo(() => buildStories(dashboard), [dashboard]);
  const scrollerRef = useRef(null);
  const [index, setIndex] = useState(0);

  useEffect(() => {
    const el = scrollerRef.current;
    if (!el) return;
    const onScroll = () => {
      const w = el.clientWidth;
      if (w === 0) return;
      const i = Math.round(el.scrollLeft / w);
      setIndex(i);
    };
    el.addEventListener('scroll', onScroll, { passive: true });
    return () => el.removeEventListener('scroll', onScroll);
  }, [stories.length]);

  if (stories.length === 0) return <EmptyStory />;
  const currentStory = stories[index] || stories[0];
  const currentRoute = getStoryRoute(currentStory);

  const scrollTo = (i) => {
    const el = scrollerRef.current;
    if (!el) return;
    const clamped = Math.max(0, Math.min(stories.length - 1, i));
    el.scrollTo({ left: clamped * el.clientWidth, behavior: 'smooth' });
  };

  return (
    <div className="story-carousel">
      <div className="story-carousel__progress">
        {stories.map((s, i) => (
          <span key={s.key} className={`story-carousel__bar${i === index ? ' active' : ''}`} />
        ))}
      </div>
      <div className="story-carousel__scroller" ref={scrollerRef}>
        {stories.map((s, i) => {
          const Card = CARD_BY_KIND[s.kind] || GenericActivityCard;
          return (
            <div key={s.key} className="story-carousel__slide">
              <Card story={s} onNavigate={onNavigate} countLabel={`${i + 1} / ${stories.length}`} />
            </div>
          );
        })}
      </div>
      {stories.length > 1 && (
        <>
          <button
            type="button"
            className="story-carousel__nav prev"
            onClick={() => scrollTo(index - 1)}
            aria-label="Previous story"
          >
            ‹
          </button>
          <button
            type="button"
            className="story-carousel__nav next"
            onClick={() => scrollTo(index + 1)}
            aria-label="Next story"
          >
            ›
          </button>
        </>
      )}
      <div className="story-carousel__footer">
        <button
          type="button"
          className="story-carousel__footer-btn"
          onClick={() => scrollTo(index - 1)}
          disabled={stories.length <= 1 || index === 0}
        >
          Previous
        </button>
        <button
          type="button"
          className="story-carousel__footer-btn primary"
          onClick={() => onNavigate(currentRoute)}
        >
          View item
        </button>
        <button
          type="button"
          className="story-carousel__footer-btn"
          onClick={() => scrollTo(index + 1)}
          disabled={stories.length <= 1 || index >= stories.length - 1}
        >
          Next
        </button>
      </div>
    </div>
  );
};

export default ActivityStories;
