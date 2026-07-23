import React, { useState } from 'react';
import EmojiKeyboard from './EmojiKeyboard.jsx';
import { haptic } from '../../utils/haptics.js';
import './ReactionPicker.css';

const DEFAULT_EMOJIS = ['😀', '👍', '❤️', '😂', '🔥', '🎉'];

const ReactionPicker = ({ onSelect, isOpen, quickEmojis }) => {
  const [keyboardOpen, setKeyboardOpen] = useState(false);
  const emojis = quickEmojis || DEFAULT_EMOJIS;

  if (!isOpen) return null;

  const handleSelect = (emoji) => {
    haptic(15);
    onSelect(emoji);
  };

  return (
    <div className="reaction-picker">
      {emojis.map((emoji) => (
        <button
          key={emoji}
          className="reaction-picker-btn"
          onClick={() => handleSelect(emoji)}
          title={emoji}
        >
          {emoji}
        </button>
      ))}
      <button
        className="reaction-picker-btn reaction-picker-more"
        onClick={() => setKeyboardOpen((v) => !v)}
        title="More emojis"
        aria-label="Open full emoji keyboard"
      >
        +
      </button>
      {keyboardOpen && (
        <EmojiKeyboard
          onSelect={(emoji) => {
            handleSelect(emoji);
            setKeyboardOpen(false);
          }}
          onClose={() => setKeyboardOpen(false)}
        />
      )}
    </div>
  );
};

export default ReactionPicker;
