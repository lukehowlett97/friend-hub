import React, { useEffect, useRef, useState } from 'react';
import Message from './Message';
import { navigate as navigateTo } from '../../utils/navigate.js';
import { buildChatMessageHref } from '../../utils/chatLinks.js';
import { updateReadState } from '../../services/api.js';

const READ_STATE_DEBOUNCE_MS = 2500;

const MessageList = ({
  messages,
  currentSessionId,
  onReply,
  onToggleReaction,
  onDeleteMessage,
  onEditMessage,
  onPinMessage,
  canPin = false,
  onOpenPhoto,
  targetMessageId = null,
  highlightedMessageIds = [],
  hasOlderMessages = false,
  isLoadingOlder = false,
  loadOlderMessages,
  onMobileNavVisibilityChange,
  quickEmojis,
}) => {
  const listRef = useRef(null);
  const messageRefs = useRef({});
  const previousLastMessageIdRef = useRef(null);
  const hasScrolledToTargetRef = useRef(false);
  const hasInitialScrolledRef = useRef(false);
  const isNearBottomRef = useRef(true);
  // Which message currently has its actions revealed (tap-to-show on mobile).
  // Only one message can be active at a time; tapping another closes the previous.
  const [activeMsgId, setActiveMsgId] = useState(null);
  const [newMessageId, setNewMessageId] = useState(null);
  const [focusedMessageId, setFocusedMessageId] = useState(targetMessageId);
  const [showScrollFab, setShowScrollFab] = useState(false);
  const [unreadFabCount, setUnreadFabCount] = useState(0);
  const lastScrollTopRef = useRef(0);
  const hiddenNavRef = useRef(false);
  const lastReportedReadIdRef = useRef(0);
  const readStateTimerRef = useRef(null);
  const messagesRef = useRef(messages);
  messagesRef.current = messages;
  const highlightedMessageIdSet = new Set([
    ...highlightedMessageIds,
    ...(targetMessageId ? [targetMessageId] : []),
  ].filter((id) => Number.isInteger(id) && id > 0));
  const highlightMessageId = focusedMessageId || targetMessageId;

  const scrollListToBottom = (behavior = 'auto') => {
    const list = listRef.current;
    if (!list) return;
    list.scrollTo({ top: list.scrollHeight, behavior });
    isNearBottomRef.current = true;
  };

  const updateNearBottom = () => {
    const list = listRef.current;
    if (!list) return true;
    const distanceFromBottom = list.scrollHeight - list.scrollTop - list.clientHeight;
    const nearBottom = distanceFromBottom < 96;
    isNearBottomRef.current = nearBottom;
    return nearBottom;
  };

  const maybeReportRead = () => {
    if (document.visibilityState !== 'visible' || !isNearBottomRef.current) return;
    const newest = [...messagesRef.current]
      .reverse()
      .find((m) => m.type === 'chat' && Number.isInteger(m.id));
    if (!newest || newest.id <= lastReportedReadIdRef.current) return;
    clearTimeout(readStateTimerRef.current);
    readStateTimerRef.current = setTimeout(() => {
      lastReportedReadIdRef.current = newest.id;
      updateReadState(newest.id).catch(() => {});
    }, READ_STATE_DEBOUNCE_MS);
  };

  // Scroll to bottom on initial history load (not when navigating to a target).
  useEffect(() => {
    if (targetMessageId || hasInitialScrolledRef.current || messages.length === 0) return;
    hasInitialScrolledRef.current = true;
    scrollListToBottom('auto');
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messages.length, targetMessageId]);

  // Scroll to bottom when a new live message arrives.
  useEffect(() => {
    if (!newMessageId) return;
    if (isNearBottomRef.current) {
      scrollListToBottom('smooth');
    }
  }, [newMessageId]);

  useEffect(() => {
    hasScrolledToTargetRef.current = false;
    setFocusedMessageId(targetMessageId);
  }, [targetMessageId]);

  useEffect(() => {
    if (!highlightMessageId || !messages.length || hasScrolledToTargetRef.current) return;
    const target = messageRefs.current[highlightMessageId];
    if (target) {
      hasScrolledToTargetRef.current = true;
      target.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }, [messages, highlightMessageId]);

  useEffect(() => {
    const lastMessage = messages[messages.length - 1];

    if (!lastMessage) {
      previousLastMessageIdRef.current = null;
      setNewMessageId(null);
      return;
    }

    const previousLastMessageId = previousLastMessageIdRef.current;
    previousLastMessageIdRef.current = lastMessage.id;

    if (
      lastMessage.id !== previousLastMessageId &&
      lastMessage.type === 'chat' &&
      lastMessage.isLive
    ) {
      setNewMessageId(lastMessage.id);
      if (!isNearBottomRef.current) {
        setUnreadFabCount((c) => c + 1);
      }
    }

    maybeReportRead();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messages]);

  // Report read state when the tab becomes visible again, clean up the timer on unmount.
  useEffect(() => {
    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible') maybeReportRead();
    };
    document.addEventListener('visibilitychange', onVisibilityChange);
    return () => {
      document.removeEventListener('visibilitychange', onVisibilityChange);
      clearTimeout(readStateTimerRef.current);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleMessageTap = (msgId) => {
    setActiveMsgId(prev => prev === msgId ? null : msgId);
  };

  const handleQuoteClick = (messageId) => {
    if (!messageId) return;
    setActiveMsgId(null);

    const target = messageRefs.current[messageId];
    if (target) {
      setFocusedMessageId(messageId);
      hasScrolledToTargetRef.current = true;
      target.scrollIntoView({ behavior: 'smooth', block: 'center' });
      return;
    }

    navigateTo(buildChatMessageHref(messageId));
  };

  // Close active actions when clicking anywhere outside a message.
  useEffect(() => {
    if (!activeMsgId) return;
    const close = (e) => {
      if (!e.target.closest('.message.chat')) setActiveMsgId(null);
    };
    document.addEventListener('click', close);
    return () => document.removeEventListener('click', close);
  }, [activeMsgId]);

  useEffect(() => () => {
    onMobileNavVisibilityChange?.(false);
  }, [onMobileNavVisibilityChange]);

  const handleScroll = () => {
    const list = listRef.current;
    if (!list) return;
    const nearBottom = updateNearBottom();
    setShowScrollFab(!nearBottom);
    if (nearBottom) {
      setUnreadFabCount(0);
      maybeReportRead();
    }

    const top = list.scrollTop;
    const delta = top - lastScrollTopRef.current;
    const threshold = 14;

    if (delta < -threshold && !hiddenNavRef.current) {
      hiddenNavRef.current = true;
      onMobileNavVisibilityChange?.(true);
    } else if (delta > threshold && hiddenNavRef.current) {
      hiddenNavRef.current = false;
      onMobileNavVisibilityChange?.(false);
    }

    if (Math.abs(delta) > threshold) {
      lastScrollTopRef.current = top;
    }
  };

  const handleFabClick = () => {
    scrollListToBottom('smooth');
    setUnreadFabCount(0);
    if (navigator.vibrate) navigator.vibrate(15);
  };

  return (
    <div className="message-list" ref={listRef} onScroll={handleScroll}>
      {hasOlderMessages && (
        <button
          type="button"
          className="load-older-btn"
          onClick={loadOlderMessages}
          disabled={isLoadingOlder}
        >
          {isLoadingOlder ? 'Loading older messages…' : 'Load older messages'}
        </button>
      )}
      {messages.map((message) => (
        <div
          key={message.id}
          ref={(node) => {
            if (node) messageRefs.current[message.id] = node;
            else delete messageRefs.current[message.id];
          }}
          className={[
            highlightedMessageIdSet.has(message.id) ? 'message-target-highlight' : '',
            message.id === focusedMessageId ? 'message-target-highlight' : '',
            message.id === newMessageId ? 'message-list-item--new' : '',
          ].filter(Boolean).join(' ')}
        >
          <Message
            message={message}
            isMe={message.isMe}
            currentSessionId={currentSessionId}
            showActions={message.id === activeMsgId}
            onTap={() => handleMessageTap(message.id)}
            onReply={onReply}
            onToggleReaction={onToggleReaction}
            onDeleteMessage={onDeleteMessage}
            onEditMessage={onEditMessage}
            onPinMessage={onPinMessage}
            canPin={canPin}
            onOpenPhoto={onOpenPhoto}
            onQuoteClick={handleQuoteClick}
            quickEmojis={quickEmojis}
          />
        </div>
      ))}
      {showScrollFab && (
        <button
          type="button"
          className="scroll-to-bottom-fab"
          onClick={handleFabClick}
          aria-label="Scroll to latest messages"
        >
          ↓{unreadFabCount > 0 && <span className="scroll-to-bottom-fab__badge">{unreadFabCount}</span>}
        </button>
      )}
    </div>
  );
};

export default MessageList;
