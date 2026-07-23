import React, { useState } from 'react';

const HubItemCardMeta = ({
  item,
  onPin,
  onSendToChat,
  onPrepareChatMessage,
  onEdit,
  onDelete,
  canEdit = false,
  canDelete = false,
  editLabel = 'Edit item',
  deleteLabel = 'Delete item',
}) => {
  const [isSending, setIsSending] = useState(false);
  const [justSent, setJustSent] = useState(false);
  const [sendError, setSendError] = useState(null);
  const [isMenuOpen, setIsMenuOpen] = useState(false);

  if (!item) return null;

  const alreadySent = !justSent && !!item.sent_to_chat_at;

  const handleSendToChat = async () => {
    if (isSending) return;
    if (onPrepareChatMessage) {
      onPrepareChatMessage(item);
      return;
    }
    setIsSending(true);
    setSendError(null);
    try {
      await onSendToChat?.(item);
      setJustSent(true);
      setTimeout(() => setJustSent(false), 3000);
    } catch (err) {
      setSendError('Failed to send');
    } finally {
      setIsSending(false);
    }
  };

  const sendLabel = isSending   ? 'Sending…'
    : justSent                  ? 'Sent ✓'
    : alreadySent               ? 'Send again'
    : '→ Chat';

  return (
    <div className="hub-item-meta">
      <div className="hub-item-meta__line">
        <strong>{item.short_id}</strong>
        <span>{item.type}</span>
        {item.tags?.map((tag) => <em key={tag}>#{tag}</em>)}
      </div>
      <div className="hub-item-meta__actions">
        <button
          type="button"
          className={`hub-btn hub-btn--icon hub-btn--pin${item.pinned_to_home ? ' active' : ''}`}
          onClick={() => onPin?.(item)}
          aria-label={`${item.pinned_to_home ? 'Unpin' : 'Pin'} ${item.short_id || item.type}`}
          aria-pressed={!!item.pinned_to_home}
          title={item.pinned_to_home ? 'Unpin' : 'Pin'}
        >
          <span aria-hidden="true">📌</span>
        </button>
        <button
          type="button"
          className={`hub-btn hub-btn--send${justSent ? ' hub-btn--sent' : ''}`}
          onClick={handleSendToChat}
          disabled={isSending || justSent}
          aria-label={`${alreadySent ? 'Send again to chat' : 'Send to chat'} ${item.short_id || item.type}`}
        >
          {sendLabel}
        </button>
        <div className="hub-item-overflow">
          <button
            type="button"
            className="hub-btn hub-btn--icon"
            onClick={() => setIsMenuOpen((value) => !value)}
            aria-label={`More actions for ${item.short_id || item.type}`}
            aria-expanded={isMenuOpen}
            title="More actions"
          >
            <span aria-hidden="true">⋯</span>
          </button>
          {isMenuOpen && (
            <div className="hub-item-overflow-menu">
              {canEdit && (
                <button type="button" onClick={() => { setIsMenuOpen(false); onEdit?.(item); }}>
                  {editLabel}
                </button>
              )}
              {canDelete && (
                <button type="button" className="danger" onClick={() => { setIsMenuOpen(false); onDelete?.(item); }}>
                  {deleteLabel}
                </button>
              )}
              {!canEdit && !canDelete && <span>No extra actions</span>}
            </div>
          )}
        </div>
        {sendError && <span className="hub-item-send-error">{sendError}</span>}
      </div>
    </div>
  );
};

export default HubItemCardMeta;
