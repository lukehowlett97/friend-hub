import React, { useEffect, useState } from 'react';
import UserAvatar from '../Chat/UserAvatar.jsx';
import { navigate } from '../../utils/navigate.js';
import { apiFetch } from '../../api/client.js';
import './ReactionModal.css';

export default function ReactionModal({ targetType, targetId, initialEmoji, onClose }) {
  const [reactions, setReactions] = useState([]);
  const [activeEmoji, setActiveEmoji] = useState(initialEmoji || null);

  useEffect(() => {
    apiFetch(`/api/v1/reactions/${targetType}/${targetId}`)
      .then(r => r.json())
      .then(data => {
        const list = data.reactions || [];
        setReactions(list);
        if (!activeEmoji && list.length > 0) setActiveEmoji(list[0].emoji);
      })
      .catch(() => {});
  }, [targetType, targetId]);

  useEffect(() => {
    const handler = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  const activeUsers = reactions.find(r => r.emoji === activeEmoji)?.users || [];

  return (
    <div className="reaction-modal-overlay" onClick={onClose}>
      <div className="reaction-modal" onClick={e => e.stopPropagation()}>
        <div className="reaction-modal-header">
          <span className="reaction-modal-title">Reacted</span>
          <button className="reaction-modal-close" onClick={onClose} aria-label="Close">✕</button>
        </div>

        {reactions.length > 1 && (
          <div className="reaction-modal-tabs">
            {reactions.map(r => (
              <button
                key={r.emoji}
                className={`reaction-tab${r.emoji === activeEmoji ? ' active' : ''}`}
                onClick={() => setActiveEmoji(r.emoji)}
              >
                {r.emoji} <span className="reaction-tab-count">{r.users.length}</span>
              </button>
            ))}
          </div>
        )}

        <ul className="reaction-modal-list">
          {activeUsers.map(user => (
            <li
              key={user.username || user.nickname}
              className={`reaction-modal-user${user.username ? ' clickable' : ''}`}
              onClick={() => {
                if (user.username) {
                  navigate(`/profile/${user.username}`);
                  onClose();
                }
              }}
            >
              <UserAvatar nickname={user.nickname} size={36} avatarUrl={user.avatar_url} />
              <span className="reaction-modal-nickname">{user.nickname}</span>
            </li>
          ))}
          {activeUsers.length === 0 && (
            <li className="reaction-modal-empty">No reactions yet</li>
          )}
        </ul>
      </div>
    </div>
  );
}
