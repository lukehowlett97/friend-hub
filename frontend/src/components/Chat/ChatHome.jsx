import React, { useState, useEffect } from 'react';
import UserAvatar from './UserAvatar';
import './ChatHome.css';

const ChatHome = ({ onEnterChat, onlineUsers = [] }) => {
  const [members, setMembers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchMembers = async () => {
      try {
        setLoading(true);
        const response = await fetch('/api/v1/members');
        if (!response.ok) throw new Error('Failed to fetch members');
        const data = await response.json();
        setMembers(data.members);
        setError(null);
      } catch (err) {
        console.error('Error fetching members:', err);
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };

    fetchMembers();
  }, []);

  const getOnlineStatus = (sessionId) => {
    return onlineUsers.some(u => u.session_id === sessionId);
  };

  const onlineCount = onlineUsers.length;
  const totalCount = members.length;

  return (
    <div className="chat-home">
      <div className="home-header">
        <h1>Friend Hub</h1>
        <p className="home-subtitle">Group Chat</p>
      </div>

      <div className="members-container">
        <div className="members-header">
          <div className="members-title">
            <h2>Members</h2>
            <span className="member-count">
              {onlineCount} online · {totalCount} total
            </span>
          </div>
          <button className="enter-chat-btn" onClick={onEnterChat}>
            Enter Chat
          </button>
        </div>

        {loading && (
          <div className="members-loading">
            <div className="spinner"></div>
            <p>Loading members…</p>
          </div>
        )}

        {error && (
          <div className="members-error">
            <p>Error loading members: {error}</p>
            <button onClick={() => window.location.reload()}>
              Retry
            </button>
          </div>
        )}

        {!loading && !error && members.length === 0 && (
          <div className="members-empty">
            <p>No members yet</p>
          </div>
        )}

        {!loading && !error && members.length > 0 && (
          <div className="members-list">
            {members.map(member => {
              const isOnline = getOnlineStatus(member.session_id);
              return (
                <div key={member.session_id} className="member-card">
                  <div className="member-avatar-section">
                    <div className="avatar-container">
                      <UserAvatar
                        nickname={member.nickname}
                        sessionId={member.session_id}
                      />
                      <span className={`online-indicator ${isOnline ? 'online' : 'offline'}`} />
                    </div>
                  </div>

                  <div className="member-info">
                    <h3 className="member-nickname">{member.nickname}</h3>
                    <div className="member-status">
                      <span className={`status-badge ${isOnline ? 'online' : 'offline'}`}>
                        {isOnline ? '● Online' : '● Offline'}
                      </span>
                    </div>
                  </div>

                  <div className="member-stats">
                    <div className="stat">
                      <span className="stat-label">Messages</span>
                      <span className="stat-value">{member.message_count}</span>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div className="home-footer">
        <p>Welcome to Friend Hub! Click "Enter Chat" to start chatting.</p>
      </div>
    </div>
  );
};

export default ChatHome;
