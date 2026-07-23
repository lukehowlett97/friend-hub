import React from 'react';

/**
 * Shows "Luke is typing…" (or multiple people) with an animated dot trail.
 * Receives `typingUsers` as {session_id: nickname} and `currentSessionId` to
 * exclude the user's own typing state from display.
 */
const TypingIndicator = ({ typingUsers = {}, currentSessionId }) => {
  const names = Object.entries(typingUsers)
    .filter(([sid]) => sid !== currentSessionId)
    .map(([, nickname]) => nickname);

  if (names.length === 0) return null;

  let label;
  if (names.length === 1)      label = `${names[0]} is typing`;
  else if (names.length === 2) label = `${names[0]} and ${names[1]} are typing`;
  else                          label = `${names[0]} and ${names.length - 1} others are typing`;

  return (
    <div className="typing-indicator">
      <span className="typing-dots">
        <span /><span /><span />
      </span>
      <span className="typing-label">{label}</span>
    </div>
  );
};

export default TypingIndicator;
