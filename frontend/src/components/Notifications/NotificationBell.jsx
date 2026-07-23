import React, { useRef, useState, useEffect } from 'react';
import useNotifications from '../../hooks/useNotifications.js';
import './NotificationBell.css';

const TYPE_ICONS = { comment: '💬', new_poll: '📊', new_event: '📅', reaction: '❤️' };
const TYPE_LABELS = { comment: 'Comment', new_poll: 'New poll', new_event: 'New event', reaction: 'Reaction' };

function getNotificationUrl(n) {
  const { type, target_type, target_id } = n;
  if (target_type === 'event' && target_id) return `/events/${target_id}`;
  if (target_type === 'poll' && target_id) return `/polls`;
  if (target_type === 'item' && target_id) return `/items`;
  if (type === 'new_event' && target_id) return `/events/${target_id}`;
  if (type === 'new_poll') return `/polls`;
  if (type === 'comment' && target_id) return `/events/${target_id}`;
  return null;
}

function timeAgo(isoString) {
  const diff = (Date.now() - new Date(isoString)) / 1000;
  if (diff < 60) return 'just now';
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

export default function NotificationBell({ onWsNotification, onNavigate }) {
  const { notifications, unreadCount, markRead, markAllRead, addNotification } = useNotifications();
  const [isOpen, setIsOpen] = useState(false);
  const panelRef = useRef(null);

  // Expose addNotification to parent (for WS delivery)
  useEffect(() => {
    if (onWsNotification) onWsNotification(addNotification);
  }, [onWsNotification, addNotification]);

  // Close when clicking outside
  useEffect(() => {
    if (!isOpen) return;
    const handler = (e) => {
      if (panelRef.current && !panelRef.current.contains(e.target)) setIsOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [isOpen]);

  const handleOpen = () => {
    setIsOpen(v => !v);
  };

  const handleNotificationClick = async (n) => {
    if (!n.is_read) await markRead(n.id);
    const url = getNotificationUrl(n);
    if (url && onNavigate) {
      setIsOpen(false);
      onNavigate(url);
    }
  };

  return (
    <div className="notif-bell-wrap" ref={panelRef}>
      <button className="notif-bell-btn" onClick={handleOpen} title="Notifications">
        🔔
        {unreadCount > 0 && (
          <span className="notif-badge">{unreadCount > 9 ? '9+' : unreadCount}</span>
        )}
      </button>

      {isOpen && (
        <div className="notif-panel">
          <div className="notif-panel-header">
            <span>Notifications</span>
            {unreadCount > 0 && (
              <button className="notif-mark-all" onClick={markAllRead}>Mark all read</button>
            )}
          </div>
          <ul className="notif-list">
            {notifications.length === 0 && (
              <li className="notif-empty">Nothing here yet</li>
            )}
            {notifications.map(n => (
              <li
                key={n.id}
                className={`notif-item${n.is_read ? '' : ' unread'}`}
                onClick={() => handleNotificationClick(n)}
                style={getNotificationUrl(n) ? { cursor: 'pointer' } : {}}
              >
                <span className="notif-icon">{TYPE_ICONS[n.type] || '🔔'}</span>
                <div className="notif-body">
                  <p className="notif-title">{n.title}</p>
                  <span className="notif-meta">{TYPE_LABELS[n.type] || n.type} · {timeAgo(n.created_at)}</span>
                </div>
                {!n.is_read && <span className="notif-dot" />}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
