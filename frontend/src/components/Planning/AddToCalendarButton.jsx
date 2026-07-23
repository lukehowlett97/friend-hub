import React, { useEffect, useId, useMemo, useRef, useState } from 'react';
import { getEventCalendarIcsUrl } from '../../services/api.js';

const DEFAULT_EVENT_DURATION_MS = 2 * 60 * 60 * 1000;

const toDate = (value) => {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
};

const calendarDate = (date) => date.toISOString().replace(/[-:]/g, '').replace(/\.\d{3}Z$/, 'Z');

const eventEndDate = (event) => {
  const start = toDate(event.starts_at);
  const end = toDate(event.ends_at);
  if (end) return end;
  return start ? new Date(start.getTime() + DEFAULT_EVENT_DURATION_MS) : null;
};

const eventUrl = (event) => `${window.location.origin}/events/${event.id}`;

const buildGoogleUrl = (event) => {
  const start = toDate(event.starts_at);
  const end = eventEndDate(event);
  const params = new URLSearchParams({
    action: 'TEMPLATE',
    text: event.title || 'Friend Hub event',
  });
  if (start && end) params.set('dates', `${calendarDate(start)}/${calendarDate(end)}`);
  if (event.description) params.set('details', `${event.description}\n\n${eventUrl(event)}`);
  else params.set('details', eventUrl(event));
  if (event.location) params.set('location', event.location);
  return `https://calendar.google.com/calendar/render?${params.toString()}`;
};

const buildOutlookUrl = (event) => {
  const start = toDate(event.starts_at);
  const end = eventEndDate(event);
  const params = new URLSearchParams({
    path: '/calendar/action/compose',
    rru: 'addevent',
    subject: event.title || 'Friend Hub event',
    body: event.description ? `${event.description}\n\n${eventUrl(event)}` : eventUrl(event),
  });
  if (start) params.set('startdt', start.toISOString());
  if (end) params.set('enddt', end.toISOString());
  if (event.location) params.set('location', event.location);
  return `https://outlook.live.com/calendar/0/deeplink/compose?${params.toString()}`;
};

const AddToCalendarButton = ({ event, className = '' }) => {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const rootRef = useRef(null);
  const menuId = useId();

  const links = useMemo(() => ({
    google: buildGoogleUrl(event),
    outlook: buildOutlookUrl(event),
    ics: getEventCalendarIcsUrl(event.id),
    event: eventUrl(event),
  }), [event]);

  useEffect(() => {
    if (!open) return undefined;
    const handlePointerDown = (pointerEvent) => {
      if (!rootRef.current?.contains(pointerEvent.target)) setOpen(false);
    };
    const handleKeyDown = (keyEvent) => {
      if (keyEvent.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', handlePointerDown);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('mousedown', handlePointerDown);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [open]);

  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(links.event);
      setCopied(true);
      setOpen(false);
      window.setTimeout(() => setCopied(false), 2400);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div ref={rootRef} className={`add-calendar${className ? ` ${className}` : ''}`}>
      <button
        type="button"
        className="add-calendar__button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-controls={menuId}
        aria-haspopup="menu"
      >
        Add to calendar
      </button>
      {copied && <span className="add-calendar__status" role="status">Link copied</span>}
      {open && (
        <div id={menuId} className="add-calendar__menu" role="menu">
          <a role="menuitem" href={links.google} target="_blank" rel="noreferrer">Google Calendar</a>
          <a role="menuitem" href={links.outlook} target="_blank" rel="noreferrer">Outlook Calendar</a>
          <a role="menuitem" href={links.ics}>Download .ics</a>
          <button type="button" role="menuitem" onClick={copyLink}>Copy event link</button>
        </div>
      )}
    </div>
  );
};

export default AddToCalendarButton;
