import React, { useEffect, useRef, useState } from 'react';
import { apiFetch, getCurrentRoomSlug, setCurrentRoomSlug } from '../../api/client.js';

/**
 * The primary, always-visible room title in the chat top bar.
 * Tapping the title opens the Room Overview. When the user belongs to more than
 * one room, a small switcher caret reveals a room-switch menu.
 */
export default function RoomTitleButton({ onOpenOverview, onResolveName }) {
  const [rooms, setRooms] = useState([]);
  const [currentSlug] = useState(getCurrentRoomSlug);
  const [switcherOpen, setSwitcherOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    let cancelled = false;
    apiFetch('/api/v1/rooms')
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (cancelled || !d?.rooms) return;
        setRooms(d.rooms);
        const slug = getCurrentRoomSlug();
        const cur = d.rooms.find((r) => r.slug === slug) || d.rooms[0];
        if (cur?.name) onResolveName?.(cur.name);
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [onResolveName]);

  useEffect(() => {
    if (!switcherOpen) return undefined;
    const close = (e) => { if (ref.current && !ref.current.contains(e.target)) setSwitcherOpen(false); };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [switcherOpen]);

  const current = rooms.find((r) => r.slug === currentSlug) || rooms[0];
  const name = current?.name || currentSlug || 'Room';
  const canSwitch = rooms.length > 1;

  const switchRoom = (slug) => {
    setSwitcherOpen(false);
    if (slug === currentSlug) return;
    setCurrentRoomSlug(slug);
    window.location.reload();
  };

  return (
    <div className="chat-room-title" ref={ref}>
      <button
        type="button"
        className="chat-room-title__btn"
        onClick={onOpenOverview}
        aria-label={`${name} — open room overview`}
        aria-haspopup="dialog"
      >
        <span className="chat-room-title__name">{name}</span>
        <span className="chat-room-title__chevron" aria-hidden="true">˅</span>
      </button>
      {canSwitch && (
        <button
          type="button"
          className="chat-room-title__switch"
          onClick={() => setSwitcherOpen((o) => !o)}
          aria-label="Switch room"
          aria-haspopup="menu"
          aria-expanded={switcherOpen}
        >
          ⇄
        </button>
      )}
      {switcherOpen && canSwitch && (
        <div className="chat-room-title__menu" role="menu">
          {rooms.map((r) => (
            <button
              key={r.slug}
              type="button"
              className={`chat-room-title__option${r.slug === currentSlug ? ' is-current' : ''}`}
              role="menuitem"
              onClick={() => switchRoom(r.slug)}
            >
              <span className="chat-room-title__option-name">{r.name}</span>
              <span className="chat-room-title__option-role">{r.role}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
