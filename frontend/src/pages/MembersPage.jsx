import React, { useEffect, useMemo, useState, useCallback } from 'react';
import UserAvatar from '../components/Chat/UserAvatar';
import PersonPopup from '../components/Chat/PersonPopup.jsx';
import { fetchMembers, updateMemberRole } from '../services/api';
import { useAuth } from '../auth/AuthProvider.jsx';
import { canManageMembers, rolesAssignableBy } from '../utils/permissions.js';
import './MembersPage.css';

const ROLE_RANK = { owner: 0, admin: 1, member: 2 };

const SORT_OPTIONS = [
  { key: 'role', label: 'Permission' },
  { key: 'name', label: 'Name' },
  { key: 'messages', label: 'Messages' },
];

const MembersPage = ({ onNavigate }) => {
  const { user: currentUser } = useAuth();
  const [members, setMembers]     = useState([]);
  const [unlinkedImportedMembers, setUnlinkedImportedMembers] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError]         = useState(null);
  const [roleError, setRoleError] = useState(null);
  const [updatingId, setUpdatingId] = useState(null);
  const [activeMemberSession, setActiveMemberSession] = useState(null);
  const [sort, setSort] = useState({ key: 'role', direction: 'asc' });

  const canManage = canManageMembers(currentUser?.role);

  const load = useCallback(() => {
    setIsLoading(true);
    fetchMembers({ includeBots: true })
      .then(data => {
        setMembers(data.members || []);
        setUnlinkedImportedMembers(data.unlinked_imported_members || []);
        setError(null);
      })
      .catch(err => setError(err.message))
      .finally(() => setIsLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleRoleChange = async (member, newRole) => {
    if (newRole === member.role) return;
    setUpdatingId(member.session_id);
    setRoleError(null);
    try {
      await updateMemberRole(member.session_id, newRole);
      await load();
    } catch (err) {
      setRoleError(err.message || 'Could not update permission');
    } finally {
      setUpdatingId(null);
    }
  };

  const onlineCount = members.filter(m => m.is_online).length;
  const totalMessages = members.reduce((sum, member) => sum + (member.message_count || 0), 0);

  const sortedMembers = useMemo(() => {
    const direction = sort.direction === 'asc' ? 1 : -1;
    return [...members].sort((a, b) => {
      if (sort.key === 'messages') {
        const countDiff = (a.message_count || 0) - (b.message_count || 0);
        if (countDiff !== 0) return countDiff * direction;
      } else if (sort.key === 'role') {
        const roleDiff = (ROLE_RANK[a.role] ?? 99) - (ROLE_RANK[b.role] ?? 99);
        if (roleDiff !== 0) return roleDiff * direction;
      } else {
        const nameDiff = (a.nickname || '').localeCompare(b.nickname || '', undefined, { sensitivity: 'base' });
        if (nameDiff !== 0) return nameDiff * direction;
      }

      return (a.nickname || '').localeCompare(b.nickname || '', undefined, { sensitivity: 'base' });
    });
  }, [members, sort]);

  const setSortKey = (key) => {
    setSort((current) => {
      if (current.key === key) {
        return { key, direction: current.direction === 'asc' ? 'desc' : 'asc' };
      }
      return { key, direction: key === 'messages' ? 'desc' : 'asc' };
    });
  };

  const handleMemberClick = (member) => {
    if (member.username && onNavigate) {
      onNavigate(`/profile/${member.username}`);
      return;
    }
    if (member.session_id) {
      setActiveMemberSession(member.session_id);
    }
  };

  return (
    <section className="page">
      <header className="page-header members-page-header">
        <div>
          <h1>Members</h1>
          <p className="page-subtitle">{onlineCount} online · {members.length} total</p>
        </div>
      </header>

      <section className="members-overview" aria-label="Member summary">
        <div>
          <span>Online</span>
          <strong>{onlineCount}</strong>
        </div>
        <div>
          <span>Members</span>
          <strong>{members.length}</strong>
        </div>
        <div>
          <span>Messages</span>
          <strong>{totalMessages.toLocaleString()}</strong>
        </div>
      </section>

      <div className="members-toolbar">
        <span>Sort by</span>
        <div className="members-sort-controls" role="group" aria-label="Sort members">
          {SORT_OPTIONS.map((option) => (
            <button
              key={option.key}
              type="button"
              className={sort.key === option.key ? 'active' : ''}
              onClick={() => setSortKey(option.key)}
              aria-pressed={sort.key === option.key}
            >
              {option.label}
              {sort.key === option.key && <em>{sort.direction === 'asc' ? '↑' : '↓'}</em>}
            </button>
          ))}
        </div>
      </div>

      {roleError && (
        <div className="members-role-error">{roleError}</div>
      )}

      {isLoading && <div className="placeholder-panel">Loading members...</div>}
      {error && <div className="placeholder-panel">Error loading members: {error}</div>}

      {!isLoading && !error && (
        <>
          <div className="members-list-page">
            {sortedMembers.map((member) => {
              const assignable = canManage
                ? rolesAssignableBy(currentUser.role, member.role)
                : [];
              const isMe = member.session_id === currentUser?.session_id;
              const showSelect = assignable.length > 0 && !isMe;
              const importedLabel = member.is_imported ? 'Imported' : null;
              const botLabel = member.is_bot ? 'Bot' : null;
              const roleLabel = member.display_role || (botLabel ? 'Bot' : importedLabel || 'Citizen');
              const permissionLabel = member.role || 'member';

              return (
                <article key={member.id || member.session_id} className="member-row">
                  <button
                    type="button"
                    className="member-person"
                    onClick={() => handleMemberClick(member)}
                    disabled={!member.session_id}
                    aria-label={member.username ? `View ${member.nickname}'s profile` : `View imported member ${member.nickname}`}
                  >
                    <div className="member-avatar-wrap">
                      <UserAvatar
                        nickname={member.nickname}
                        size={44}
                        avatarUrl={member.avatar_url}
                        avatarEmoji={member.avatar_emoji || (member.is_bot ? '🤖' : null)}
                      />
                      <span className={`member-presence ${member.is_online ? 'online' : 'offline'}`} />
                    </div>
                    <div>
                      <h2>
                        {member.nickname}
                        {isMe && <span className="member-you"> (you)</span>}
                      </h2>
                      <div className="member-detail-line">
                        <span>{member.username ? `@${member.username}` : importedLabel || botLabel || 'No username'}</span>
                        <span>{(member.message_count || 0).toLocaleString()} messages</span>
                        <span>{(member.imported_message_count || 0).toLocaleString()} imported</span>
                        <span>{roleLabel}</span>
                        <span className="member-permission-label">{permissionLabel} permissions</span>
                      </div>
                    </div>
                  </button>

                  <div className="member-row-meta">
                    {showSelect ? (
                      <select
                        className={`role-select role-${member.role}`}
                        value={member.role}
                        disabled={updatingId === member.session_id}
                        onChange={e => handleRoleChange(member, e.target.value)}
                      >
                        {assignable.map(r => (
                          <option key={r} value={r}>{r}</option>
                        ))}
                      </select>
                    ) : (
                      <span className={`role-pill role-${member.role}`}>{permissionLabel}</span>
                    )}
                  </div>
                </article>
              );
            })}

            {members.length === 0 && <div className="placeholder-panel">No members yet</div>}
          </div>

          {unlinkedImportedMembers.length > 0 && (
            <details className="unlinked-imported-members">
              <summary>
                <span>Unlinked imported members</span>
                <strong>{unlinkedImportedMembers.length}</strong>
              </summary>
              <div className="unlinked-imported-table-wrap">
                <table className="unlinked-imported-table">
                  <thead>
                    <tr>
                      <th>Name</th>
                      <th>Messages</th>
                      <th>Status</th>
                      <th>Last seen</th>
                    </tr>
                  </thead>
                  <tbody>
                    {unlinkedImportedMembers.map((member) => (
                      <tr key={member.id}>
                        <td>
                          <strong>{member.nickname}</strong>
                          {member.normalised_name && (
                            <span>{member.normalised_name}</span>
                          )}
                        </td>
                        <td>{(member.message_count || 0).toLocaleString()}</td>
                        <td>{member.linked_username?.startsWith('legacy_') ? 'legacy placeholder' : (member.status || 'unlinked')}</td>
                        <td>{member.last_seen_at ? new Date(member.last_seen_at).toLocaleDateString() : 'Unknown'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          )}
        </>
      )}

      {activeMemberSession && (
        <PersonPopup
          sessionId={activeMemberSession}
          onClose={() => setActiveMemberSession(null)}
        />
      )}
    </section>
  );
};

export default MembersPage;
