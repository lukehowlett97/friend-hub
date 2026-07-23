import React, { useEffect, useRef, useState } from 'react';
import useWebSocket from '../../hooks/useWebSocket.jsx';
import ChatMessageToast from './ChatMessageToast.jsx';

const BASE_TITLE = 'Friend Hub';

function isTabHidden() {
  return typeof document !== 'undefined' && document.visibilityState === 'hidden';
}

const GlobalChatNotifications = ({ onNavigate }) => {
  const [latestMessage, setLatestMessage] = useState(null);
  const [unreadCount, setUnreadCount] = useState(0);
  const previousLastMessageIdRef = useRef(null);
  const toastTimerRef = useRef(null);
  const {
    messages,
    isLoadingHistory,
    isLoadingOlder,
    connect,
    disconnect,
  } = useWebSocket();

  useEffect(() => {
    connect();
    return () => disconnect();
  }, [connect, disconnect]);

  useEffect(() => () => clearTimeout(toastTimerRef.current), []);

  // Reset the unread badge whenever the tab becomes visible again.
  useEffect(() => {
    const handler = () => {
      if (!isTabHidden()) setUnreadCount(0);
    };
    document.addEventListener('visibilitychange', handler);
    window.addEventListener('focus', handler);
    return () => {
      document.removeEventListener('visibilitychange', handler);
      window.removeEventListener('focus', handler);
    };
  }, []);

  // Drive document.title from the unread count.
  useEffect(() => {
    document.title = unreadCount > 0 ? `(${unreadCount}) ${BASE_TITLE}` : BASE_TITLE;
  }, [unreadCount]);

  useEffect(() => {
    const lastMessage = messages[messages.length - 1];

    if (!lastMessage) {
      previousLastMessageIdRef.current = null;
      setLatestMessage(null);
      return;
    }

    const previousLastMessageId = previousLastMessageIdRef.current;
    previousLastMessageIdRef.current = lastMessage.id;

    if (
      isLoadingHistory ||
      isLoadingOlder ||
      lastMessage.id === previousLastMessageId ||
      lastMessage.type !== 'chat' ||
      !lastMessage.isLive ||
      lastMessage.isMe
    ) {
      return;
    }

    setLatestMessage(lastMessage);
    clearTimeout(toastTimerRef.current);
    toastTimerRef.current = setTimeout(() => setLatestMessage(null), 3600);

    // Bump the tab badge only when the user can't see the chat right now.
    if (isTabHidden()) {
      setUnreadCount(c => c + 1);
    }
  }, [messages, isLoadingHistory, isLoadingOlder]);

  const handleOpenChat = () => {
    clearTimeout(toastTimerRef.current);
    setLatestMessage(null);
    setUnreadCount(0);
    onNavigate?.('/chat');
  };

  return (
    <ChatMessageToast
      key={latestMessage?.id || 'empty-global-chat-toast'}
      message={latestMessage}
      onClick={handleOpenChat}
    />
  );
};

export default GlobalChatNotifications;
