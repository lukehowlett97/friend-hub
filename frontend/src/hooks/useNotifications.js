import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchNotifications, markAllNotificationsRead, markNotificationRead } from '../services/api.js';

const POLL_INTERVAL = 30000;

export default function useNotifications() {
  const [notifications, setNotifications] = useState([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const intervalRef = useRef(null);

  const load = useCallback(async () => {
    try {
      const data = await fetchNotifications();
      setNotifications(data.notifications || []);
      setUnreadCount(data.unread_count || 0);
    } catch { /* silently ignore */ }
  }, []);

  useEffect(() => {
    load();
    intervalRef.current = setInterval(load, POLL_INTERVAL);
    return () => clearInterval(intervalRef.current);
  }, [load]);

  const markRead = useCallback(async (id) => {
    await markNotificationRead(id);
    setNotifications(prev => prev.map(n => n.id === id ? { ...n, is_read: true } : n));
    setUnreadCount(prev => Math.max(0, prev - 1));
  }, []);

  const markAllRead = useCallback(async () => {
    await markAllNotificationsRead();
    setNotifications(prev => prev.map(n => ({ ...n, is_read: true })));
    setUnreadCount(0);
  }, []);

  // Called by WS handler when a real-time notification arrives
  const addNotification = useCallback((notif) => {
    setNotifications(prev => [notif, ...prev].slice(0, 30));
    setUnreadCount(prev => prev + 1);
  }, []);

  // Subscribe to window custom events dispatched by the WS hook
  useEffect(() => {
    const handler = (e) => {
      const n = e.detail;
      addNotification({
        id: n.notification_id,
        type: n.notif_type,
        title: n.title,
        body: n.body,
        target_type: n.target_type,
        target_id: n.target_id,
        is_read: false,
        created_at: new Date().toISOString(),
      });
    };
    window.addEventListener('friend-hub-notification', handler);
    return () => window.removeEventListener('friend-hub-notification', handler);
  }, [addNotification]);

  return { notifications, unreadCount, markRead, markAllRead, addNotification, refresh: load };
}
