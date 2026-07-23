import React, { useEffect, useMemo, useState } from 'react';
import {
  linkImportedIdentity,
  listIdentityUsers,
  listImportedIdentities,
  unlinkImportedIdentity,
  updateImportedIdentity,
} from '../api/adminUsers.js';
import './FeaturePages.css';

function norm(value) {
  return (value || '').trim().toLowerCase().replace(/\s+/g, ' ');
}

function firstName(value) {
  return norm(value).split(' ')[0] || '';
}

function fmt(value) {
  return value ? new Date(value).toLocaleDateString() : 'Never';
}

function userLabel(user) {
  return user ? `${user.display_name || user.nickname || user.username} (@${user.username || 'no-username'})` : 'Unlinked';
}

export default function AdminIdentityPage() {
  const [identities, setIdentities] = useState([]);
  const [users, setUsers] = useState([]);
  const [filters, setFilters] = useState({ status: '', search: '' });
  const [links, setLinks] = useState({});
  const [notes, setNotes] = useState({});
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(true);

  const load = async () => {
    const [identityData, userData] = await Promise.all([
      listImportedIdentities({ ...filters, limit: 200 }),
      listIdentityUsers({ limit: 500 }),
    ]);
    const nextIdentities = identityData.imported_identities || [];
    const allUsers = userData.users || [];
    const filteredUsers = allUsers.filter(user => !user.is_test_user && user.user_type !== 'system' && user.user_type !== 'test');
    setIdentities(nextIdentities);
    setUsers(filteredUsers);
    setLinks(Object.fromEntries(nextIdentities.map(identity => [identity.id, identity.linked_user_id || ''])));
    setNotes(Object.fromEntries(nextIdentities.map(identity => [identity.id, identity.notes || ''])));
    if (allUsers.length === 0) {
      setError(`No users returned from server. The /admin/identity/users endpoint may be failing — check server logs.`);
    } else if (filteredUsers.length === 0) {
      setError(`${allUsers.length} users returned but all filtered out (user_type breakdown: ${[...new Set(allUsers.map(u => u.user_type || 'null'))].join(', ')}). Adjust filter logic if real members are being excluded.`);
    }
  };

  useEffect(() => {
    load().catch(err => setError(err.message)).finally(() => setIsLoading(false));
  }, []);

  const suggestionsByIdentity = useMemo(() => {
    return Object.fromEntries(identities.map(identity => {
      const exact = users.filter(user => {
        const identityName = identity.normalised_name || norm(identity.source_display_name);
        return [user.display_name, user.nickname, user.username].some(value => norm(value) === identityName);
      });
      const first = exact.length ? [] : users.filter(user => firstName(user.display_name || user.nickname) === firstName(identity.source_display_name));
      return [identity.id, [...exact, ...first].slice(0, 3)];
    }));
  }, [identities, users]);

  const act = async (fn) => {
    setError('');
    try {
      await fn();
      await load();
    } catch (err) {
      setError(err.message);
    }
  };

  const applyFilters = (event) => {
    event.preventDefault();
    setIsLoading(true);
    load().catch(err => setError(err.message)).finally(() => setIsLoading(false));
  };

  return (
    <div className="feature-page">
      <header className="feature-page-header">
        <h1>Member Identity Management</h1>
      </header>

      {error && <div className="form-error">{error}</div>}

      <form className="feature-panel feature-form" onSubmit={applyFilters}>
        <input
          value={filters.search}
          placeholder="Search imported names"
          onChange={event => setFilters(current => ({ ...current, search: event.target.value }))}
        />
        <select value={filters.status} onChange={event => setFilters(current => ({ ...current, status: event.target.value }))}>
          <option value="">all statuses</option>
          <option value="unlinked">unlinked</option>
          <option value="linked">linked</option>
          <option value="ignored">ignored</option>
          <option value="duplicate">duplicate</option>
          <option value="archived">archived</option>
        </select>
        <button type="submit">Filter</button>
      </form>

      <section className="feature-panel">
        <h2>Imported Messenger Identities</h2>
        {isLoading ? <p>Loading...</p> : (
          <div className="admin-users-list">
            {identities.map(identity => {
              const suggestions = suggestionsByIdentity[identity.id] || [];
              return (
                <article key={identity.id} className="admin-user-row">
                  <div>
                    <strong>{identity.source_display_name}</strong>
                    <span>{identity.source} · {identity.status} · {identity.message_count || 0} messages</span>
                    <span>Linked: {userLabel(users.find(user => user.id === identity.linked_user_id))}</span>
                    <span>Seen: {fmt(identity.first_seen_at)} to {fmt(identity.last_seen_at)}</span>
                    {suggestions.length > 0 && (
                      <span>Suggestions: {suggestions.map(user => user.display_name || user.nickname || user.username).join(', ')}</span>
                    )}
                    <textarea
                      value={notes[identity.id] || ''}
                      rows={2}
                      placeholder="Notes"
                      onChange={event => setNotes(current => ({ ...current, [identity.id]: event.target.value }))}
                    />
                  </div>
                  <div className="admin-user-actions admin-identity-actions">
                    <select value={links[identity.id] || ''} onChange={event => setLinks(current => ({ ...current, [identity.id]: event.target.value }))}>
                      <option value="">unlinked</option>
                      {users.map(user => (
                        <option key={user.id} value={user.id}>{userLabel(user)}</option>
                      ))}
                    </select>
                    <button
                      type="button"
                      onClick={() => act(() => links[identity.id]
                        ? linkImportedIdentity(identity.id, links[identity.id])
                        : unlinkImportedIdentity(identity.id))}
                    >
                      {links[identity.id] ? 'Link' : 'Unlink'}
                    </button>
                    {suggestions[0] && (
                      <button type="button" onClick={() => act(() => linkImportedIdentity(identity.id, suggestions[0].id))}>
                        Link suggested
                      </button>
                    )}
                    <button type="button" onClick={() => act(() => updateImportedIdentity(identity.id, { notes: notes[identity.id] || null }))}>
                      Save notes
                    </button>
                    <select value={identity.status} onChange={event => act(() => updateImportedIdentity(identity.id, { status: event.target.value }))}>
                      <option value="unlinked">unlinked</option>
                      <option value="linked">linked</option>
                      <option value="ignored">ignored</option>
                      <option value="duplicate">duplicate</option>
                      <option value="archived">archived</option>
                    </select>
                  </div>
                </article>
              );
            })}
            {identities.length === 0 && <p>No imported identities found.</p>}
          </div>
        )}
      </section>
    </div>
  );
}
