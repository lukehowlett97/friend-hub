import React from 'react';
import UserAvatar from '../Chat/UserAvatar.jsx';
import { formatRelativeTime, formatAbsoluteDate } from './ActivityFeedTypes.js';
import './ActivityFeedCards.css';

/**
 * Status badge component for activities
 */
const StatusBadge = ({ status, label, animated = false }) => {
  if (!status) return null;

  const badgeConfig = {
    active: { color: '#10b981', label: 'Active' },
    pinned: { color: '#f59e0b', label: 'Pinned' },
    'closing-soon': { color: '#ef4444', label: 'Closing soon' },
    unresolved: { color: '#6b7280', label: 'Unresolved' },
    new: { color: '#8b5cf6', label: 'New' },
    live: { color: '#ef4444', label: 'Live' },
    overdue: { color: '#dc2626', label: 'Overdue' },
    'due-today': { color: '#f59e0b', label: 'Today' },
    'due-soon': { color: '#f97316', label: 'Due soon' },
    today: { color: '#10b981', label: 'Today' },
    tomorrow: { color: '#3b82f6', label: 'Tomorrow' },
  };

  const config = badgeConfig[status];
  if (!config) return null;

  return (
    <span
      className={`activity-badge${animated ? ' activity-badge--animated' : ''}`}
      style={{ '--badge-color': config.color }}
      title={config.label}
    >
      {label || config.label}
    </span>
  );
};

/**
 * Pinned item activity card
 */
export const PinnedItemCard = ({ activity, onNavigate }) => {
  return (
    <button
      type="button"
      className="activity-feed-card pinned-item-card"
      onClick={() => onNavigate(activity.route)}
      aria-label={`Pinned: ${activity.title}`}
    >
      <div className="activity-card-header">
        <span className="activity-card-icon">{activity.icon}</span>
        <div className="activity-card-meta">
          <h3 className="activity-card-title">{activity.title}</h3>
          {activity.shortId && <span className="activity-card-id">#{activity.shortId}</span>}
          {activity.commentCount > 0 && (
            <span className="activity-card-subtitle">{activity.commentCount} new comment{activity.commentCount !== 1 ? 's' : ''}</span>
          )}
        </div>
        <StatusBadge status="pinned" />
      </div>
    </button>
  );
};

/**
 * Active poll activity card
 */
export const ActivePollCard = ({ activity, onNavigate }) => {
  const votePercentage = activity.totalVoters > 0
    ? Math.round((activity.responseCount / activity.totalVoters) * 100)
    : 0;

  return (
    <button
      type="button"
      className="activity-feed-card active-poll-card"
      onClick={() => onNavigate(activity.route)}
      aria-label={`Poll: ${activity.title}`}
    >
      <div className="activity-card-header">
        <span className="activity-card-icon">🗳️</span>
        <div className="activity-card-meta">
          <h3 className="activity-card-title">{activity.title}</h3>
          <span className="activity-card-subtitle">
            {activity.responseCount}/{activity.totalVoters} voted
          </span>
        </div>
        <StatusBadge status={activity.status} />
      </div>
      <div className="poll-progress">
        <div className="poll-progress-bar">
          <div className="poll-progress-fill" style={{ width: `${votePercentage}%` }} />
        </div>
        <span className="poll-progress-text">{votePercentage}%</span>
      </div>
    </button>
  );
};

/**
 * Upcoming event activity card
 */
export const UpcomingEventCard = ({ activity, onNavigate }) => {
  return (
    <button
      type="button"
      className="activity-feed-card upcoming-event-card"
      onClick={() => onNavigate(activity.route)}
      aria-label={`Event: ${activity.title}`}
    >
      <div className="activity-card-header">
        <span className="activity-card-icon">📅</span>
        <div className="activity-card-meta">
          <h3 className="activity-card-title">{activity.title}</h3>
          <span className="activity-card-subtitle">
            {formatAbsoluteDate(activity.startsAt)}
            {activity.location && ` · ${activity.location}`}
          </span>
        </div>
        <StatusBadge status={activity.status} />
      </div>
      {activity.attendeeCount > 0 && (
        <div className="event-attendees">
          <span className="event-attendee-count">{activity.attendeeCount} attendee{activity.attendeeCount !== 1 ? 's' : ''}</span>
        </div>
      )}
    </button>
  );
};

/**
 * AI memory/suggestion activity card
 */
export const AIMemoryCard = ({ activity, onNavigate }) => {
  return (
    <button
      type="button"
      className="activity-feed-card ai-memory-card"
      onClick={() => activity.actionRoute ? onNavigate(activity.actionRoute) : null}
      aria-label={`AI suggestion: ${activity.suggestion}`}
    >
      <div className="activity-card-header">
        <span className="activity-card-icon">✨</span>
        <div className="activity-card-meta">
          <h3 className="activity-card-title activity-card-title--suggestion">{activity.suggestion}</h3>
          {activity.context && <span className="activity-card-subtitle">{activity.context}</span>}
        </div>
      </div>
      {activity.actionRoute && (
        <div className="ai-action-bar">
          <button
            type="button"
            className="ai-action-btn"
            onClick={(e) => {
              e.stopPropagation();
              onNavigate(activity.actionRoute);
            }}
          >
            {activity.actionLabel || 'View'} →
          </button>
        </div>
      )}
    </button>
  );
};

/**
 * Photo upload activity card
 */
export const PhotoUploadCard = ({ activity, onNavigate }) => {
  return (
    <button
      type="button"
      className="activity-feed-card photo-upload-card"
      onClick={() => onNavigate(activity.route)}
      aria-label={`${activity.count} photos uploaded to ${activity.folderName}`}
    >
      <div className="activity-card-header">
        <span className="activity-card-icon">📸</span>
        <div className="activity-card-meta">
          <h3 className="activity-card-title">
            {activity.uploaderName || 'Someone'} added {activity.count} photo{activity.count !== 1 ? 's' : ''}
          </h3>
          <span className="activity-card-subtitle">{activity.folderName}</span>
        </div>
      </div>
      {activity.uploaderAvatar && (
        <div className="photo-uploader">
          <UserAvatar nickname={activity.uploaderName} size={24} avatarUrl={activity.uploaderAvatar} />
        </div>
      )}
    </button>
  );
};

/**
 * Recent edit/comment activity card
 */
export const RecentEditCard = ({ activity, onNavigate }) => {
  const changeIconMap = {
    comment: '💬',
    edit: '✏️',
    'status-update': '✔️',
  };

  return (
    <button
      type="button"
      className="activity-feed-card recent-edit-card"
      onClick={() => onNavigate(activity.route)}
      aria-label={`${activity.changeType} on ${activity.itemTitle}`}
    >
      <div className="activity-card-header">
        <span className="activity-card-icon">{changeIconMap[activity.changeType] || '✏️'}</span>
        <div className="activity-card-meta">
          <h3 className="activity-card-title">{activity.itemTitle}</h3>
          <span className="activity-card-subtitle">
            {activity.editorName || 'Someone'} {activity.changeType === 'comment' ? 'commented' : 'updated'}
            {activity.timestamp && ` · ${formatRelativeTime(activity.timestamp)}`}
          </span>
        </div>
      </div>
    </button>
  );
};

/**
 * Open reminder activity card
 */
export const OpenReminderCard = ({ activity, onNavigate }) => {
  return (
    <button
      type="button"
      className="activity-feed-card open-reminder-card"
      onClick={() => onNavigate(activity.route)}
      aria-label={`Reminder: ${activity.title}`}
    >
      <div className="activity-card-header">
        <span className="activity-card-icon">⏰</span>
        <div className="activity-card-meta">
          <h3 className="activity-card-title">{activity.title}</h3>
          <span className="activity-card-subtitle">
            Due {formatAbsoluteDate(activity.dueAt)}
            {activity.assignees?.length > 0 && ` · Assigned to ${activity.assignees.join(', ')}`}
          </span>
        </div>
        <StatusBadge status={activity.status} animated={activity.status === 'overdue'} />
      </div>
    </button>
  );
};

/**
 * Hub item update activity card
 */
export const HubItemUpdateCard = ({ activity, onNavigate }) => {
  const updateIconMap = {
    new: '🆕',
    updated: '🔄',
    active: '◆',
  };

  return (
    <button
      type="button"
      className="activity-feed-card hub-item-update-card"
      onClick={() => onNavigate(activity.route)}
      aria-label={`Item update: ${activity.title}`}
    >
      <div className="activity-card-header">
        <span className="activity-card-icon">{updateIconMap[activity.updateType] || '◆'}</span>
        <div className="activity-card-meta">
          <h3 className="activity-card-title">{activity.title}</h3>
          {activity.actionCount > 0 && (
            <span className="activity-card-subtitle">
              {activity.actionCount} unresolved action{activity.actionCount !== 1 ? 's' : ''}
            </span>
          )}
        </div>
        <StatusBadge status={activity.updateType === 'new' ? 'new' : 'active'} />
      </div>
    </button>
  );
};

/**
 * Generic activity card renderer that dispatches to specific card type
 */
export const ActivityCard = ({ activity, onNavigate }) => {
  switch (activity.type) {
    case 'pinned-item':
      return <PinnedItemCard activity={activity} onNavigate={onNavigate} />;
    case 'active-poll':
      return <ActivePollCard activity={activity} onNavigate={onNavigate} />;
    case 'upcoming-event':
      return <UpcomingEventCard activity={activity} onNavigate={onNavigate} />;
    case 'ai-memory':
      return <AIMemoryCard activity={activity} onNavigate={onNavigate} />;
    case 'photo-upload':
      return <PhotoUploadCard activity={activity} onNavigate={onNavigate} />;
    case 'recent-edit':
      return <RecentEditCard activity={activity} onNavigate={onNavigate} />;
    case 'open-reminder':
      return <OpenReminderCard activity={activity} onNavigate={onNavigate} />;
    case 'hub-item-update':
      return <HubItemUpdateCard activity={activity} onNavigate={onNavigate} />;
    default:
      return null;
  }
};
