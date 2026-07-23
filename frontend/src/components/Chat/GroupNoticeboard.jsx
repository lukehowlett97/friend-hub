import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useAuth } from '../../auth/AuthProvider.jsx';
import { updateGroupNotice } from '../../services/api.js';
import { navigate as navigateTo } from '../../utils/navigate.js';
import { buildChatMessageHref } from '../../utils/chatLinks.js';
import './GroupNoticeboard.css';

// ── Helpers ──────────────────────────────────────────────────────────────────

function getItemType(item) {
  return item.type || item.source_type || 'item';
}

function getItemTitle(item) {
  const d = item.detail || {};
  if ((item.type || item.source_type) === 'message') {
    const body = (item.body || '').trim();
    return body || `Message from ${item.sender_nickname || item.title || 'a member'}`;
  }
  return d.question || d.title || item.question || item.title || 'Pinned item';
}

function getItemShortId(item) {
  return item.short_id || item.hub_item?.short_id || null;
}

function formatDate(value) {
  if (!value) return null;
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return null;
  return new Intl.DateTimeFormat(undefined, {
    weekday: 'short', month: 'short', day: 'numeric',
    hour: 'numeric', minute: '2-digit',
  }).format(d);
}

function getItemMeta(item) {
  const d = item.detail || {};
  const type = getItemType(item);
  if (type === 'message') {
    const who = item.sender_nickname || item.title || 'Member';
    const when = formatDate(item.created_at);
    return when ? `${who} · ${when}` : who;
  }
  if (type === 'event') return formatDate(d.starts_at || item.event_start_at);
  if (type === 'poll') {
    const total = d.total_votes ?? (d.options || []).reduce((s, o) => s + (o.vote_count || 0), 0);
    return `${total || 0} vote${total === 1 ? '' : 's'}`;
  }
  return formatDate(item.due_at || item.event_start_at || item.created_at);
}

function getItemStatus(item) {
  const d = item.detail || {};
  const type = getItemType(item);
  if (type === 'event') {
    const start = d.starts_at ? new Date(d.starts_at) : null;
    const end = d.ends_at ? new Date(d.ends_at) : null;
    const now = new Date();
    if (start && end && now >= start && now <= end) return 'LIVE';
    if (start && start < now) return 'past';
    if (start) {
      const diff = start - now;
      if (diff < 86400000) return 'today';
      if (diff < 604800000) return 'soon';
    }
  }
  if (type === 'poll') {
    if (d.is_closed) return 'CLOSED';
    if (d.is_live) return 'LIVE';
  }
  if (type === 'reminder') {
    if (item.is_completed) return 'done';
    if (item.due_at) {
      const diff = new Date(item.due_at) - new Date();
      if (diff < 0) return 'overdue';
      if (diff < 86400000) return 'due soon';
    }
  }
  return null;
}

function getItemRoute(item) {
  const type = getItemType(item);
  if (type === 'event') {
    const id = item.source_id || item.hub_item?.source_id || item.id;
    return `/events/${id}`;
  }
  if (type === 'poll') return '/polls';
  if (type === 'reminder') return '/reminders';
  if (type === 'idea') return '/ideas';
  if (type === 'note') return `/notes/${item.source_id || item.hub_item?.source_id || item.id}`;
  if (type === 'message') return buildChatMessageHref(item.message_id);
  return '/items';
}

const TYPE_LABELS = {
  event: 'Event',
  poll: 'Poll',
  reminder: 'Reminder',
  idea: 'Idea',
  photo: 'Photo',
  note: 'Note',
  message: 'Message',
};

const STATUS_CLASS = {
  LIVE: 'nb-status--live',
  CLOSED: 'nb-status--closed',
  past: 'nb-status--past',
  today: 'nb-status--today',
  soon: 'nb-status--soon',
  done: 'nb-status--done',
  overdue: 'nb-status--overdue',
  'due soon': 'nb-status--soon',
};

// ── PinnedNotice ──────────────────────────────────────────────────────────────

const PinnedNotice = ({ notice, isAdmin, onSaved }) => {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(notice || '');
  const [saving, setSaving] = useState(false);
  const textareaRef = useRef(null);

  useEffect(() => {
    if (editing && textareaRef.current) {
      textareaRef.current.focus();
      textareaRef.current.setSelectionRange(draft.length, draft.length);
    }
  }, [editing]);

  const handleSave = async () => {
    setSaving(true);
    try {
      const result = await updateGroupNotice(draft.trim());
      onSaved(result.notice || '');
      setEditing(false);
    } catch {
      // keep editing open on error
    } finally {
      setSaving(false);
    }
  };

  const handleCancel = () => {
    setDraft(notice || '');
    setEditing(false);
  };

  if (editing) {
    return (
      <div className="nb-notice nb-notice--editing">
        <textarea
          ref={textareaRef}
          className="nb-notice__input"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Add a group notice… e.g. Pub Thursday at 8"
          maxLength={280}
          rows={3}
          onKeyDown={(e) => {
            if (e.key === 'Escape') handleCancel();
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleSave();
          }}
        />
        <div className="nb-notice__actions">
          <button type="button" className="nb-notice__save" onClick={handleSave} disabled={saving}>
            {saving ? 'Saving…' : 'Save'}
          </button>
          <button type="button" className="nb-notice__cancel" onClick={handleCancel}>
            Cancel
          </button>
        </div>
      </div>
    );
  }

  if (notice) {
    return (
      <div className="nb-notice">
        <span className="nb-notice__pin" aria-hidden="true">📌</span>
        <p className="nb-notice__text">{notice}</p>
        {isAdmin && (
          <button
            type="button"
            className="nb-notice__edit"
            aria-label="Edit group notice"
            onClick={() => { setDraft(notice); setEditing(true); }}
          >
            ✏️
          </button>
        )}
      </div>
    );
  }

  if (isAdmin) {
    return (
      <button
        type="button"
        className="nb-notice nb-notice--empty"
        onClick={() => { setDraft(''); setEditing(true); }}
      >
        <span aria-hidden="true">📌</span>
        Add a group notice
      </button>
    );
  }

  return null;
};

// ── PinnedItemCard ────────────────────────────────────────────────────────────

const PinnedItemCard = ({ item, onDrillDown, onNavigate }) => {
  const type = getItemType(item);
  const d = item.detail || {};
  const title = getItemTitle(item);
  const shortId = getItemShortId(item);
  const meta = getItemMeta(item);
  const status = getItemStatus(item);
  const coverUrl = d.cover_photo_url || item.cover_photo_url;
  const coverX = d.cover_photo_position_x ?? item.cover_photo_position_x ?? 50;
  const coverY = d.cover_photo_position_y ?? item.cover_photo_position_y ?? 50;
  const pollOptions = type === 'poll' ? (d.options || []) : [];
  const totalVotes = type === 'poll'
    ? (d.total_votes ?? pollOptions.reduce((s, o) => s + (o.vote_count || 0), 0))
    : 0;

  const handleClick = () => {
    if (type === 'event' || type === 'message') {
      onNavigate(getItemRoute(item));
    } else {
      onDrillDown(item);
    }
  };

  const yesCount = d.yes_count ?? 0;
  const maybeCount = d.maybe_count ?? 0;
  const hasRsvp = type === 'event' && (d.yes_count !== undefined);

  return (
    <button
      type="button"
      className={`nb-card nb-card--${type}${coverUrl ? ' nb-card--has-cover' : ''}`}
      onClick={handleClick}
    >
      {coverUrl && (
        <div className="nb-card__cover-wrap">
          <img
            className="nb-card__cover"
            src={coverUrl}
            alt=""
            style={{ objectPosition: `${coverX}% ${coverY}%` }}
          />
          <div className="nb-card__cover-overlay">
            <div className="nb-card__cover-topline">
              <span className="nb-card__type nb-card__type--on-cover">
                {shortId ? `${shortId} · ` : ''}{TYPE_LABELS[type] || type}
              </span>
              {status && (
                <span className={`nb-status ${STATUS_CLASS[status] || ''}`}>{status}</span>
              )}
            </div>
            <strong className="nb-card__title nb-card__title--on-cover">{title}</strong>
            {meta && <span className="nb-card__meta nb-card__meta--on-cover">{meta}</span>}
            {hasRsvp && (
              <div className="nb-card__rsvp">
                <span className="nb-card__rsvp-yes">✓ {yesCount} going</span>
                {maybeCount > 0 && <span className="nb-card__rsvp-maybe">~ {maybeCount} maybe</span>}
              </div>
            )}
          </div>
        </div>
      )}

      {!coverUrl && (
        <div className="nb-card__body">
          <div className="nb-card__topline">
            <span className="nb-card__type">
              {shortId ? `${shortId} · ` : ''}{TYPE_LABELS[type] || type}
            </span>
            {status && (
              <span className={`nb-status ${STATUS_CLASS[status] || ''}`}>{status}</span>
            )}
          </div>
          <strong className="nb-card__title">{title}</strong>
          {meta && <span className="nb-card__meta">{meta}</span>}

          {type === 'event' && (
            <div className="nb-card__detail">
              {d.location && <span>📍 {d.location}</span>}
              {hasRsvp && (
                <span>{yesCount} going · {maybeCount} maybe</span>
              )}
            </div>
          )}

          {type === 'poll' && pollOptions.length > 0 && (
            <div className="nb-card__poll">
              {pollOptions.slice(0, 3).map((opt) => {
                const votes = opt.vote_count || 0;
                const pct = totalVotes ? Math.round((votes / totalVotes) * 100) : 0;
                return (
                  <span key={opt.id || opt.label} className="nb-card__poll-opt">
                    <span className="nb-card__poll-fill" style={{ width: `${pct}%` }} />
                    <span className="nb-card__poll-label">{opt.label}</span>
                    <strong>{votes}</strong>
                  </span>
                );
              })}
            </div>
          )}

          {type === 'reminder' && d.description && (
            <p className="nb-card__desc">{d.description}</p>
          )}
          {type === 'idea' && (item.body || d.description) && (
            <p className="nb-card__desc">{item.body || d.description}</p>
          )}
        </div>
      )}
    </button>
  );
};

// ── PinnedSection ─────────────────────────────────────────────────────────────

const PinnedSection = ({ type, items, onDrillDown, onNavigate }) => {
  const [collapsed, setCollapsed] = useState(false);
  const label = TYPE_LABELS[type] || type;
  const plural = label === 'Reminder' ? 'Reminders' : `${label}s`;

  return (
    <section className="nb-section">
      {items.length > 1 && (
        <button
          type="button"
          className="nb-section__header"
          aria-expanded={!collapsed}
          onClick={() => setCollapsed((c) => !c)}
        >
          <span className="nb-section__title">{plural}</span>
          <span className="nb-section__count">{items.length}</span>
          <span className="nb-section__chevron" aria-hidden="true">{collapsed ? '›' : '‹'}</span>
        </button>
      )}
      {!collapsed && (
        <div className="nb-section__list">
          {items.map((item) => (
            <PinnedItemCard key={item.id} item={item} onDrillDown={onDrillDown} onNavigate={onNavigate} />
          ))}
        </div>
      )}
    </section>
  );
};

// ── PinnedItemDetail ──────────────────────────────────────────────────────────

const PinnedItemDetail = ({ item, onBack, onNavigate }) => {
  const type = getItemType(item);
  const d = item.detail || {};
  const title = getItemTitle(item);
  const shortId = getItemShortId(item);
  const status = getItemStatus(item);
  const coverUrl = d.cover_photo_url || item.cover_photo_url;
  const coverX = d.cover_photo_position_x ?? item.cover_photo_position_x ?? 50;
  const coverY = d.cover_photo_position_y ?? item.cover_photo_position_y ?? 50;
  const pollOptions = type === 'poll' ? (d.options || []) : [];
  const totalVotes = type === 'poll'
    ? (d.total_votes ?? pollOptions.reduce((s, o) => s + (o.vote_count || 0), 0))
    : 0;
  const route = getItemRoute(item);

  return (
    <div className="nb-detail">
      {coverUrl && (
        <img
          className="nb-detail__cover"
          src={coverUrl}
          alt=""
          style={{ objectPosition: `${coverX}% ${coverY}%` }}
        />
      )}
      <div className="nb-detail__content">
        <div className="nb-detail__topline">
          <span className="nb-card__type">
            {shortId ? `${shortId} · ` : ''}{TYPE_LABELS[type] || type}
          </span>
          {status && (
            <span className={`nb-status ${STATUS_CLASS[status] || ''}`}>{status}</span>
          )}
        </div>

        <h3 className="nb-detail__title">{title}</h3>

        {type === 'event' && (
          <div className="nb-detail__event">
            {d.starts_at && (
              <div className="nb-detail__row">
                <span>🗓</span>
                <span>{formatDate(d.starts_at)}</span>
              </div>
            )}
            {d.location && (
              <div className="nb-detail__row">
                <span>📍</span>
                <span>{d.location}</span>
              </div>
            )}
            {d.description && <p className="nb-detail__desc">{d.description}</p>}
            {(d.yes_count !== undefined) && (
              <div className="nb-detail__rsvp">
                <span className="nb-detail__rsvp-yes">{d.yes_count || 0} going</span>
                <span className="nb-detail__rsvp-maybe">{d.maybe_count || 0} maybe</span>
                <span className="nb-detail__rsvp-no">{d.no_count || 0} can't go</span>
              </div>
            )}
          </div>
        )}

        {type === 'poll' && (
          <div className="nb-detail__poll">
            {d.description && <p className="nb-detail__desc">{d.description}</p>}
            <div className="nb-detail__poll-opts">
              {pollOptions.map((opt) => {
                const votes = opt.vote_count || 0;
                const pct = totalVotes ? Math.round((votes / totalVotes) * 100) : 0;
                return (
                  <div key={opt.id || opt.label} className="nb-detail__poll-opt">
                    <div className="nb-detail__poll-bar">
                      <div className="nb-detail__poll-fill" style={{ width: `${pct}%` }} />
                    </div>
                    <div className="nb-detail__poll-meta">
                      <span>{opt.label}</span>
                      <strong>{votes} ({pct}%)</strong>
                    </div>
                  </div>
                );
              })}
            </div>
            <p className="nb-detail__poll-total">{totalVotes} total vote{totalVotes !== 1 ? 's' : ''}</p>
          </div>
        )}

        {type === 'reminder' && (
          <div className="nb-detail__reminder">
            {d.description && <p className="nb-detail__desc">{d.description}</p>}
            {item.due_at && (
              <div className="nb-detail__row">
                <span>⏰</span>
                <span>{formatDate(item.due_at)}</span>
              </div>
            )}
          </div>
        )}

        {type === 'idea' && (
          <div className="nb-detail__idea">
            {(item.body || d.description) && (
              <p className="nb-detail__desc">{item.body || d.description}</p>
            )}
          </div>
        )}
      </div>

      <button
        type="button"
        className="nb-detail__open-btn"
        onClick={() => { onNavigate(route); }}
      >
        Open full page →
      </button>
    </div>
  );
};

// ── GroupNoticeboard (main) ───────────────────────────────────────────────────

const SECTION_ORDER = ['message', 'event', 'poll', 'reminder', 'idea', 'photo', 'note'];

const GroupNoticeboard = ({
  open,
  onlineUsers,
  pinnedItems,
  loading,
  groupNotice,
  onNoticeChange,
  onClose,
}) => {
  const { user } = useAuth();
  const isAdmin = user?.is_admin;
  const [drillItem, setDrillItem] = useState(null);
  const [isVisible, setIsVisible] = useState(false);
  const [isDrilling, setIsDrilling] = useState(false);
  const panelRef = useRef(null);
  const closeButtonRef = useRef(null);
  const triggerRef = useRef(null);

  // Open/close animation
  useEffect(() => {
    if (open) {
      requestAnimationFrame(() => setIsVisible(true));
    } else {
      setIsVisible(false);
      setDrillItem(null);
    }
  }, [open]);

  // Escape to close
  useEffect(() => {
    if (!open) return undefined;
    const handleKey = (e) => {
      if (e.key === 'Escape') {
        if (drillItem) {
          setDrillItem(null);
        } else {
          onClose();
        }
      }
    };
    document.addEventListener('keydown', handleKey);
    return () => document.removeEventListener('keydown', handleKey);
  }, [open, drillItem, onClose]);

  // Focus trap
  useEffect(() => {
    if (open && closeButtonRef.current) {
      closeButtonRef.current.focus();
    }
  }, [open]);

  const handleDrillDown = useCallback((item) => {
    setIsDrilling(true);
    setTimeout(() => {
      setDrillItem(item);
      setIsDrilling(false);
    }, 140);
  }, []);

  const handleBack = useCallback(() => {
    setIsDrilling(true);
    setTimeout(() => {
      setDrillItem(null);
      setIsDrilling(false);
    }, 140);
  }, []);

  const handleNavigate = useCallback((path) => {
    onClose();
    navigateTo(path);
  }, [onClose]);

  if (!open && !isVisible) return null;

  // Group pinned items by type
  const grouped = {};
  for (const item of pinnedItems) {
    const type = getItemType(item);
    if (!grouped[type]) grouped[type] = [];
    grouped[type].push(item);
  }
  const sections = SECTION_ORDER.filter((t) => grouped[t]?.length > 0);
  const totalPinned = pinnedItems.length;

  return (
    <div
      className={`nb-backdrop${isVisible ? ' nb-backdrop--visible' : ''}`}
      role="presentation"
      onClick={onClose}
    >
      <aside
        ref={panelRef}
        className={`nb-panel${isVisible ? ' nb-panel--visible' : ''}`}
        role="dialog"
        aria-modal="true"
        aria-label="Group noticeboard"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="nb-header">
          <div className="nb-header__left">
            {drillItem ? (
              <button
                type="button"
                className="nb-header__back"
                onClick={handleBack}
                aria-label="Back to noticeboard"
              >
                ‹ Back
              </button>
            ) : (
              <div>
                <h2 className="nb-header__title">Noticeboard</h2>
                <p className="nb-header__sub">
                  {onlineUsers.length > 0 && (
                    <span>{onlineUsers.length} online · </span>
                  )}
                  {totalPinned > 0
                    ? `${totalPinned} pinned item${totalPinned !== 1 ? 's' : ''}`
                    : 'Nothing pinned yet'}
                </p>
              </div>
            )}
          </div>
          <button
            ref={closeButtonRef}
            type="button"
            className="nb-header__close"
            onClick={onClose}
            aria-label="Close noticeboard"
          >
            ×
          </button>
        </div>

        {/* Content */}
        <div className={`nb-content${isDrilling ? ' nb-content--transitioning' : ''}`}>
          {drillItem ? (
            <PinnedItemDetail
              item={drillItem}
              onBack={handleBack}
              onNavigate={handleNavigate}
            />
          ) : (
            <>
              {/* Notice area */}
              <PinnedNotice
                notice={groupNotice}
                isAdmin={isAdmin}
                onSaved={onNoticeChange}
              />

              {/* Online users */}
              {onlineUsers.length > 0 && (
                <div className="nb-online">
                  <span className="nb-online__label">Online now</span>
                  <div className="nb-online__chips">
                    {onlineUsers.slice(0, 10).map((m) => (
                      <span key={m.session_id || m.nickname} className="nb-online__chip">
                        {m.nickname || 'Friend'}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Pinned sections */}
              {loading ? (
                <div className="nb-empty">
                  <p>Loading pinned items…</p>
                </div>
              ) : sections.length > 0 ? (
                <div className="nb-sections">
                  {sections.map((type) => (
                    <PinnedSection
                      key={type}
                      type={type}
                      items={grouped[type]}
                      onDrillDown={handleDrillDown}
                      onNavigate={handleNavigate}
                    />
                  ))}
                </div>
              ) : (
                <div className="nb-empty">
                  <span className="nb-empty__icon" aria-hidden="true">📌</span>
                  <strong>Nothing pinned yet</strong>
                  <p>Pin events, polls or reminders so the group can find them quickly.</p>
                </div>
              )}
            </>
          )}
        </div>
      </aside>
    </div>
  );
};

export default GroupNoticeboard;
