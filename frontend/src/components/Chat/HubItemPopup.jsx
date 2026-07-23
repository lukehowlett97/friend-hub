import React, { useEffect, useRef, useState } from 'react';
import { fetchHubItemByRef } from '../../services/api.js';
import './HubItemPopup.css';

const cache = new Map();

const TYPE_LABELS = { idea: 'Idea', poll: 'Poll', reminder: 'Reminder', event: 'Event', note: 'Note' };
const TYPE_ROUTES = { idea: '/ideas', poll: '/polls', reminder: '/reminders', event: '/events', note: '/notes' };

const STATUS_LABELS = { open: 'Open', done: 'Done', archived: 'Archived' };

function fmtDate(iso) {
  if (!iso) return null;
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
}

export default function HubItemPopup({ shortRef, onClose }) {
  const [item, setItem]       = useState(cache.get(shortRef) || null);
  const [isLoading, setLoad]  = useState(!cache.has(shortRef));
  const [error, setError]     = useState(null);
  const overlayRef            = useRef(null);

  useEffect(() => {
    if (cache.has(shortRef)) return;
    setLoad(true);
    fetchHubItemByRef(shortRef)
      .then(data => {
        if (data) { cache.set(shortRef, data); setItem(data); }
        else setError('Item not found');
      })
      .catch(() => setError('Failed to load'))
      .finally(() => setLoad(false));
  }, [shortRef]);

  useEffect(() => {
    const handler = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  const handleOverlayClick = (e) => {
    if (e.target === overlayRef.current) onClose();
  };

  const handleView = () => {
    if (!item) return;
    const route = item.type === 'event' && item.source_id
      ? `/events/${item.source_id}`
      : item.type === 'note' && item.source_id
        ? `/notes/${item.source_id}`
      : (TYPE_ROUTES[item.type] || '/home');
    window.history.pushState({}, '', route);
    window.dispatchEvent(new PopStateEvent('popstate'));
    onClose();
  };

  return (
    <div className="hub-popup-overlay" ref={overlayRef} onClick={handleOverlayClick}>
      <div className="hub-popup-card" role="dialog" aria-modal="true">
        <button className="hub-popup-close" type="button" onClick={onClose} aria-label="Close">✕</button>

        {isLoading && <div className="hub-popup-state">Loading…</div>}
        {error    && <div className="hub-popup-state hub-popup-state--error">{error}</div>}

        {item && (
          <>
            <div className="hub-popup-head">
              <span className={`hub-popup-badge hub-popup-badge--${item.type}`}>
                {TYPE_LABELS[item.type] || item.type}
              </span>
              <span className="hub-popup-ref">{item.short_id}</span>
              <span className={`hub-popup-status hub-popup-status--${item.status}`}>
                {STATUS_LABELS[item.status] || item.status}
              </span>
            </div>

            <h3 className="hub-popup-title">{item.title}</h3>

            {item.body && item.body !== item.title && (
              <p className="hub-popup-body">
                {item.body.length > 220 ? item.body.slice(0, 220) + '…' : item.body}
              </p>
            )}

            <div className="hub-popup-meta">
              {item.due_at        && <span>📅 Due {fmtDate(item.due_at)}</span>}
              {item.event_start_at && <span>🗓 {fmtDate(item.event_start_at)}</span>}
              {item.creator       && <span>👤 {item.creator.nickname}</span>}
              {item.tags?.length > 0 && (
                <span>{item.tags.map(t => `#${t}`).join(' ')}</span>
              )}
            </div>

            <button className="hub-popup-view-btn" type="button" onClick={handleView}>
              View in {TYPE_LABELS[item.type] || 'app'} →
            </button>
          </>
        )}
      </div>
    </div>
  );
}
