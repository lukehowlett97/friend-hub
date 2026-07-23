import React from 'react';
import UserAvatar from '../Chat/UserAvatar.jsx';
import './OnlineMembersModal.css';

const PERMISSION_LABELS = { owner: 'Owner', admin: 'Admin', member: 'Member' };

const OnlineMembersModal = ({ users, loading = false, error = '', onlineCount = 0, currentSessionId, onNavigate, onClose }) => {
  const handleUserClick = (user) => {
    if (user.username) {
      onNavigate(`/profile/${user.username}`);
    } else if (user.session_id === currentSessionId) {
      onNavigate('/profile');
    }
    onClose();
  };

  return (
    <div className="online-members-backdrop" role="presentation" onClick={onClose}>
      <aside
        className="online-members-modal"
        role="dialog"
        aria-modal="true"
        aria-label="Members"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="online-members-header">
          <div>
            <h2>
              Members
              <span className="online-members-count">— {users.length}</span>
            </h2>
            <p>{onlineCount} online now</p>
          </div>
          <button
            type="button"
            className="online-members-close"
            onClick={onClose}
            aria-label="Close members"
          >
            ×
          </button>
        </div>

        <ul className="online-members-list">
          {loading ? (
            <li className="online-member-empty">Loading members…</li>
          ) : error ? (
            <li className="online-member-empty online-member-empty--error">{error}</li>
          ) : users.length > 0 ? (
            users.map((user) => {
              const isYou = user.session_id === currentSessionId;
              const permissionLabel = PERMISSION_LABELS[user.role];
              const chatRole = user.display_role;
              const roleLabel = chatRole || 'Citizen';

              return (
                <li key={user.session_id || user.id || user.username}>
                  <button
                    type="button"
                    className="online-member-card"
                    onClick={() => handleUserClick(user)}
                    title={`View ${user.nickname}'s profile`}
                  >
                    <span className="online-member-avatar-wrap">
                      <UserAvatar
                        nickname={user.nickname}
                        size={42}
                        avatarUrl={user.avatar_url}
                        avatarEmoji={user.avatar_emoji}
                      />
                      <span
                        className={`online-member-presence${user.is_online ? ' is-online' : ''}`}
                        aria-label={user.is_online ? 'Online' : 'Offline'}
                      />
                    </span>

                    <span className="online-member-info">
                      <span className="online-member-nickname">
                        {user.nickname}
                        {isYou && <span className="online-member-you"> (you)</span>}
                      </span>
                      {user.username && (
                        <span className="online-member-username">@{user.username}</span>
                      )}
                      <span className="online-member-roleline">{roleLabel}</span>
                    </span>

                    <span className="online-member-badges">
                      {user.role !== 'member' && permissionLabel && (
                        <span className={`online-member-badge online-member-badge--permission online-member-badge--${user.role}`}>{permissionLabel}</span>
                      )}
                      {user.is_online && (
                        <span className="online-member-badge online-member-badge--online">Online</span>
                      )}
                    </span>
                  </button>
                </li>
              );
            })
          ) : (
            <li className="online-member-empty">No members yet.</li>
          )}
        </ul>
      </aside>
    </div>
  );
};

export default OnlineMembersModal;
