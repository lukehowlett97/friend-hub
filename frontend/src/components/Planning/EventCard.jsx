import React, { useState } from 'react';
import { format, parseISO } from 'date-fns';
import CreatorCard from './CreatorCard.jsx';
import AddToCalendarButton from './AddToCalendarButton.jsx';
import EngagementPanel from './EngagementPanel.jsx';

// ── Shared event helpers (used by Events + Calendar pages) ──────────────────
export const eventDate = (event) => (event?.starts_at ? parseISO(event.starts_at) : null);

export const mapsUrl = (location) =>
  `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(location)}`;

const formatEventDate = (event) => {
  const date = eventDate(event);
  return date ? format(date, 'EEE d MMM yyyy, h:mm a') : 'Time TBC';
};

export const EventTime = ({ event, className = 'eyebrow' }) => {
  const date = eventDate(event);
  return date ? (
    <time className={className} dateTime={date.toISOString()}>{formatEventDate(event)}</time>
  ) : (
    <span className={className}>Time TBC</span>
  );
};

const formatDateParts = (event) => {
  const date = eventDate(event);
  if (!date) {
    return { weekday: 'TBC', day: '--', month: 'Time', time: 'Time TBC', iso: undefined };
  }
  return {
    weekday: format(date, 'EEE'),
    day: format(date, 'd'),
    month: format(date, 'MMM'),
    time: format(date, 'h:mm a'),
    iso: date.toISOString(),
  };
};

export const RSVP_OPTIONS = [
  { key: 'yes', label: 'Going', countKey: 'yes_count' },
  { key: 'maybe', label: 'Maybe', countKey: 'maybe_count' },
  { key: 'no', label: 'No', countKey: 'no_count' },
];

export const rsvpSummary = (event) =>
  `${event.yes_count || 0} going · ${event.maybe_count || 0} maybe · ${event.no_count || 0} no`;

// ── Quick actions (pin / send-to-chat / overflow) ───────────────────────────
const EventQuickActions = ({ item, canEdit, canDelete, onPin, onSendToChat, onPrepareChatMessage, onEdit, onDelete }) => {
  const [isSending, setIsSending] = useState(false);
  const [justSent, setJustSent] = useState(false);
  const [sendError, setSendError] = useState(null);
  const [isMenuOpen, setIsMenuOpen] = useState(false);

  if (!item) return null;

  const alreadySent = !justSent && !!item.sent_to_chat_at;

  const handleSendToChat = async () => {
    if (isSending) return;
    if (onPrepareChatMessage) {
      onPrepareChatMessage(item);
      return;
    }
    setIsSending(true);
    setSendError(null);
    try {
      await onSendToChat?.(item);
      setJustSent(true);
      window.setTimeout(() => setJustSent(false), 3000);
    } catch {
      setSendError('Failed to send');
    } finally {
      setIsSending(false);
    }
  };

  const sendTitle = alreadySent ? 'Send again to chat' : 'Send to chat';

  return (
    <div className="event-card-actions" aria-label="Event quick actions">
      <button
        type="button"
        className={`event-icon-btn${item.pinned_to_home ? ' active' : ''}`}
        onClick={() => onPin?.(item)}
        aria-label={`${item.pinned_to_home ? 'Unpin' : 'Pin'} ${item.short_id || 'event'}`}
        aria-pressed={!!item.pinned_to_home}
        title={item.pinned_to_home ? 'Unpin' : 'Pin'}
      >
        <span aria-hidden="true">📌</span>
      </button>
      <button
        type="button"
        className={`event-icon-btn${justSent ? ' active' : ''}`}
        onClick={handleSendToChat}
        disabled={isSending || justSent}
        aria-label={`${sendTitle} ${item.short_id || 'event'}`}
        title={justSent ? 'Sent' : sendTitle}
      >
        <span aria-hidden="true">{justSent ? '✓' : '↗'}</span>
      </button>
      <div className="event-overflow">
        <button
          type="button"
          className="event-icon-btn"
          onClick={() => setIsMenuOpen((value) => !value)}
          aria-label={`More actions for ${item.short_id || 'event'}`}
          aria-expanded={isMenuOpen}
          title="More actions"
        >
          <span aria-hidden="true">⋯</span>
        </button>
        {isMenuOpen && (
          <div className="event-overflow-menu">
            {canEdit && <button type="button" onClick={() => { setIsMenuOpen(false); onEdit?.(); }}>Edit event</button>}
            {canDelete && <button type="button" className="danger" onClick={() => { setIsMenuOpen(false); onDelete?.(); }}>Delete event</button>}
            {!canEdit && !canDelete && <span>No extra actions</span>}
          </div>
        )}
      </div>
      {sendError && <span className="event-action-error" role="status">{sendError}</span>}
    </div>
  );
};

// ── EventCard ───────────────────────────────────────────────────────────────
// variant: 'upcoming' | 'past'
// compact: tighter layout for agenda lists (hides cover + creator row)
const EventCard = ({
  event,
  variant = 'upcoming',
  compact = false,
  user,
  onNavigate,
  onRsvp,
  onPin,
  onSendToChat,
  onPrepareChatMessage,
  onArchive,
  onEventsChanged,
}) => {
  const currentUserResponse = event.rsvps?.find((rsvp) => rsvp.user?.id === user?.id)?.response;
  const dateParts = formatDateParts(event);
  const isPast = variant === 'past';
  const canManageEvent = user?.role === 'owner' || user?.role === 'admin' || event.creator?.id === user?.id;

  return (
    <article className={`event-feed-card event-feed-card--${variant}${compact ? ' event-feed-card--compact' : ''}`}>
      {!compact && event.cover_photo_url && (
        <img className="event-card-cover event-feed-card__cover" src={event.cover_photo_url} alt="" />
      )}

      <div className="event-feed-card__top">
        <time className="event-date-block" dateTime={dateParts.iso}>
          <span>{dateParts.weekday}</span>
          <strong>{dateParts.day}</strong>
          <em>{dateParts.month}</em>
          <small>{dateParts.time}</small>
        </time>
        <EventQuickActions
          item={event.hub_item}
          canEdit={canManageEvent}
          canDelete={canManageEvent}
          onPin={onPin}
          onSendToChat={onSendToChat}
          onPrepareChatMessage={onPrepareChatMessage}
          onEdit={() => onNavigate(`/events/${event.id}`)}
          onDelete={() => onArchive(event)}
        />
      </div>

      <div className="event-feed-card__body">
        <div className="event-title-row">
          <EventTime event={event} className="event-time-text" />
          <h2>{event.title}</h2>
        </div>

        {event.location && (
          <a className="event-location-link" href={mapsUrl(event.location)} target="_blank" rel="noreferrer">
            <span aria-hidden="true">⌖</span>
            <span>{event.location}</span>
          </a>
        )}

        {event.description && <p className="event-description">{event.description}</p>}

        <div className="event-social-row">
          {!compact && <CreatorCard creator={event.creator} onNavigate={onNavigate} verb="Host" />}
          <span className="event-rsvp-summary">{rsvpSummary(event)}</span>
        </div>
      </div>

      <div className="event-card-primary-row">
        <button type="button" className="event-view-btn" onClick={() => onNavigate(`/events/${event.id}`)}>
          View event
        </button>
        <AddToCalendarButton event={event} className="add-calendar--secondary" />
      </div>

      {!isPast && (
        <div className="event-rsvp-actions event-rsvp-actions--segmented" aria-label="RSVP">
          {RSVP_OPTIONS.map((option) => (
            <button
              key={option.key}
              type="button"
              className={currentUserResponse === option.key ? 'active' : ''}
              onClick={() => onRsvp(event.id, option.key)}
              aria-pressed={currentUserResponse === option.key}
            >
              <span>{option.label}</span>
              <strong>{event[option.countKey] || 0}</strong>
            </button>
          ))}
        </div>
      )}

      {!compact && (
        <EngagementPanel targetType="event" targetId={event.id} reactions={event.reactions} commentCount={event.comment_count} onChange={onEventsChanged} />
      )}
    </article>
  );
};

export default EventCard;
