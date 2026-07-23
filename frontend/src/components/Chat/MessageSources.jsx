import React, { useState } from 'react';
import './MessageSources.css';

const VISIBLE_LIMIT = 3;

// Compact source chips rendered below a bot answer.
// `sources` is an array of { index, messageId }; clicking a chip jumps to the
// referenced message via `onOpenSource(messageId)`.
const MessageSources = ({ sources, onOpenSource }) => {
  const [expanded, setExpanded] = useState(false);
  if (!sources?.length) return null;

  const visible = expanded ? sources : sources.slice(0, VISIBLE_LIMIT);
  const hiddenCount = sources.length - visible.length;

  return (
    <div className="message-sources" aria-label={`${sources.length} source${sources.length === 1 ? '' : 's'}`}>
      <span className="message-sources__label">Sources</span>
      {visible.map((source) => (
        <button
          key={source.messageId}
          type="button"
          className="message-sources__chip"
          onClick={(e) => {
            e.stopPropagation();
            onOpenSource?.(source.messageId);
          }}
          aria-label={`Open source ${source.index} in chat`}
          title="Jump to the referenced message"
        >
          <span aria-hidden="true">💬</span> {source.index}
        </button>
      ))}
      {hiddenCount > 0 && (
        <button
          type="button"
          className="message-sources__chip message-sources__chip--more"
          onClick={(e) => {
            e.stopPropagation();
            setExpanded(true);
          }}
          aria-label={`Show ${hiddenCount} more sources`}
        >
          +{hiddenCount} more
        </button>
      )}
    </div>
  );
};

export default MessageSources;
