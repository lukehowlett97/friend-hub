import React from 'react';
import UserAvatar from './UserAvatar';
import './OnlineUsers.css';

const OnlineUsers = ({ users = [], currentSessionId }) => (
  <aside className="online-users">
    <div className="online-users-header">
      <span className="online-dot" />
      Online — {users.length}
    </div>
    <ul className="online-users-list">
      {users.map(user => (
        <li key={user.session_id} className="online-user">
          <UserAvatar nickname={user.nickname} size={28} />
          <span className="online-user-name">
            {user.nickname}
            {user.session_id === currentSessionId && (
              <span className="online-user-you"> (you)</span>
            )}
          </span>
        </li>
      ))}
      {users.length === 0 && (
        <li className="online-user-empty">No one else here yet</li>
      )}
    </ul>
  </aside>
);

export default OnlineUsers;
