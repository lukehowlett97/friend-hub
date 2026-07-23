import React, { useEffect, useRef } from 'react';
import './ChatHelpModal.css';

const CAPABILITIES = [
  { icon: '💬', title: 'Chat', body: 'Send messages, reply, edit, and react with emojis.' },
  { icon: '📷', title: 'Photos & GIFs', body: 'Share photos and GIFs — browse them all in the Photos gallery.' },
  { icon: '🔍', title: 'Search', body: 'Search messages, photos, people, polls, events and more.' },
  { icon: '⚖️', title: 'Agenda', body: 'Raise a council motion, schedule events, and run polls.' },
  { icon: '📌', title: 'Pinned items', body: 'Important events, polls and ideas pinned for the group.' },
  { icon: '🧠', title: 'Summaries', body: 'Ask for a recap with the summarise action in the composer.' },
  { icon: '📊', title: 'Stats', body: 'Explore room activity, leaderboards and reaction trends.' },
];

const ChatHelpModal = ({ open, onClose }) => {
  const closeRef = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    closeRef.current?.focus();
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="chat-help__backdrop"
      role="presentation"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <section className="chat-help" role="dialog" aria-modal="true" aria-label="What you can do here">
        <header className="chat-help__header">
          <h2>What you can do here</h2>
          <button type="button" className="chat-help__close" onClick={onClose} aria-label="Close help" ref={closeRef}>
            ×
          </button>
        </header>
        <ul className="chat-help__list">
          {CAPABILITIES.map((cap) => (
            <li key={cap.title} className="chat-help__item">
              <span className="chat-help__icon" aria-hidden="true">{cap.icon}</span>
              <span className="chat-help__text">
                <strong>{cap.title}</strong>
                <span>{cap.body}</span>
              </span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
};

export default ChatHelpModal;
