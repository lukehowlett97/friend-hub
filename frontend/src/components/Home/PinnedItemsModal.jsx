import React, { useEffect } from 'react';
import './HomeAppearanceModal.css';
import './PinnedItemsModal.css';

const itemRoutes = {
  idea: '/ideas',
  poll: '/polls',
  event: '/events',
  reminder: '/reminders',
  note: '/notes',
  hub_item: '/items',
};

function routeForItem(item) {
  const type = item.hub_item?.type || item.type;
  if (type === 'event') {
    const eventId = item.source_id || item.hub_item?.source_id || item.id;
    return eventId ? `/events/${eventId}` : '/events';
  }
  if (type === 'note') {
    const noteId = item.source_id || item.hub_item?.source_id || item.id;
    return noteId ? `/notes/${noteId}` : '/notes';
  }
  return itemRoutes[type] || '/items';
}

const PinnedItemsModal = ({ open, items, onClose, onNavigate }) => {
  useEffect(() => {
    if (!open) return undefined;
    const handleKeyDown = (event) => { if (event.key === 'Escape') onClose(); };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  const list = items || [];

  return (
    <div className="home-appearance-modal" role="dialog" aria-modal="true" aria-label="Pinned items">
      <button
        className="home-appearance-modal__backdrop"
        type="button"
        aria-label="Close"
        onClick={onClose}
      />
      <div className="home-appearance-modal__sheet">
        <header className="home-appearance-modal__header">
          <h2>Pinned items</h2>
          <button
            type="button"
            className="home-appearance-modal__close"
            aria-label="Close"
            onClick={onClose}
          >×</button>
        </header>

        {list.length === 0 ? (
          <div className="placeholder-panel compact">No pinned items yet.</div>
        ) : (
          <ul className="pinned-items-modal__list">
            {list.map((item) => {
              const type = item.hub_item?.type || item.type || 'item';
              const shortId = item.hub_item?.short_id || item.short_id;
              const title = item.title || item.question || item.text || 'Untitled';
              return (
                <li key={`${type}-${item.id}`}>
                  <button
                    type="button"
                    className="pinned-items-modal__item"
                    onClick={() => { onClose(); onNavigate?.(routeForItem(item)); }}
                  >
                    <span className="pinned-items-modal__eyebrow">
                      {shortId ? `${shortId} · ` : ''}{type}
                    </span>
                    <strong>{title}</strong>
                    {item.body && <span className="pinned-items-modal__body">{item.body}</span>}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
};

export default PinnedItemsModal;
