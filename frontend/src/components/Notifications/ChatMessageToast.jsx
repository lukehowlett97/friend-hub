import React from 'react';
import UserAvatar from '../Chat/UserAvatar.jsx';
import './ChatMessageToast.css';

const getToastPreview = (content = '') => {
  if (content.startsWith('Photo: ')) return 'Shared a photo';
  return content.replace(/\s+/g, ' ').trim();
};

const ChatMessageToast = ({ message, onClick }) => {
  if (!message) return null;

  const sender = message.isMe ? 'You' : (message.nickname || message.sender || 'Someone');

  return (
    <button type="button" className="chat-message-toast" onClick={onClick}>
      <UserAvatar
        nickname={sender}
        size={34}
        avatarUrl={message.avatar_url}
        avatarEmoji={message.avatar_emoji || (message.is_bot ? '🤖' : null)}
      />
      <span className="chat-message-toast__body">
        <span className="chat-message-toast__sender">{sender}</span>
        <span className="chat-message-toast__preview">{getToastPreview(message.content)}</span>
      </span>
    </button>
  );
};

export default ChatMessageToast;
