import React, { useEffect, useState, useRef } from 'react';
import EmojiKeyboard from '../Reactions/EmojiKeyboard.jsx';
import { haptic } from '../../utils/haptics.js';
import './MessageContextMenu.css';

const DEFAULT_EMOJIS = ['😀', '👍', '❤️', '😂', '🔥', '🎉'];

const MessageContextMenu = ({
  message,
  isMe,
  quickEmojis,
  onReaction,
  onReply,
  onEdit,
  onDelete,
  onClose,
}) => {
  const [keyboardOpen, setKeyboardOpen] = useState(false);
  const [visible, setVisible] = useState(false);
  const sheetRef = useRef(null);
  const emojis = quickEmojis || DEFAULT_EMOJIS;

  useEffect(() => {
    requestAnimationFrame(() => setVisible(true));
  }, []);

  useEffect(() => {
    const handleKey = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', handleKey);
    return () => document.removeEventListener('keydown', handleKey);
  }, [onClose]);

  const handleAction = (fn) => {
    haptic(10);
    fn();
  };

  const isDeleted = message.isDeleted || message.is_deleted;

  return (
    <div
      className={`context-menu-backdrop${visible ? ' visible' : ''}`}
      role="presentation"
      onClick={onClose}
    >
      <div
        ref={sheetRef}
        className={`context-menu-sheet${visible ? ' visible' : ''}`}
        role="dialog"
        aria-modal="true"
        aria-label="Message options"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="context-menu-handle" />

        {!isDeleted && (
          <div className="context-menu-reactions">
            {emojis.map((emoji) => (
              <button
                key={emoji}
                type="button"
                className="context-menu-emoji-btn"
                onClick={() => handleAction(() => onReaction(emoji))}
                aria-label={`React with ${emoji}`}
              >
                {emoji}
              </button>
            ))}
            <button
              type="button"
              className="context-menu-emoji-btn context-menu-emoji-more"
              onClick={() => setKeyboardOpen((v) => !v)}
              aria-label="More emojis"
            >
              +
            </button>
          </div>
        )}

        {keyboardOpen && (
          <EmojiKeyboard
            onSelect={(emoji) => { handleAction(() => onReaction(emoji)); setKeyboardOpen(false); }}
            onClose={() => setKeyboardOpen(false)}
          />
        )}

        <div className="context-menu-actions">
          <button
            type="button"
            className="context-menu-action-btn"
            onClick={() => handleAction(onReply)}
          >
            <span>↩</span> Reply
          </button>

          {isMe && !isDeleted && (
            <button
              type="button"
              className="context-menu-action-btn"
              onClick={() => handleAction(onEdit)}
            >
              <span>✏️</span> Edit
            </button>
          )}

          {isMe && (
            <button
              type="button"
              className="context-menu-action-btn context-menu-action-danger"
              onClick={() => handleAction(onDelete)}
            >
              <span>🗑️</span> Delete
            </button>
          )}
        </div>
      </div>
    </div>
  );
};

export default MessageContextMenu;
