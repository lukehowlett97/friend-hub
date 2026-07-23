import React, { useEffect, useMemo, useState } from 'react';
import { format, parseISO } from 'date-fns';
import CreatorCard from '../components/Planning/CreatorCard.jsx';
import AddToCalendarButton from '../components/Planning/AddToCalendarButton.jsx';
import EngagementPanel from '../components/Planning/EngagementPanel.jsx';
import {
  createEvent,
  fetchEvents,
  pinHubItem,
  rsvpEvent,
  sendHubItemToChat,
  updateHubItem,
} from '../services/api.js';
import { useAuth } from '../auth/AuthProvider.jsx';
import { openNativeDatePicker } from '../utils/nativeDatePicker.js';
import './FeaturePages.css';

const datetimeLocalValue = (date = new Date()) => {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 16);
};

const eventDate = (event) => (event.starts_at ? parseISO(event.starts_at) : null);

const formatEventDate = (event) => {
  const date = eventDate(event);
  return date ? format(date, 'EEE d MMM yyyy, h:mm a') : 'Time TBC';
};

const EventTime = ({ event, className = 'eyebrow' }) => {
  const date = eventDate(event);
  return date ? (
    <time className={className} dateTime={date.toISOString()}>{formatEventDate(event)}</time>
  ) : (
    <span className={className}>Time TBC</span>
  );
};

const mapsUrl = (location) => `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(location)}`;

const formatDateParts = (event) => {
  const date = eventDate(event);
  if (!date) {
    return {
      weekday: 'TBC',
      day: '--',
      month: 'Time',
      time: 'Time TBC',
      iso: undefined,
    };
  }
  return {
    weekday: format(date, 'EEE'),
    day: format(date, 'd'),
    month: format(date, 'MMM'),
    time: format(date, 'h:mm a'),
    iso: date.toISOString(),
  };
};

const RSVP_OPTIONS = [
  { key: 'yes', label: 'Going', countKey: 'yes_count' },
  { key: 'maybe', label: 'Maybe', countKey: 'maybe_count' },
  { key: 'no', label: 'No', countKey: 'no_count' },
];

const rsvpSummary = (event) => (
  `${event.yes_count || 0} going · ${event.maybe_count || 0} maybe · ${event.no_count || 0} no`
);

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

const EventCard = ({
  event,
  variant = 'upcoming',
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
    <article className={`event-feed-card event-feed-card--${variant}`}>
      {event.cover_photo_url && <img className="event-card-cover event-feed-card__cover" src={event.cover_photo_url} alt="" />}

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
          <CreatorCard creator={event.creator} onNavigate={onNavigate} verb="Host" />
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

      <EngagementPanel targetType="event" targetId={event.id} reactions={event.reactions} commentCount={event.comment_count} onChange={onEventsChanged} />
    </article>
  );
};

const EventsPage = ({ onNavigate }) => {
  const { user } = useAuth();
  const [events, setEvents] = useState([]);
  const [error, setError] = useState(null);
  const [isSaving, setIsSaving] = useState(false);
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [showPastEvents, setShowPastEvents] = useState(false);
  const [form, setForm] = useState({
    title: '',
    starts_at: datetimeLocalValue(),
    location: '',
    description: '',
  });

  const loadEvents = () => {
    fetchEvents()
      .then((data) => {
        setEvents(data.events || []);
        setError(null);
      })
      .catch((err) => setError(err.message));
  };

  useEffect(() => {
    loadEvents();
  }, []);

  const upcomingEvents = useMemo(
    () => events.filter((event) => {
      const date = eventDate(event);
      return !date || date >= new Date();
    }),
    [events],
  );

  const pastEvents = useMemo(
    () => events
      .filter((event) => {
        const date = eventDate(event);
        return date && date < new Date();
      })
      .sort((a, b) => (eventDate(b)?.getTime() || 0) - (eventDate(a)?.getTime() || 0)),
    [events],
  );

  const handleSubmit = async (event) => {
    event.preventDefault();
    setError(null);
    setIsSaving(true);
    try {
      const startsIso = new Date(form.starts_at).toISOString();
      const payload = { ...form, starts_at: startsIso };
      const result = await createEvent(payload);
      setForm({
        title: '',
        starts_at: datetimeLocalValue(new Date(form.starts_at)),
        location: '',
        description: '',
      });
      setIsCreateOpen(false);
      loadEvents();
      if (!result?.event?.id) {
        // Defensive: surface unexpected response shape rather than failing silently.
        setError('Event created but server returned an unexpected response — refresh to see it.');
      }
    } catch (err) {
      // Log so the user can see the underlying cause in dev tools even if the
      // inline banner is scrolled off-screen.
      console.error('createEvent failed', err);
      setError(err.message || 'Failed to create event');
    } finally {
      setIsSaving(false);
    }
  };

  const handleRsvp = async (eventId, response) => {
    try {
      await rsvpEvent(eventId, response);
      loadEvents();
    } catch (err) {
      setError(err.message);
    }
  };

  const togglePin = async (item) => {
    try {
      await pinHubItem(item.id, !item.pinned_to_home);
      loadEvents();
    } catch (err) {
      setError(err.message);
    }
  };

  const sendToChat = async (item) => {
    await sendHubItemToChat(item.id);
    loadEvents();
  };

  const prepareChatMessage = (item) => {
    onNavigate?.(`/chat?draft=${encodeURIComponent(item.short_id || '')}`);
  };

  const archiveEvent = async (event) => {
    if (!event.hub_item?.id) return;
    const confirmed = window.confirm(
      `Delete "${event.title}"?\n\nThis will move the event to the archive instead of permanently deleting it.`,
    );
    if (!confirmed) return;
    try {
      await updateHubItem(event.hub_item.id, { status: 'archived', pinned_to_home: false });
      loadEvents();
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <section className="page feature-page events-page">
      <header className="page-header">
        <h1>Events</h1>
        <p className="page-subtitle">Create plans, RSVP, and share events with chat.</p>
      </header>

      <section className="create-panel">
        <button
          type="button"
          className="create-panel-toggle"
          onClick={() => setIsCreateOpen((value) => !value)}
          aria-expanded={isCreateOpen}
        >
          <span>{isCreateOpen ? 'Close' : 'Create event'}</span>
          <strong>{isCreateOpen ? '×' : '+'}</strong>
        </button>

        {isCreateOpen && (
          <form className="feature-form create-panel-form" onSubmit={handleSubmit}>
            <input
              value={form.title}
              onChange={(event) => setForm({ ...form, title: event.target.value })}
              placeholder="Event title"
              required
            />
            <input
              type="datetime-local"
              value={form.starts_at}
              onChange={(event) => setForm({ ...form, starts_at: event.target.value })}
              onClick={openNativeDatePicker}
              required
            />
            <textarea
              value={form.description}
              onChange={(event) => setForm({ ...form, description: event.target.value })}
              placeholder="Details"
              rows="3"
            />
            <input
              value={form.location}
              onChange={(event) => setForm({ ...form, location: event.target.value })}
              placeholder="Location"
            />
            {error && <div className="inline-error">{error}</div>}
            <button type="submit" disabled={isSaving}>{isSaving ? 'Creating...' : 'Create Event'}</button>
          </form>
        )}
      </section>

      {error && !isCreateOpen && <div className="inline-error">{error}</div>}

      <section className="activity-section">
        <div className="section-heading">
          <h2>Upcoming Events</h2>
          <span>{upcomingEvents.length} upcoming</span>
        </div>
        <div className="feature-list">
          {upcomingEvents.length > 0
            ? upcomingEvents.map((event) => (
              <EventCard
                key={event.id}
                event={event}
                user={user}
                onNavigate={onNavigate}
                onRsvp={handleRsvp}
                onPin={togglePin}
                onSendToChat={sendToChat}
                onPrepareChatMessage={prepareChatMessage}
                onArchive={archiveEvent}
                onEventsChanged={loadEvents}
              />
            ))
            : <div className="placeholder-panel compact">No events scheduled</div>}
        </div>
      </section>

      {pastEvents.length > 0 && (
        <section className="activity-section past-events-section">
          <div className="section-heading">
            <div>
              <h2>Past Events</h2>
              <span>{pastEvents.length} past</span>
            </div>
            <button
              type="button"
              className="past-events-toggle"
              onClick={() => setShowPastEvents((value) => !value)}
              aria-expanded={showPastEvents}
            >
              {showPastEvents ? 'Hide past' : 'Show past'}
            </button>
          </div>
          {showPastEvents && (
            <div className="feature-list past-events-list">
              {pastEvents.map((event) => (
                <EventCard
                  key={event.id}
                  event={event}
                  variant="past"
                  user={user}
                  onNavigate={onNavigate}
                  onRsvp={handleRsvp}
                  onPin={togglePin}
                  onSendToChat={sendToChat}
                  onPrepareChatMessage={prepareChatMessage}
                  onArchive={archiveEvent}
                  onEventsChanged={loadEvents}
                />
              ))}
            </div>
          )}
        </section>
      )}
    </section>
  );
};

export default EventsPage;
