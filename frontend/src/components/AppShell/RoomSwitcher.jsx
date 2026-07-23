import React, { useEffect, useRef, useState } from 'react';
import { apiFetch, getCurrentRoomSlug, setCurrentRoomSlug } from '../../api/client.js';

export default function RoomSwitcher({ className = '', showWhenSingle = false }) {
  const [rooms, setRooms] = useState([]);
  const [currentSlug, setCurrentSlug] = useState(getCurrentRoomSlug);
  const [open, setOpen] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    apiFetch('/api/v1/rooms')
      .then(r => r.ok ? r.json() : null)
      .then(d => {
        if (d?.rooms) setRooms(d.rooms);
        setLoaded(true);
      })
      .catch(() => setLoaded(true));
  }, []);

  useEffect(() => {
    if (!open) return;
    const close = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [open]);

  // Don't render until loaded, and only show a single room when a caller needs
  // the current room label in its own UI.
  if (!loaded || (!showWhenSingle && rooms.length <= 1) || rooms.length === 0) return null;

  const current = rooms.find(r => r.slug === currentSlug) || rooms[0];
  const canSwitchRooms = rooms.length > 1;

  const switchRoom = (slug) => {
    if (slug === currentSlug) {
      setOpen(false);
      return;
    }
    setCurrentRoomSlug(slug);
    setCurrentSlug(slug);
    setOpen(false);
    window.location.reload();
  };

  return (
    <div className={`room-switcher${className ? ` ${className}` : ''}`} ref={ref}>
      <button
        className="room-switcher__btn"
        onClick={() => canSwitchRooms && setOpen(o => !o)}
        title={canSwitchRooms ? 'Switch room' : current?.name}
        aria-haspopup={canSwitchRooms ? 'menu' : undefined}
        aria-expanded={canSwitchRooms ? open : undefined}
        disabled={!canSwitchRooms}
      >
        <span className="room-switcher__name">{current?.name ?? currentSlug}</span>
        {canSwitchRooms && <span className="room-switcher__chevron">{open ? '▴' : '▾'}</span>}
      </button>
      {open && canSwitchRooms && (
        <div className="room-switcher__dropdown" role="menu">
          {rooms.map(r => (
            <button
              key={r.slug}
              className={`room-switcher__option${r.slug === currentSlug ? ' is-current' : ''}`}
              onClick={() => switchRoom(r.slug)}
              role="menuitem"
            >
              <span className="room-switcher__option-name">{r.name}</span>
              <span className="room-switcher__option-role">{r.role}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
