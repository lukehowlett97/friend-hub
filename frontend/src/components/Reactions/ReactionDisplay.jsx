import React, { useState } from 'react';
import ReactionModal from './ReactionModal.jsx';
import './ReactionDisplay.css';

const ReactionDisplay = ({ reactions = [], currentSessionId, targetType, targetId }) => {
  const [modal, setModal] = useState(null); // emoji string or null

  if (!reactions || reactions.length === 0) return null;

  return (
    <>
      <div className="reaction-display">
        {reactions.map((reaction) => {
          const userReacted = reaction.session_ids?.includes(currentSessionId);
          const names = reaction.nicknames?.length
            ? reaction.nicknames.join(', ')
            : `${reaction.count} ${reaction.count === 1 ? 'person' : 'people'}`;

          return (
            <div
              key={reaction.emoji}
              className={`reaction-bubble ${userReacted ? 'user-reacted' : ''}`}
              title={`${names} reacted with ${reaction.emoji}`}
              role="button"
              tabIndex={0}
              aria-label={`${reaction.emoji} ${reaction.count} — click to see who reacted`}
              onClick={() => targetType && targetId && setModal(reaction.emoji)}
              onKeyDown={e => e.key === 'Enter' && targetType && targetId && setModal(reaction.emoji)}
            >
              <span className="reaction-emoji">{reaction.emoji}</span>
              <span className="reaction-count">{reaction.count}</span>
            </div>
          );
        })}
      </div>

      {modal && targetType && targetId && (
        <ReactionModal
          targetType={targetType}
          targetId={targetId}
          initialEmoji={modal}
          onClose={() => setModal(null)}
        />
      )}
    </>
  );
};

export default ReactionDisplay;
