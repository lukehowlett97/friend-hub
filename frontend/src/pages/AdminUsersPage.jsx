import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  changeUserRole,
  createAdminUser,
  deactivateUser,
  linkImportedIdentity,
  listIdentityUsers,
  listAdminUsers,
  listImportedIdentities,
  reactivateUser,
  removeUserRoom,
  resetUserPin,
  unlinkImportedIdentity,
  updateIdentityUser,
  updateUserProfile,
  updateUserRoom,
} from '../api/adminUsers.js';
import InviteShareCard from '../components/Admin/InviteShareCard.jsx';
import './FeaturePages.css';

function fmt(value) {
  return value ? new Date(value).toLocaleString() : 'Never';
}

function canBePlatformOwner(username) {
  return (username || '').trim().toLowerCase() === 'techlett';
}

function RoleOptions({ username, currentRole }) {
  const showOwner = currentRole === 'owner' || canBePlatformOwner(username);
  return (
    <>
      <option value="member">member</option>
      <option value="admin">admin</option>
      {showOwner && <option value="owner">owner</option>}
    </>
  );
}

function RoomRoleOptions({ username, currentRole }) {
  const showOwner = currentRole === 'owner' || canBePlatformOwner(username);
  return (
    <>
      <option value="member">member</option>
      <option value="admin">admin</option>
      {showOwner && <option value="owner">owner</option>}
    </>
  );
}

function isFacebookImportedProfile(user) {
  const username = (user.username || '').toLowerCase();
  const type = (user.user_type || '').toLowerCase();
  const status = (user.status || '').toLowerCase();
  return username.startsWith('legacy_') || type === 'imported' || status === 'imported' || user.likely_test_user;
}

const STALL_WINDOW_MS = 3 * 24 * 60 * 60 * 1000; // invite within 3 days of expiry = "stalled"

// Derive an onboarding stage from existing account fields — no new backend data.
function onboardingStage(user) {
  if (!user.is_active && !user.invite_pending) return 'inactive';
  if (user.has_pin || user.last_login_at) return 'joined';
  if (user.invite_pending) {
    const expiresAt = user.invite_code_expires_at ? new Date(user.invite_code_expires_at).getTime() : null;
    if (expiresAt !== null && expiresAt - Date.now() < STALL_WINDOW_MS) return 'stalled';
    return 'invited';
  }
  return 'inactive';
}

const STAGE_LABELS = {
  invited: 'Invited',
  joined: 'Joined',
  stalled: 'Stalled',
  inactive: 'Inactive',
};

export default function AdminUsersPage() {
  const [users, setUsers] = useState([]);
  const [rooms, setRooms] = useState([]);
  const [identities, setIdentities] = useState([]);
  const [form, setForm] = useState({ display_name: '', username: '', role: 'member', room_ids: [] });
  const [messengerLinks, setMessengerLinks] = useState({});
  const [expandedMessengerLink, setExpandedMessengerLink] = useState(null);
  const [visibleInviteCodes, setVisibleInviteCodes] = useState({});
  const [expandedActions, setExpandedActions] = useState({});
  const [profileDrafts, setProfileDrafts] = useState({});
  const [roomFilter, setRoomFilter] = useState('all');
  const [stageFilter, setStageFilter] = useState('all');
  const [selectedUserIds, setSelectedUserIds] = useState(() => new Set());
  const [bulkRoomId, setBulkRoomId] = useState('');
  const [bulkRole, setBulkRole] = useState('member');
  const [bulkBusy, setBulkBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const listRef = useRef(null);

  const load = async () => {
    try {
      const data = await listAdminUsers();
      setUsers(data.users || []);
      setRooms(data.rooms || []);
    } catch {
      const data = await listIdentityUsers();
      setUsers(data.users || []);
      setRooms([]);
    }
    const identityData = await listImportedIdentities({ limit: 500 });
    const nextIdentities = identityData.imported_identities || [];
    setIdentities(nextIdentities);
    setMessengerLinks(() => {
      const next = {};
      nextIdentities.forEach(identity => {
        if (identity.linked_user_id) next[identity.linked_user_id] = identity.id;
      });
      return next;
    });
  };

  useEffect(() => {
    load().catch(err => setError(err.message)).finally(() => setIsLoading(false));
  }, []);

  const roomStats = useMemo(() => rooms.map(room => ({
    ...room,
    count: users.filter(user => (user.rooms || []).some(memberRoom => memberRoom.id === room.id)).length,
  })), [rooms, users]);

  const importedCount = useMemo(() => users.filter(isFacebookImportedProfile).length, [users]);
  const roomlessCount = useMemo(() => users.filter(user => !(user.rooms || []).length).length, [users]);

  const stageCounts = useMemo(() => {
    const counts = { invited: 0, joined: 0, stalled: 0, inactive: 0 };
    users.forEach(user => { counts[onboardingStage(user)] += 1; });
    return counts;
  }, [users]);

  const filteredUsers = useMemo(() => {
    let result = users;
    if (roomFilter === 'roomless') result = result.filter(user => !(user.rooms || []).length);
    else if (roomFilter === 'imported') result = result.filter(isFacebookImportedProfile);
    else if (roomFilter !== 'all') result = result.filter(user => (user.rooms || []).some(room => room.id === roomFilter));
    if (stageFilter !== 'all') result = result.filter(user => onboardingStage(user) === stageFilter);
    return result;
  }, [roomFilter, stageFilter, users]);

  // Default the bulk-assign target to the first room (typically the main shared room).
  useEffect(() => {
    if (!bulkRoomId && rooms.length) setBulkRoomId(rooms[0].id);
  }, [rooms, bulkRoomId]);

  const selectedCount = selectedUserIds.size;
  const allFilteredSelected = filteredUsers.length > 0 && filteredUsers.every(user => selectedUserIds.has(user.id));

  const toggleUserSelected = (userId) => {
    setSelectedUserIds(current => {
      const next = new Set(current);
      if (next.has(userId)) next.delete(userId); else next.add(userId);
      return next;
    });
  };

  const toggleSelectAllFiltered = () => {
    setSelectedUserIds(current => {
      const next = new Set(current);
      if (allFilteredSelected) filteredUsers.forEach(user => next.delete(user.id));
      else filteredUsers.forEach(user => next.add(user.id));
      return next;
    });
  };

  const clearSelection = () => setSelectedUserIds(new Set());

  const bulkAddToRoom = async () => {
    if (!bulkRoomId || !selectedCount) return;
    setBulkBusy(true);
    setError('');
    setNotice('');
    const ids = [...selectedUserIds];
    const results = await Promise.allSettled(ids.map(id => updateUserRoom(id, bulkRoomId, bulkRole)));
    const failed = results.filter(r => r.status === 'rejected').length;
    const roomName = rooms.find(room => room.id === bulkRoomId)?.name || 'room';
    if (failed) setError(`${failed} of ${ids.length} could not be added to ${roomName}.`);
    setNotice(`Added ${ids.length - failed} member${ids.length - failed === 1 ? '' : 's'} to ${roomName}.`);
    clearSelection();
    setBulkBusy(false);
    await load();
  };

  // "View room users": pick a room (default the active filter, else the first room),
  // apply it as the filter, and scroll the list into view.
  const viewRoomUsers = () => {
    const targetRoomId = (roomFilter !== 'all' && roomFilter !== 'roomless' && roomFilter !== 'imported')
      ? roomFilter
      : rooms[0]?.id;
    if (!targetRoomId) return;
    setRoomFilter(targetRoomId);
    setStageFilter('all');
    requestAnimationFrame(() => listRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }));
  };

  const submit = async (event) => {
    event.preventDefault();
    setError('');
    try {
      const data = await createAdminUser(form);
      if (data.user?.id && data.invite_code) {
        setVisibleInviteCodes(current => ({
          ...current,
          [data.user.id]: { code: data.invite_code, url: data.invite_url, displayName: data.user.display_name },
        }));
      }
      setForm({ display_name: '', username: '', role: 'member', room_ids: [] });
      setShowCreateForm(false);
      await load();
    } catch (err) {
      setError(err.message);
    }
  };

  const act = async (fn) => {
    setError('');
    try {
      const data = await fn();
      if (data.user?.id && data.invite_code) {
        setVisibleInviteCodes(current => ({
          ...current,
          [data.user.id]: { code: data.invite_code, url: data.invite_url, displayName: data.user.display_name },
        }));
      }
      await load();
      return true;
    } catch (err) {
      setError(err.message);
      return false;
    }
  };

  const identityLabel = (identity) => {
    const parts = [
      identity.source_display_name,
      `${identity.message_count || 0} messages`,
      identity.status,
    ];
    return parts.filter(Boolean).join(' · ');
  };

  const activeUserIds = new Set(users.filter(u => u.is_active).map(u => u.id));

  const identitiesForUser = (user) => {
    return identities.filter(identity =>
      !identity.linked_user_id ||
      identity.linked_user_id === user.id ||
      !activeUserIds.has(identity.linked_user_id)
    );
  };

  const currentMessengerIdentity = (user) => {
    return identities.find(identity => identity.linked_user_id === user.id) || null;
  };

  const linkMessenger = async (user) => {
    const identityId = messengerLinks[user.id];
    if (!identityId) {
      setError('Choose a Messenger profile to link');
      return;
    }
    if (await act(() => linkImportedIdentity(identityId, user.id))) {
      setExpandedMessengerLink(null);
    }
  };

  const toggleActions = (userId) => {
    setExpandedActions(current => ({ ...current, [userId]: !current[userId] }));
  };

  const userRoomIds = (user) => new Set((user.rooms || []).map(room => room.id));

  const draftForUser = (user) => profileDrafts[user.id] || { username: user.username || '' };

  const setUsernameDraft = (user, username) => {
    setProfileDrafts(current => ({
      ...current,
      [user.id]: {
        ...draftForUser(user),
        username: username.toLowerCase(),
      },
    }));
  };

  const saveUsername = async (user) => {
    const draft = draftForUser(user);
    if ((draft.username || '').trim().toLowerCase() === (user.username || '').toLowerCase()) return;
    if (await act(() => updateUserProfile(user.id, { username: draft.username }))) {
      setProfileDrafts(current => {
        const next = { ...current };
        delete next[user.id];
        return next;
      });
    }
  };

  const filterLabel = roomFilter === 'all'
    ? 'All users'
    : roomFilter === 'roomless'
      ? 'Users without rooms'
      : roomFilter === 'imported'
        ? 'Facebook imports'
        : rooms.find(room => room.id === roomFilter)?.name || 'Users';

  return (
    <div className="feature-page admin-users-page">
      <header className="feature-page-header admin-users-header">
        <div>
          <h1>Users</h1>
          <p>Review room membership first. Open actions only when you need to change an account.</p>
        </div>
        <strong>{users.length}</strong>
      </header>

      {error && <div className="form-error">{error}</div>}
      {notice && <div className="form-notice">{notice}</div>}

      <section className="feature-panel admin-users-primary">
        <div className="admin-user-filter-bar" aria-label="Filter users">
          <button type="button" className={roomFilter === 'all' ? 'is-selected' : ''} onClick={() => setRoomFilter('all')}>
            All <span>{users.length}</span>
          </button>
          {rooms.map(room => (
            <button key={room.id} type="button" className={roomFilter === room.id ? 'is-selected' : ''} onClick={() => setRoomFilter(room.id)}>
              {room.name} <span>{roomStats.find(item => item.id === room.id)?.count || 0}</span>
            </button>
          ))}
          <button type="button" className={roomFilter === 'roomless' ? 'is-selected' : ''} onClick={() => setRoomFilter('roomless')}>
            No rooms <span>{roomlessCount}</span>
          </button>
          <button type="button" className={roomFilter === 'imported' ? 'is-selected' : ''} onClick={() => setRoomFilter('imported')}>
            Facebook imports <span>{importedCount}</span>
          </button>
        </div>

        <div className="admin-user-filter-bar admin-user-stage-bar" aria-label="Filter by onboarding stage">
          <button type="button" className={stageFilter === 'all' ? 'is-selected' : ''} onClick={() => setStageFilter('all')}>
            Any stage
          </button>
          {['invited', 'stalled', 'joined', 'inactive'].map(stage => (
            <button
              key={stage}
              type="button"
              className={`stage-chip stage-${stage}${stageFilter === stage ? ' is-selected' : ''}`}
              onClick={() => setStageFilter(stage)}
            >
              {STAGE_LABELS[stage]} <span>{stageCounts[stage]}</span>
            </button>
          ))}
        </div>

        <div className="admin-user-action-row">
          <button
            type="button"
            className="admin-action-btn is-primary"
            onClick={() => setShowCreateForm(open => !open)}
            aria-expanded={showCreateForm}
          >
            {showCreateForm ? 'Close' : '+ Create user'}
          </button>
          <button
            type="button"
            className="admin-action-btn"
            onClick={viewRoomUsers}
            disabled={!rooms.length}
          >
            View room users
          </button>
        </div>

        {showCreateForm && (
          <form className="admin-create-user-form admin-create-user-inline" onSubmit={submit}>
            <label>
              Display name
              <input value={form.display_name} onChange={e => setForm(f => ({ ...f, display_name: e.target.value }))} autoFocus />
            </label>
            <label>
              Username
              <input
                value={form.username}
                onChange={e => {
                  const username = e.target.value.toLowerCase();
                  setForm(f => ({
                    ...f,
                    username,
                    role: f.role === 'owner' && !canBePlatformOwner(username) ? 'member' : f.role,
                  }));
                }}
              />
            </label>
            <label>
              Role
              <select value={form.role} onChange={e => setForm(f => ({ ...f, role: e.target.value }))}>
                <RoleOptions username={form.username} currentRole={form.role} />
              </select>
            </label>
            {rooms.length > 0 && (
              <fieldset className="admin-create-user-rooms">
                <legend>Add to rooms</legend>
                {rooms.map(room => {
                  const checked = form.room_ids.includes(room.id);
                  return (
                    <label key={room.id} className="admin-create-user-room-option">
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => setForm(f => ({
                          ...f,
                          room_ids: checked ? f.room_ids.filter(id => id !== room.id) : [...f.room_ids, room.id],
                        }))}
                      />
                      {room.name}
                    </label>
                  );
                })}
              </fieldset>
            )}
            <button type="submit" className="admin-action-btn is-primary">Create user</button>
          </form>
        )}

        <div className="admin-users-section-heading" ref={listRef}>
          <h2>{filterLabel}</h2>
          <div className="admin-users-section-tools">
            <span>{filteredUsers.length} shown · {roomlessCount} without rooms</span>
            {filteredUsers.length > 0 && (
              <label className="admin-select-all">
                <input type="checkbox" checked={allFilteredSelected} onChange={toggleSelectAllFiltered} />
                Select all shown
              </label>
            )}
          </div>
        </div>

        {selectedCount > 0 && (
          <div className="admin-bulk-bar" role="region" aria-label="Bulk actions">
            <strong>{selectedCount} selected</strong>
            <label>
              Add to
              <select value={bulkRoomId} onChange={e => setBulkRoomId(e.target.value)} disabled={bulkBusy}>
                {rooms.map(room => <option key={room.id} value={room.id}>{room.name}</option>)}
              </select>
            </label>
            <label>
              as
              <select value={bulkRole} onChange={e => setBulkRole(e.target.value)} disabled={bulkBusy}>
                <option value="member">member</option>
                <option value="admin">admin</option>
              </select>
            </label>
            <button type="button" className="admin-bulk-primary" onClick={bulkAddToRoom} disabled={bulkBusy || !bulkRoomId}>
              {bulkBusy ? 'Adding…' : 'Add to room'}
            </button>
            <button type="button" onClick={clearSelection} disabled={bulkBusy}>Clear</button>
          </div>
        )}

        {isLoading ? <p>Loading...</p> : (
          <div className="admin-users-list">
            {filteredUsers.map(user => {
              const messengerIdentity = currentMessengerIdentity(user);
              const roomIds = userRoomIds(user);
              const missingRooms = rooms.filter(room => !roomIds.has(room.id));
              const actionsOpen = Boolean(expandedActions[user.id]);
              const importedProfile = isFacebookImportedProfile(user);
              const draft = draftForUser(user);
              const stage = onboardingStage(user);
              const selected = selectedUserIds.has(user.id);

              return (
                <article key={user.id} className={`admin-user-row${!user.is_active ? ' is-inactive' : ''}${selected ? ' is-selected' : ''}`}>
                  <label className="admin-user-select" aria-label={`Select ${user.display_name}`}>
                    <input type="checkbox" checked={selected} onChange={() => toggleUserSelected(user.id)} />
                  </label>
                  <div className="admin-user-main">
                    <div className="admin-user-title-row">
                      <div>
                        <strong>{user.display_name}</strong>
                        <span>@{user.username}</span>
                      </div>
                      <span className={`admin-user-stage-badge stage-${stage}`}>{STAGE_LABELS[stage]}</span>
                    </div>

                    {importedProfile && (
                      <span className="admin-user-imported-badge">Facebook imported profile</span>
                    )}

                    <div className="admin-user-room-chips" aria-label={`Rooms for ${user.display_name}`}>
                      {(user.rooms || []).length ? user.rooms.map(room => (
                        <span key={room.id} className={`admin-user-room-chip role-${room.role}`}>
                          {room.name} <em>{room.role}</em>
                        </span>
                      )) : (
                        <span className="admin-user-room-chip is-empty">No rooms</span>
                      )}
                    </div>

                    <div className="admin-user-meta">
                      <span>{user.role} platform role</span>
                      <span>{user.has_pin ? 'has PIN' : 'no PIN'}</span>
                      <span>{user.invite_pending ? 'invite pending' : 'no invite'}</span>
                      <span>{messengerIdentity ? `Messenger: ${messengerIdentity.source_display_name}` : 'Messenger: unlinked'}</span>
                      {importedProfile && <span>Imported username pattern detected</span>}
                      <span>Last login: {fmt(user.last_login_at)}</span>
                    </div>

                    {visibleInviteCodes[user.id] && (
                      <InviteShareCard
                        inviteUrl={visibleInviteCodes[user.id].url}
                        inviteCode={visibleInviteCodes[user.id].code}
                        displayName={visibleInviteCodes[user.id].displayName}
                      />
                    )}
                  </div>

                  <button
                    type="button"
                    className="admin-user-actions-toggle"
                    onClick={() => toggleActions(user.id)}
                    aria-expanded={actionsOpen}
                    aria-controls={`admin-user-actions-${user.id}`}
                  >
                    {actionsOpen ? 'Hide actions' : 'Actions'}
                  </button>

                  {actionsOpen && (
                    <div id={`admin-user-actions-${user.id}`} className="admin-user-actions-panel">
                      <section>
                        <h3 className="admin-section-label">Rooms</h3>
                        <div className="admin-user-room-editor">
                          {(user.rooms || []).map(room => (
                            <div key={room.id} className="admin-user-room-editor-row">
                              <span>{room.name}</span>
                              <select
                                value={room.role}
                                onChange={e => act(() => updateUserRoom(user.id, room.id, e.target.value))}
                              >
                                <RoomRoleOptions username={user.username} currentRole={room.role} />
                              </select>
                              <button type="button" onClick={() => act(() => removeUserRoom(user.id, room.id))}>Remove</button>
                            </div>
                          ))}
                          {missingRooms.map(room => (
                            <button
                              key={room.id}
                              type="button"
                              className="admin-user-add-room-btn"
                              onClick={() => act(() => updateUserRoom(user.id, room.id, 'member'))}
                            >
                              Add to {room.name}
                            </button>
                          ))}
                        </div>
                      </section>

                      <section>
                        <h3 className="admin-section-label">Account</h3>
                        <div className="admin-user-profile-editor">
                          <label>
                            Username
                            <input
                              value={draft.username}
                              onChange={e => setUsernameDraft(user, e.target.value)}
                              onBlur={() => saveUsername(user)}
                            />
                          </label>
                          <button type="button" onClick={() => saveUsername(user)}>Save username</button>
                        </div>
                        <div className="admin-user-actions">
                          <select value={user.role} onChange={e => act(() => changeUserRole(user.id, e.target.value))}>
                            <RoleOptions username={user.username} currentRole={user.role} />
                          </select>
                          <button type="button" onClick={() => act(() => resetUserPin(user.id))}>Reset PIN</button>
                          {user.is_active ? (
                            <button type="button" onClick={() => act(() => deactivateUser(user.id))}>Deactivate</button>
                          ) : (
                            <button type="button" onClick={() => act(() => reactivateUser(user.id))}>Reactivate</button>
                          )}
                          {!user.is_test_user && (
                            <button type="button" onClick={() => act(() => updateIdentityUser(user.id, { is_test_user: true, user_type: 'test', hidden_from_member_list: true }))}>Mark test</button>
                          )}
                          {!user.hidden_from_member_list ? (
                            <button type="button" onClick={() => act(() => updateIdentityUser(user.id, { hidden_from_member_list: true }))}>Hide</button>
                          ) : (
                            <button type="button" onClick={() => act(() => updateIdentityUser(user.id, { hidden_from_member_list: false }))}>Show</button>
                          )}
                        </div>
                        <p className="admin-user-details">
                          type: {user.user_type || 'human'} · status: {user.status || (user.is_active ? 'active' : 'deactivated')} · test: {user.is_test_user ? 'yes' : 'no'} · hidden: {user.hidden_from_member_list ? 'yes' : 'no'} · bot: {user.is_bot ? 'yes' : 'no'} · {user.locked_until ? 'locked' : 'unlocked'}
                        </p>
                      </section>

                      <section>
                        <h3 className="admin-section-label">Messenger</h3>
                        <div className="admin-user-actions">
                          <button type="button" onClick={() => setExpandedMessengerLink(current => current === user.id ? null : user.id)}>
                            {messengerIdentity ? 'Change Messenger link' : 'Link Messenger'}
                          </button>
                          {messengerIdentity && (
                            <button type="button" onClick={() => act(() => unlinkImportedIdentity(messengerIdentity.id))}>
                              Unlink Messenger
                            </button>
                          )}
                        </div>
                        {expandedMessengerLink === user.id && (
                          <div className="admin-messenger-link-row">
                            <select
                              value={messengerLinks[user.id] || ''}
                              onChange={e => setMessengerLinks(current => ({ ...current, [user.id]: e.target.value }))}
                            >
                              <option value="">Choose Messenger profile</option>
                              {identitiesForUser(user).map(identity => (
                                <option key={identity.id} value={identity.id}>{identityLabel(identity)}</option>
                              ))}
                            </select>
                            <button type="button" onClick={() => linkMessenger(user)}>Save link</button>
                          </div>
                        )}
                      </section>
                    </div>
                  )}
                </article>
              );
            })}
          </div>
        )}
      </section>

    </div>
  );
}
