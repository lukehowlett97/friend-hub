import React, { useEffect, useRef } from 'react';
import './EmojiKeyboard.css';

const REACTION_EMOJIS = [
  '😀', '😂', '😍', '🥰', '😎', '😢',
  '👍', '👎', '👏', '🙌', '🙏', '💪',
  '❤️', '🔥', '🎉', '✨', '👀', '💯',
  '🤔', '😮', '😅', '😴', '🍻', '✅',
];

const EmojiKeyboard = ({ onSelect, onClose }) => {
  const containerRef = useRef(null);

  // Close on outside click/touch
  useEffect(() => {
    const handleOutside = (e) => {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        onClose();
      }
    };
    document.addEventListener('mousedown', handleOutside);
    document.addEventListener('touchstart', handleOutside, { passive: true });
    return () => {
      document.removeEventListener('mousedown', handleOutside);
      document.removeEventListener('touchstart', handleOutside);
    };
  }, [onClose]);

  return (
    <div className="emoji-keyboard-container" ref={containerRef} role="dialog" aria-label="More reactions">
      <div className="emoji-keyboard-picker" role="grid" aria-label="Reaction emojis">
        {REACTION_EMOJIS.map((emoji) => (
          <button
            key={emoji}
            type="button"
            className="emoji-keyboard-btn"
            onClick={() => onSelect(emoji)}
            aria-label={`React with ${emoji}`}
          >
            {emoji}
          </button>
        ))}
      </div>
    </div>
  );
};

export default EmojiKeyboard;
