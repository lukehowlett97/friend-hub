import { useState, useEffect, useRef, useCallback } from 'react';
import { apiFetch, getCurrentRoomSlug, getToken } from '../api/client.js';

const getApiBase = () => window.location.origin;

const getWsBase = () => {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${window.location.host}`;
};

const MAX_RECONNECT_ATTEMPTS = 5;
const RECONNECT_DELAY = 3000;
const HISTORY_LIMIT = 50;

const mapHistoryMessage = (msg, currentSessionId) => ({
  id: msg.id,
  content: msg.content,
  sender: msg.session_id === currentSessionId ? 'You' : (msg.nickname || msg.session_id),
  nickname: msg.nickname,
  username: msg.username || null,
  avatar_url: msg.avatar_url || null,
  avatar_emoji: msg.avatar_emoji || null,
  display_role: msg.display_role || null,
  role: msg.role || null,
  is_bot: !!msg.is_bot,
  session_id: msg.session_id,
  isMe: msg.session_id === currentSessionId,
  timestamp: msg.created_at,
  type: 'chat',
  reply_to: msg.reply_to || null,
  reactions: msg.reactions || [],
  isDeleted: !!msg.is_deleted,
  isEdited: !!msg.edited_at,
  edited_at: msg.edited_at || null,
  isImported: !!msg.is_imported,
  sourceProvider: msg.source_provider || null,
  isLive: false,
});

const useWebSocket = () => {
  const [isConnected, setIsConnected]           = useState(false);
  const [isConnecting, setIsConnecting]         = useState(false);
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);
  const [isLoadingOlder, setIsLoadingOlder]     = useState(false);
  const [hasOlderMessages, setHasOlderMessages] = useState(false);
  const [messages, setMessages]                 = useState([]);
  const [sessionId, setSessionId]               = useState(null);  // user's session_id (users PK)
  const [connectionError, setConnectionError]   = useState(null);
  const [onlineUsers, setOnlineUsers]           = useState([]);
  const [typingUsers, setTypingUsers]           = useState({});

  const wsRef                = useRef(null);
  const reconnectTimeoutRef  = useRef(null);
  const reconnectAttemptsRef = useRef(0);
  const sessionIdRef         = useRef(null);
  const shouldReconnectRef   = useRef(false);
  const historyOffsetRef     = useRef(0);
  const isContextModeRef     = useRef(false);
  const oldestTimestampRef   = useRef(null);

  // ── Helpers ───────────────────────────────────────────────────────────────

  const addMessage = useCallback((message) => {
    setMessages(prev => [...prev, message]);
  }, []);

  const addSystemMessage = useCallback((content, type = 'system') => {
    addMessage({
      id: Date.now() + Math.random(),
      content,
      sender: 'System',
      isMe: false,
      timestamp: new Date().toISOString(),
      type,
    });
  }, [addMessage]);

  const clearReconnectTimeout = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
  }, []);

  // ── Message history ───────────────────────────────────────────────────────

  const loadMessageHistory = useCallback(async (currentSessionId, targetMessageId = null) => {
    setIsLoadingHistory(true);
    try {
      const path = targetMessageId
        ? `/api/v1/messages/${targetMessageId}/context?before=30&after=30`
        : `/api/v1/messages?limit=${HISTORY_LIMIT}`;
      const response = await apiFetch(`${getApiBase()}${path}`);
      if (!response.ok) return;
      const data = await response.json();

      const history = data.messages.map(msg => mapHistoryMessage(msg, currentSessionId));

      setMessages(history);
      isContextModeRef.current = !!targetMessageId;
      oldestTimestampRef.current = history.length > 0 ? history[0].timestamp : null;
      historyOffsetRef.current = history.length;
      setHasOlderMessages(targetMessageId ? history.length > 0 : history.length === HISTORY_LIMIT);
    } catch (err) {
      console.error('Error loading history:', err);
      addSystemMessage('Failed to load message history', 'error');
    } finally {
      setIsLoadingHistory(false);
    }
  }, [addSystemMessage]);

  const loadOlderMessages = useCallback(async () => {
    const currentSessionId = sessionIdRef.current;
    if (!currentSessionId || isLoadingOlder || !hasOlderMessages) return;
    setIsLoadingOlder(true);
    try {
      let url;
      if (isContextModeRef.current && oldestTimestampRef.current) {
        url = `${getApiBase()}/api/v1/messages?limit=${HISTORY_LIMIT}&end_at=${encodeURIComponent(oldestTimestampRef.current)}`;
      } else {
        url = `${getApiBase()}/api/v1/messages?limit=${HISTORY_LIMIT}&offset=${historyOffsetRef.current}`;
      }
      const response = await apiFetch(url);
      if (!response.ok) return;
      const data = await response.json();
      const older = data.messages.map(msg => mapHistoryMessage(msg, currentSessionId));
      if (older.length > 0) {
        setMessages(prev => [...older, ...prev]);
        oldestTimestampRef.current = older[0].timestamp;
        if (!isContextModeRef.current) historyOffsetRef.current += older.length;
      }
      setHasOlderMessages(older.length === HISTORY_LIMIT);
    } catch (err) {
      console.error('Error loading older history:', err);
      addSystemMessage('Failed to load older history', 'error');
    } finally {
      setIsLoadingOlder(false);
    }
  }, [addSystemMessage, hasOlderMessages, isLoadingOlder]);

  // ── Incoming event handler ────────────────────────────────────────────────

  const handleMessage = useCallback((data, targetMessageId = null) => {
    const currentSid = sessionIdRef.current;

    switch (data.type) {

      case 'connection':
        setConnectionError(null);
        reconnectAttemptsRef.current = 0;
        if (data.session_id) {
          setSessionId(data.session_id);
          sessionIdRef.current = data.session_id;
          loadMessageHistory(data.session_id, targetMessageId);
        }
        break;

      case 'online_users':
        setOnlineUsers(data.users || []);
        break;

      case 'typing_indicator':
        setTypingUsers(prev => {
          const next = { ...prev };
          if (data.is_typing) {
            next[data.session_id] = data.nickname;
          } else {
            delete next[data.session_id];
          }
          return next;
        });
        break;

      case 'user_joined':
        break;

      case 'user_disconnected':
        setTypingUsers(prev => {
          const next = { ...prev };
          delete next[data.session_id];
          return next;
        });
        break;

      case 'message': {
        const isMe = data.session_id === currentSid;
        addMessage({
          id: data.message_id || Date.now() + Math.random(),
          content: data.content,
          sender: isMe ? 'You' : (data.nickname || data.session_id),
          nickname: data.nickname,
          username: data.username || null,
          avatar_url: data.avatar_url || null,
          avatar_emoji: data.avatar_emoji || null,
          display_role: data.display_role || null,
          role: data.role || null,
          is_bot: !!data.is_bot,
          session_id: data.session_id,
          isMe,
          timestamp: data.timestamp || new Date().toISOString(),
          type: 'chat',
          reply_to: data.reply_to || null,
          reactions: data.reactions || [],
          isLive: true,
          is_new_outgoing: isMe,
        });
        break;
      }

      case 'reaction_updated':
        setMessages(prev =>
          prev.map(msg =>
            msg.id === data.message_id ? { ...msg, reactions: data.reactions } : msg
          )
        );
        break;

      case 'message_deleted':
        setMessages(prev =>
          prev.map(msg =>
            msg.id === data.message_id
              ? { ...msg, content: '[message deleted]', isDeleted: true }
              : msg
          )
        );
        break;

      case 'message_edited':
        setMessages(prev =>
          prev.map(msg =>
            msg.id === data.message_id
              ? { ...msg, content: data.content, edited_at: data.edited_at, isEdited: true }
              : msg
          )
        );
        break;

      case 'notification':
        window.dispatchEvent(new CustomEvent('friend-hub-notification', { detail: data }));
        break;

      case 'pong':
        break;

      case 'error':
        // Auth errors on the WS (4001 close) are handled in onclose.
        break;

      default:
        break;
    }
  }, [addMessage, addSystemMessage, loadMessageHistory]);

  // ── Core WebSocket builder ────────────────────────────────────────────────

  const createWebSocketConnection = useCallback((targetMessageId = null) => {
    if (wsRef.current) wsRef.current.close();
    clearReconnectTimeout();

    const token = getToken();
    if (!token) {
      setConnectionError('Not authenticated');
      setIsConnecting(false);
      return;
    }

    const params = new URLSearchParams({ token });
    const roomSlug = getCurrentRoomSlug();
    if (roomSlug) params.set('room', roomSlug);
    const ws = new WebSocket(`${getWsBase()}/ws?${params.toString()}`);

    ws.onopen = () => {
      setIsConnected(true);
      setIsConnecting(false);
      setConnectionError(null);
      shouldReconnectRef.current = true;
      reconnectAttemptsRef.current = 0;
      // session_id and message history loaded when 'connection' event arrives

      // Tell the server our current foreground state so chat-message push
      // fanout can skip live viewers and target backgrounded tabs.
      try {
        ws.send(JSON.stringify({
          type: 'visibility',
          visible: typeof document !== 'undefined' ? document.visibilityState !== 'hidden' : true,
        }));
      } catch { /* socket already gone */ }
    };

    ws.onmessage = (event) => {
      try {
        handleMessage(JSON.parse(event.data), targetMessageId);
      } catch (err) {
        console.error('WS parse error:', err);
      }
    };

    ws.onclose = (event) => {
      setIsConnected(false);
      setIsConnecting(false);

      if (event.code === 4001) {
        setConnectionError('Authentication failed');
        shouldReconnectRef.current = false;
        return;
      }

      if (!shouldReconnectRef.current) return;

      if (event.code === 1000) {
        addSystemMessage('Disconnected from chat');
        return;
      }

      if (reconnectAttemptsRef.current >= MAX_RECONNECT_ATTEMPTS) {
        addSystemMessage('Failed to reconnect. Please refresh the page.', 'error');
        setConnectionError('Connection failed');
        return;
      }

      addSystemMessage('Connection lost. Attempting to reconnect...', 'error');
      reconnectTimeoutRef.current = setTimeout(() => {
        if (!shouldReconnectRef.current) return;
        reconnectAttemptsRef.current += 1;
        setIsConnecting(true);
        addSystemMessage(`Reconnecting… (${reconnectAttemptsRef.current}/${MAX_RECONNECT_ATTEMPTS})`);
        createWebSocketConnection(targetMessageId);
      }, RECONNECT_DELAY);
    };

    ws.onerror = () => {
      setIsConnecting(false);
      setConnectionError('Connection error');
    };

    wsRef.current = ws;
  }, [handleMessage, addSystemMessage, clearReconnectTimeout]);

  // ── Public API ────────────────────────────────────────────────────────────

  const connect = useCallback((targetMessageId = null) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;
    shouldReconnectRef.current = true;
    setIsConnecting(true);
    setConnectionError(null);
    reconnectAttemptsRef.current = 0;
    createWebSocketConnection(targetMessageId);
  }, [createWebSocketConnection]);

  const disconnect = useCallback(() => {
    clearReconnectTimeout();
    shouldReconnectRef.current = false;
    sessionIdRef.current = null;
    reconnectAttemptsRef.current = 0;
    setOnlineUsers([]);
    setTypingUsers({});
    setSessionId(null);

    if (wsRef.current) {
      wsRef.current.close(1000, 'User disconnected');
      wsRef.current = null;
      setIsConnected(false);
      setIsConnecting(false);
      setConnectionError(null);
    }
  }, [clearReconnectTimeout]);

  const sendMessage = useCallback((content, replyToId) => {
    if (!content.trim() || wsRef.current?.readyState !== WebSocket.OPEN) return false;
    const payload = { type: 'message', content: content.trim() };
    if (replyToId) payload.reply_to_id = replyToId;
    wsRef.current.send(JSON.stringify(payload));
    return true;
  }, []);

  const sendTyping = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'typing' }));
    }
  }, []);

  const sendStopTyping = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'stop_typing' }));
    }
  }, []);

  const deleteMessage = useCallback((messageId) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'delete_message', message_id: messageId }));
    }
  }, []);

  const editMessage = useCallback((messageId, content) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'edit_message', message_id: messageId, content }));
    }
  }, []);

  const toggleReaction = useCallback((messageId, emoji) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'toggle_reaction', message_id: messageId, emoji }));
    }
  }, []);

  const updateMessageReactions = useCallback((messageId, reactions) => {
    setMessages(prev =>
      prev.map(msg => msg.id === messageId ? { ...msg, reactions } : msg)
    );
  }, []);

  const updateMessagePinned = useCallback((messageId, isPinned) => {
    setMessages(prev =>
      prev.map(msg => msg.id === messageId ? { ...msg, is_pinned: isPinned } : msg)
    );
  }, []);

  const ping = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'ping' }));
    }
  }, []);

  // ── Effects ───────────────────────────────────────────────────────────────

  useEffect(() => {
    return () => {
      clearReconnectTimeout();
      shouldReconnectRef.current = false;
      wsRef.current?.close();
    };
  }, [clearReconnectTimeout]);

  useEffect(() => {
    if (!isConnected) return;
    const id = setInterval(ping, 30000);
    return () => clearInterval(id);
  }, [isConnected, ping]);

  // Broadcast tab-foreground state so the backend can decide between live
  // delivery and a push notification. Fires on visibilitychange + focus/blur
  // (mobile Safari sometimes emits one but not the other).
  useEffect(() => {
    if (!isConnected) return;
    const sendVisibility = () => {
      if (wsRef.current?.readyState !== WebSocket.OPEN) return;
      const visible = document.visibilityState !== 'hidden' && document.hasFocus?.() !== false;
      try {
        wsRef.current.send(JSON.stringify({ type: 'visibility', visible }));
      } catch { /* socket gone */ }
    };
    document.addEventListener('visibilitychange', sendVisibility);
    window.addEventListener('focus', sendVisibility);
    window.addEventListener('blur', sendVisibility);
    return () => {
      document.removeEventListener('visibilitychange', sendVisibility);
      window.removeEventListener('focus', sendVisibility);
      window.removeEventListener('blur', sendVisibility);
    };
  }, [isConnected]);

  return {
    isConnected,
    isConnecting,
    isLoadingHistory,
    isLoadingOlder,
    hasOlderMessages,
    messages,
    sessionId,
    connectionError,
    onlineUsers,
    typingUsers,
    connect,
    disconnect,
    sendMessage,
    sendTyping,
    sendStopTyping,
    loadOlderMessages,
    ping,
    toggleReaction,
    deleteMessage,
    editMessage,
    updateMessageReactions,
    updateMessagePinned,
    clearMessages: () => setMessages([]),
    addMessage,
  };
};

export default useWebSocket;
