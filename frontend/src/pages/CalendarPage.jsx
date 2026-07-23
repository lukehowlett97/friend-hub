import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  addDays,
  addMonths,
  endOfDay,
  format,
  isSameDay,
  isSameMonth,
  isValid,
  parseISO,
  startOfDay,
  startOfMonth,
  startOfWeek,
  subMonths,
} from 'date-fns';
import {
  fetchEvents,
  fetchMessages,
  fetchPhotos,
  pinHubItem,
  rsvpEvent,
  sendHubItemToChat,
} from '../services/api';
import EngagementPanel from '../components/Planning/EngagementPanel.jsx';
import HubItemCardMeta from '../components/Planning/HubItemCardMeta.jsx';
import PhotoModal from '../components/Photos/PhotoModal.jsx';
import { buildChatMessageHref } from '../utils/chatLinks.js';
import './FeaturePages.css';

const CALENDAR_MESSAGE_LIMIT = 20000;
const CALENDAR_PHOTO_LIMIT = 2000;
const TIMELINE_FILTERS = [
  { key: 'all', label: 'All' },
  { key: 'chat', label: 'Chat' },
  { key: 'photos', label: 'Photos' },
  { key: 'plans', label: 'Plans' },
];

const parseDate = (value) => {
  if (!value) return null;
  const date = parseISO(value);
  return isValid(date) ? date : null;
};

const toEventDate = (event) => parseDate(event.starts_at);
const toMessageDate = (message) => parseDate(message.created_at);
const toPhotoDate = (photo) => parseDate(photo.created_at);

const formatEventTime = (event) => {
  const date = toEventDate(event);
  return date ? format(date, 'h:mm a') : 'Time TBC';
};

const mapsUrl = (location) => `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(location)}`;

const buildCalendarDays = (monthDate) => {
  const gridStart = startOfWeek(startOfMonth(monthDate));
  return Array.from({ length: 42 }, (_, index) => addDays(gridStart, index));
};

const getVisibleRange = (days) => ({
  start_at: startOfDay(days[0]).toISOString(),
  end_at: endOfDay(days[days.length - 1]).toISOString(),
});

const getPhotoLabel = (photo) => photo.caption || photo.original_filename || 'Shared photo';

const activityCountsForDate = (activityByDay, date) => {
  const day = activityByDay.find((entry) => isSameDay(entry.date, date));
  return {
    messages: day?.messages.length || 0,
    photos: day?.photos.length || 0,
    plans: day?.events.length || 0,
  };
};

const MobileWeekStrip = ({ selectedDate, activityByDay, onSelectDate }) => {
  const weekStart = startOfWeek(selectedDate);
  const weekDays = Array.from({ length: 7 }, (_, index) => addDays(weekStart, index));

  return (
    <div className="mobile-week-strip" aria-label="Selected week">
      {weekDays.map((date) => {
        const counts = activityCountsForDate(activityByDay, date);
        const isSelected = isSameDay(date, selectedDate);
        const isToday = isSameDay(date, new Date());

        return (
          <button
            type="button"
            key={date.toISOString()}
            className={[
              'mobile-week-day',
              isSelected ? 'is-selected' : '',
              isToday ? 'is-today' : '',
            ].filter(Boolean).join(' ')}
            onClick={() => onSelectDate(date)}
            aria-pressed={isSelected}
            aria-label={`${format(date, 'EEEE, MMM d')}: ${counts.messages} messages, ${counts.photos} photos, ${counts.plans} plans`}
          >
            <span className="mobile-week-day__weekday">{format(date, 'EEEEE')}</span>
            <span className="mobile-week-day__number">{format(date, 'd')}</span>
            <span className="mobile-week-day__signals" aria-hidden="true">
              {counts.messages > 0 && <span className="signal signal--messages">{counts.messages > 9 ? '9+' : counts.messages}</span>}
              {counts.photos > 0 && <span className="signal signal--photos">{counts.photos > 9 ? '9+' : counts.photos}</span>}
              {counts.plans > 0 && <span className="signal signal--plans">{counts.plans > 9 ? '9+' : counts.plans}</span>}
            </span>
          </button>
        );
      })}
    </div>
  );
};

const DaySummaryHeader = ({
  selectedDate,
  counts,
  onPreviousDay,
  onNextDay,
  onMessage,
  onPlan,
  onPhoto,
}) => (
  <div className="day-summary-header">
    <div className="day-summary-heading-row">
      <button type="button" className="day-nav-button" onClick={onPreviousDay} aria-label="Previous day">
        ←
      </button>
      <div className="day-summary-title">
        <span>{format(selectedDate, 'EEEE')}</span>
        <h2>{format(selectedDate, 'MMMM d, yyyy')}</h2>
      </div>
      <button type="button" className="day-nav-button" onClick={onNextDay} aria-label="Next day">
        →
      </button>
    </div>
    <div className="day-summary-counts" aria-label="Day activity counts">
      <span>{counts.messages} messages</span>
      <span>{counts.photos} photos</span>
      <span>{counts.plans} plans</span>
    </div>
    <div className="day-summary-actions">
      <button type="button" onClick={onMessage}>Message</button>
      <button type="button" onClick={onPlan}>Plan</button>
      <button type="button" onClick={onPhoto}>Photo</button>
    </div>
  </div>
);

const TimelineFilter = ({ value, onChange, counts }) => (
  <div className="timeline-filter" aria-label="Timeline filter">
    {TIMELINE_FILTERS.map((filter) => {
      const count = filter.key === 'all'
        ? counts.messages + counts.photos + counts.plans
        : filter.key === 'chat'
          ? counts.messages
          : filter.key === 'photos'
            ? counts.photos
            : counts.plans;

      return (
        <button
          key={filter.key}
          type="button"
          className={value === filter.key ? 'is-active' : ''}
          onClick={() => onChange(filter.key)}
        >
          {filter.label}
          <span>{count}</span>
        </button>
      );
    })}
  </div>
);

const MobilePlanCard = ({ event, onNavigate, onRsvp, onPin, onSendToChat, onPrepareChatMessage, onEventsChanged }) => (
  <article className="day-event-card mobile-plan-card">
    {event.cover_photo_url && <img className="event-card-cover" src={event.cover_photo_url} alt="" />}
    <div className="mobile-plan-card__main">
      <div className="mobile-plan-card__meta">
        <span>{event.hub_item?.type || 'Event'}</span>
        <strong>{formatEventTime(event)}</strong>
      </div>
      <h3>{event.title}</h3>
      {event.description && <p>{event.description}</p>}
      {event.location && (
        <a className="map-link" href={mapsUrl(event.location)} target="_blank" rel="noreferrer">
          {event.location}
        </a>
      )}
      <span className="day-event-rsvps">{event.yes_count} yes · {event.maybe_count || 0} maybe · {event.no_count} no</span>
    </div>

    <div className="mobile-plan-card__actions">
      <button type="button" className="mobile-plan-card__open" onClick={() => onNavigate(`/events/${event.id}`)}>
        Open
      </button>
      <button type="button" onClick={() => onRsvp(event.id, 'yes')}>Yes</button>
      <button type="button" onClick={() => onRsvp(event.id, 'maybe')}>Maybe</button>
      <button type="button" onClick={() => onRsvp(event.id, 'no')}>No</button>
    </div>

    <div className="mobile-plan-card__secondary">
      <HubItemCardMeta item={event.hub_item} onPin={onPin} onSendToChat={onSendToChat} onPrepareChatMessage={onPrepareChatMessage} />
    </div>
    <EngagementPanel targetType="event" targetId={event.id} reactions={event.reactions} commentCount={event.comment_count} onChange={onEventsChanged} />
  </article>
);

const buildTimelineItems = (messages, photos, events) => {
  const items = [
    ...messages.map((message, index) => ({
      id: `chat-${message.id}`,
      type: 'chat',
      date: toMessageDate(message),
      stableIndex: index,
      data: message,
    })),
    ...photos.map((photo, index) => ({
      id: `photo-${photo.id}`,
      type: 'photos',
      date: toPhotoDate(photo),
      stableIndex: index,
      data: photo,
    })),
    ...events.map((event, index) => ({
      id: `plan-${event.id}`,
      type: 'plans',
      date: toEventDate(event),
      stableIndex: index,
      data: event,
    })),
  ];
  const typeOrder = { plans: 0, photos: 1, chat: 2 };

  return items.sort((a, b) => {
    if (a.date && b.date) return a.date.getTime() - b.date.getTime();
    if (a.date) return -1;
    if (b.date) return 1;
    if (typeOrder[a.type] !== typeOrder[b.type]) return typeOrder[a.type] - typeOrder[b.type];
    return a.stableIndex - b.stableIndex;
  });
};

const DayTimeline = ({
  items,
  filter,
  counts,
  onOpenMessage,
  onOpenPhoto,
  onNavigate,
  onRsvp,
  onPin,
  onSendToChat,
  onPrepareChatMessage,
  onEventsChanged,
}) => {
  const filteredItems = filter === 'all' ? items : items.filter((item) => item.type === filter);

  if (items.length === 0) {
    return <div className="placeholder-panel compact day-empty-state">No activity on this day yet</div>;
  }

  if (filteredItems.length === 0) {
    const emptyText = filter === 'chat'
      ? 'No messages on this day'
      : filter === 'photos'
        ? 'No photos on this day'
        : 'No plans on this day';
    return <div className="placeholder-panel compact day-empty-state">{emptyText}</div>;
  }

  return (
    <div className="day-timeline">
      {filteredItems.map((item) => {
        if (item.type === 'chat') {
          const message = item.data;
          return (
            <button key={item.id} type="button" className="day-message timeline-item timeline-item--chat" onClick={() => onOpenMessage(message.id)}>
              <div>
                <strong>{message.nickname || 'Friend'}</strong>
                <span>{item.date ? format(item.date, 'h:mm a') : ''}</span>
              </div>
              <p>{message.content}</p>
            </button>
          );
        }

        if (item.type === 'photos') {
          const photo = item.data;
          return (
            <button
              key={item.id}
              type="button"
              className="timeline-item timeline-item--photo"
              onClick={() => onOpenPhoto(photo)}
            >
              <img src={photo.thumbnail_url || photo.url} alt={getPhotoLabel(photo)} />
              <span>{item.date ? format(item.date, 'h:mm a') : 'Photo'}</span>
              <strong>{getPhotoLabel(photo)}</strong>
            </button>
          );
        }

        return (
          <MobilePlanCard
            key={item.id}
            event={item.data}
            onNavigate={onNavigate}
            onRsvp={onRsvp}
            onPin={onPin}
            onSendToChat={onSendToChat}
            onPrepareChatMessage={onPrepareChatMessage}
            onEventsChanged={onEventsChanged}
          />
        );
      })}
      {filter === 'all' && counts.messages === 0 && counts.photos === 0 && counts.plans === 0 && (
        <div className="placeholder-panel compact day-empty-state">No activity on this day yet</div>
      )}
    </div>
  );
};

const CalendarPage = ({ onNavigate }) => {
  const [events, setEvents] = useState([]);
  const [messages, setMessages] = useState([]);
  const [photos, setPhotos] = useState([]);
  const [error, setError] = useState(null);
  const [isLoadingActivity, setIsLoadingActivity] = useState(false);
  const [visibleMonth, setVisibleMonth] = useState(() => startOfMonth(new Date()));
  const [selectedDate, setSelectedDate] = useState(() => new Date());
  const [isMonthExpanded, setIsMonthExpanded] = useState(false);
  const [timelineFilter, setTimelineFilter] = useState('all');
  const [openPhoto, setOpenPhoto] = useState(null);
  const dayContentRef = useRef(null);
  const didMountRef = useRef(false);
  const swipeStartRef = useRef(null);

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

  const calendarDays = useMemo(() => buildCalendarDays(visibleMonth), [visibleMonth]);

  useEffect(() => {
    const visibleRange = getVisibleRange(calendarDays);
    setIsLoadingActivity(true);

    Promise.all([
      fetchMessages(CALENDAR_MESSAGE_LIMIT, visibleRange),
      fetchPhotos(CALENDAR_PHOTO_LIMIT, visibleRange),
    ])
      .then(([messageData, photoData]) => {
        setMessages(messageData.messages || []);
        setPhotos(photoData.photos || []);
        setError(null);
      })
      .catch((err) => setError(err.message))
      .finally(() => setIsLoadingActivity(false));
  }, [calendarDays]);

  useEffect(() => {
    setTimelineFilter('all');
    if (!didMountRef.current) {
      didMountRef.current = true;
      return;
    }
    window.requestAnimationFrame(() => {
      dayContentRef.current?.scrollIntoView({ block: 'start' });
    });
  }, [selectedDate]);

  const selectedEvents = useMemo(
    () => events.filter((event) => {
      const eventDate = toEventDate(event);
      return eventDate && isSameDay(eventDate, selectedDate);
    }),
    [events, selectedDate],
  );

  const selectedMessages = useMemo(
    () => messages.filter((message) => {
      const messageDate = toMessageDate(message);
      return messageDate && isSameDay(messageDate, selectedDate);
    }),
    [messages, selectedDate],
  );

  const selectedPhotos = useMemo(
    () => photos.filter((photo) => {
      const photoDate = toPhotoDate(photo);
      return photoDate && isSameDay(photoDate, selectedDate);
    }),
    [photos, selectedDate],
  );

  const activityByDay = useMemo(() => {
    return calendarDays.map((day) => ({
      date: day,
      events: events.filter((event) => {
        const eventDate = toEventDate(event);
        return eventDate && isSameDay(eventDate, day);
      }),
      messages: messages.filter((message) => {
        const messageDate = toMessageDate(message);
        return messageDate && isSameDay(messageDate, day);
      }),
      photos: photos.filter((photo) => {
        const photoDate = toPhotoDate(photo);
        return photoDate && isSameDay(photoDate, day);
      }),
    }));
  }, [calendarDays, events, messages, photos]);

  const selectedCounts = {
    messages: selectedMessages.length,
    photos: selectedPhotos.length,
    plans: selectedEvents.length,
  };

  const timelineItems = useMemo(
    () => buildTimelineItems(selectedMessages, selectedPhotos, selectedEvents),
    [selectedMessages, selectedPhotos, selectedEvents],
  );

  const goToMonth = (date) => {
    setVisibleMonth(startOfMonth(date));
  };

  const selectDate = (date) => {
    setSelectedDate(date);
    if (!isSameMonth(date, visibleMonth)) goToMonth(date);
  };

  const goToToday = () => {
    selectDate(new Date());
  };

  const moveDay = (dayDelta) => {
    selectDate(addDays(selectedDate, dayDelta));
  };

  const handlePlanQuickAction = () => {
    onNavigate('/events');
  };

  const handleSwipeStart = (event) => {
    if (event.target.closest('button, a, input, textarea, select')) return;
    swipeStartRef.current = { x: event.clientX, y: event.clientY };
  };

  const handleSwipeEnd = (event) => {
    const start = swipeStartRef.current;
    swipeStartRef.current = null;
    if (!start) return;
    const deltaX = event.clientX - start.x;
    const deltaY = event.clientY - start.y;
    if (Math.abs(deltaX) < 60 || Math.abs(deltaX) < Math.abs(deltaY) * 1.5) return;
    moveDay(deltaX < 0 ? 1 : -1);
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
    onNavigate(`/chat?draft=${encodeURIComponent(item.short_id || '')}`);
  };

  const openChatMessage = (messageId) => {
    onNavigate(buildChatMessageHref(messageId));
  };

  const openDayPhoto = (photo) => {
    setOpenPhoto({ url: photo.url, label: getPhotoLabel(photo), tags: photo.tags });
  };

  const renderMessageSection = (showEmpty = false) => (
    selectedMessages.length > 0 ? (
      <section className="day-section">
        <h3>Chat{showEmpty ? '' : ` (${selectedMessages.length})`}</h3>
        <div className="day-message-list">
          {selectedMessages.map((message) => {
            const messageDate = toMessageDate(message);
            return (
              <button
                key={message.id}
                type="button"
                className="day-message"
                onClick={() => openChatMessage(message.id)}
              >
                <div>
                  <strong>{message.nickname || 'Friend'}</strong>
                  <span>{messageDate ? format(messageDate, 'h:mm a') : ''}</span>
                </div>
                <p>{message.content}</p>
              </button>
            );
          })}
        </div>
      </section>
    ) : showEmpty ? (
      <div className="placeholder-panel compact">No chat messages on this day</div>
    ) : null
  );

  const renderPhotoSection = (showEmpty = false) => (
    selectedPhotos.length > 0 ? (
      <section className="day-section">
        <h3>Photos{showEmpty ? '' : ` (${selectedPhotos.length})`}</h3>
        <div className={`day-photo-grid${selectedPhotos.length === 1 ? ' has-single-photo' : ''}`}>
          {selectedPhotos.map((photo) => (
            <button key={photo.id} type="button" className="day-photo-card" onClick={() => openDayPhoto(photo)}>
              <img src={photo.thumbnail_url || photo.url} alt={getPhotoLabel(photo)} />
              <span>{getPhotoLabel(photo)}</span>
            </button>
          ))}
        </div>
      </section>
    ) : showEmpty ? (
      <div className="placeholder-panel compact">No photos on this day</div>
    ) : null
  );

  const renderEventSection = (showEmpty = false) => (
    selectedEvents.length > 0 ? (
      <div className="day-event-list">
        <h3>Plans{showEmpty ? '' : ` (${selectedEvents.length})`}</h3>
        {selectedEvents.map((event) => (
          <article key={event.id} className="day-event-card">
            {event.cover_photo_url && <img className="event-card-cover" src={event.cover_photo_url} alt="" />}
            <div className="day-event-card__top">
              <HubItemCardMeta item={event.hub_item} onPin={togglePin} onSendToChat={sendToChat} onPrepareChatMessage={prepareChatMessage} />
              <span className="day-event-time">{formatEventTime(event)}</span>
            </div>

            <div className="day-event-card__body">
              <h3>{event.title}</h3>
              {event.description && <p>{event.description}</p>}
              {event.location && (
                <a className="map-link" href={mapsUrl(event.location)} target="_blank" rel="noreferrer">
                  {event.location}
                </a>
              )}
              <span className="day-event-rsvps">{event.yes_count} yes · {event.maybe_count || 0} maybe · {event.no_count} no</span>
            </div>

            <div className="row-actions day-event-actions">
              <button type="button" onClick={() => onNavigate(`/events/${event.id}`)}>Open</button>
              <button type="button" onClick={() => handleRsvp(event.id, 'yes')}>Yes</button>
              <button type="button" onClick={() => handleRsvp(event.id, 'maybe')}>Maybe</button>
              <button type="button" onClick={() => handleRsvp(event.id, 'no')}>No</button>
            </div>
            <EngagementPanel targetType="event" targetId={event.id} reactions={event.reactions} commentCount={event.comment_count} onChange={loadEvents} />
          </article>
        ))}
      </div>
    ) : showEmpty ? (
      <div className="placeholder-panel compact">No plans on this day</div>
    ) : null
  );

  return (
    <section className="page feature-page calendar-page">
      <header className="page-header">
        <h1>Calendar</h1>
        <p className="page-subtitle">Browse each day's chat, photos, and plans.</p>
      </header>

      <section className="calendar-compact" aria-label="Event calendar">
        <MobileWeekStrip selectedDate={selectedDate} activityByDay={activityByDay} onSelectDate={selectDate} />
        <button
          type="button"
          className="mobile-month-toggle"
          onClick={() => setIsMonthExpanded((current) => !current)}
          aria-expanded={isMonthExpanded}
        >
          {isMonthExpanded ? 'Hide month' : `Month: ${format(visibleMonth, 'MMM yyyy')}`}
        </button>

        <div className={`calendar-month-panel${isMonthExpanded ? ' is-expanded' : ''}`}>
          <div className="calendar-toolbar">
            <button type="button" onClick={() => setVisibleMonth((date) => subMonths(date, 1))}>
              ←
            </button>
            <h2>{format(visibleMonth, 'MMM yyyy')}</h2>
            <div className="calendar-toolbar-actions">
              <button type="button" onClick={goToToday}>Today</button>
              <button type="button" onClick={() => setVisibleMonth((date) => addMonths(date, 1))}>
                →
              </button>
            </div>
          </div>

          <div className="calendar-weekdays" aria-hidden="true">
            {['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].map((dayName) => (
              <span key={dayName}>{dayName.charAt(0)}</span>
            ))}
          </div>

          <div className="calendar-grid">
            {activityByDay.map(({ date, events: dayEvents, messages: dayMessages, photos: dayPhotos }) => {
              const isSelected = isSameDay(date, selectedDate);
              const isToday = isSameDay(date, new Date());
              const totalActivity = dayEvents.length + dayMessages.length + dayPhotos.length;
              return (
                <button
                  type="button"
                  key={date.toISOString()}
                  className={[
                    'calendar-day',
                    !isSameMonth(date, visibleMonth) ? 'is-muted' : '',
                    isSelected ? 'is-selected' : '',
                    isToday ? 'is-today' : '',
                  ].filter(Boolean).join(' ')}
                  onClick={() => selectDate(date)}
                  aria-pressed={isSelected}
                  aria-label={`${format(date, 'MMM d')}: ${dayMessages.length} messages, ${dayPhotos.length} photos, ${dayEvents.length} events`}
                >
                  <span className="calendar-day-number">{format(date, 'd')}</span>
                  {totalActivity > 0 && <span className="calendar-day-dot" aria-hidden="true" />}
                </button>
              );
            })}
          </div>
        </div>
      </section>

      {error && <div className="inline-error">{error}</div>}

      <div className="calendar-tab-content">
        <div
          className="tab-pane"
          ref={dayContentRef}
          onPointerDown={handleSwipeStart}
          onPointerUp={handleSwipeEnd}
          onPointerCancel={() => { swipeStartRef.current = null; }}
        >
          <DaySummaryHeader
            selectedDate={selectedDate}
            counts={selectedCounts}
            onPreviousDay={() => moveDay(-1)}
            onNextDay={() => moveDay(1)}
            onMessage={() => onNavigate('/chat')}
            onPlan={handlePlanQuickAction}
            onPhoto={() => onNavigate('/photos')}
          />

          {isLoadingActivity && <div className="inline-notice">Loading day activity...</div>}

          <section className="mobile-day-timeline-section">
            <TimelineFilter value={timelineFilter} onChange={setTimelineFilter} counts={selectedCounts} />
            <DayTimeline
              items={timelineItems}
              filter={timelineFilter}
              counts={selectedCounts}
              onOpenMessage={openChatMessage}
              onOpenPhoto={openDayPhoto}
              onNavigate={onNavigate}
              onRsvp={handleRsvp}
              onPin={togglePin}
              onSendToChat={sendToChat}
              onPrepareChatMessage={prepareChatMessage}
              onEventsChanged={loadEvents}
            />
          </section>

          <div className="desktop-day-sections">
            {renderMessageSection(true)}
            {renderPhotoSection(false)}
            {renderEventSection(false)}
          </div>
        </div>
      </div>

      <PhotoModal photo={openPhoto} onClose={() => setOpenPhoto(null)} />
    </section>
  );
};

export default CalendarPage;
