import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  createDisplayRoleVote,
  fetchMemberByUsername,
  fetchMemberProfile,
  updateMemberProfile,
} from '../../services/api.js';
import { useAuth } from '../../auth/AuthProvider.jsx';
import UserAvatar from './UserAvatar.jsx';
import './PersonPopup.css';

const cache = new Map();

export function clearPersonCache(username) {
  if (username) cache.delete(username);
  else cache.clear();
}

const ROLE_COLORS = { owner: '#8a5600', admin: '#284ea6', member: '#415066' };
const ROLE_BG     = { owner: '#fff1d6', admin: '#e6f0ff', member: '#eef2f6' };

// Phase 1 permission rule mirrors backend can_edit_profile() with the default
// self_edit policy: admin/owner can edit anyone, members can edit themselves.
function canEditProfile(currentUser, member) {
  if (!currentUser || !member) return false;
  if (currentUser.role === 'owner' || currentUser.role === 'admin') return true;
  return currentUser.session_id === member.session_id;
}

export default function PersonPopup({ username, sessionId, onClose }) {
  const { user: currentUser } = useAuth();
  const cacheKey = useMemo(() => sessionId || username, [sessionId, username]);

  const [member, setMember]     = useState(cache.get(cacheKey) || null);
  const [isLoading, setLoading] = useState(!cache.has(cacheKey));
  const [error, setError]       = useState(null);
  const [isEditing, setEditing] = useState(false);
  const [isProposingRole, setProposingRole] = useState(false);
  const overlayRef              = useRef(null);

  useEffect(() => {
    if (cache.has(cacheKey)) return;
    setLoading(true);

    const loader = sessionId
      ? fetchMemberProfile(sessionId)
      : fetchMemberByUsername(username);

    loader
      .then(data => {
        if (data) { cache.set(cacheKey, data); setMember(data); }
        else setError('Member not found');
      })
      .catch(() => setError('Failed to load'))
      .finally(() => setLoading(false));
  }, [cacheKey, sessionId, username]);

  useEffect(() => {
    const handler = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  const handleOverlayClick = (e) => {
    if (e.target === overlayRef.current) onClose();
  };

  const handleViewProfile = () => {
    if (!member?.username) return;
    const route = `/profile/${member.username}`;
    window.history.pushState({}, '', route);
    window.dispatchEvent(new PopStateEvent('popstate'));
    onClose();
  };

  const handleSaved = (updated) => {
    cache.set(cacheKey, updated);
    if (updated.username) cache.set(updated.username, updated);
    setMember(updated);
    setEditing(false);
  };

  const editable = canEditProfile(currentUser, member);
  const canProposeRole = !!currentUser && !!member?.session_id;

  return (
    <div className="person-popup-overlay" ref={overlayRef} onClick={handleOverlayClick}>
      <div className="person-popup-card person-popup-sheet" role="dialog" aria-modal="true">
        <button className="person-popup-close" type="button" onClick={onClose} aria-label="Close">✕</button>

        {isLoading && <div className="person-popup-state">Loading…</div>}
        {error     && <div className="person-popup-state person-popup-state--error">{error}</div>}

        {member && !isEditing && !isProposingRole && (
          <>
            <div className="person-popup-header">
              <div className="person-popup-avatar-wrap">
                {member.avatar_emoji && !member.avatar_url ? (
                  <span className="person-popup-avatar-emoji" aria-hidden="true">
                    {member.avatar_emoji}
                  </span>
                ) : (
                  <UserAvatar nickname={member.nickname} size={56} avatarUrl={member.avatar_url} />
                )}
                <span className={`person-popup-online-dot ${member.is_online ? 'online' : ''}`} />
              </div>
              <div className="person-popup-identity">
                <h3 className="person-popup-name">{member.nickname}</h3>
                {member.username && <p className="person-popup-username">@{member.username}</p>}
                <div className="person-popup-badges">
                  <span
                    className="person-popup-role"
                    style={{ background: ROLE_BG[member.role] || ROLE_BG.member, color: ROLE_COLORS[member.role] || ROLE_COLORS.member }}
                  >
                    {member.role}
                  </span>
                  {member.display_role && (
                    <span className="person-popup-display-role">{member.display_role}</span>
                  )}
                </div>
              </div>
            </div>

            <div className={`person-popup-description${member.bio ? '' : ' empty'}`}>
              <span>Description</span>
              <p>{member.bio || 'No description yet.'}</p>
            </div>

            <div className="person-popup-actions">
              {canProposeRole && (
                <button
                  className="person-popup-secondary-btn"
                  type="button"
                  onClick={() => setProposingRole(true)}
                >
                  Propose chat role
                </button>
              )}
              {editable && (
                <button
                  className="person-popup-secondary-btn"
                  type="button"
                  onClick={() => setEditing(true)}
                >
                  Edit profile
                </button>
              )}
              {member.username && (
                <button className="person-popup-view-btn" type="button" onClick={handleViewProfile}>
                  Go to profile →
                </button>
              )}
            </div>
          </>
        )}

        {member && isProposingRole && !isEditing && (
          <RoleVoteForm
            member={member}
            onCancel={() => setProposingRole(false)}
            onCreated={() => {
              clearPersonCache(cacheKey);
              setProposingRole(false);
              onClose();
            }}
          />
        )}

        {member && isEditing && (
          <ProfileEditForm
            member={member}
            onCancel={() => setEditing(false)}
            onSaved={handleSaved}
          />
        )}
      </div>
    </div>
  );
}

function RoleVoteForm({ member, onCancel, onCreated }) {
  const [displayRole, setDisplayRole] = useState(member.display_role || '');
  const [reason, setReason]           = useState('');
  const [isSaving, setSaving]         = useState(false);
  const [submitError, setSubmitError] = useState(null);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSaving(true);
    setSubmitError(null);

    try {
      await createDisplayRoleVote({
        targetSessionId: member.session_id,
        proposedDisplayRole: displayRole.trim(),
        reason: reason.trim() || undefined,
      });
      onCreated();
    } catch (err) {
      setSubmitError(err.message || 'Could not create vote');
    } finally {
      setSaving(false);
    }
  };

  return (
    <form className="person-popup-form" onSubmit={handleSubmit}>
      <h3 className="person-popup-form-title">Propose chat role</h3>

      <label className="person-popup-field">
        <span>Chat role</span>
        <input
          type="text"
          value={displayRole}
          onChange={(e) => setDisplayRole(e.target.value)}
          placeholder="e.g. Vibes Officer"
          maxLength={64}
          required
        />
      </label>

      <label className="person-popup-field">
        <span>Reason</span>
        <textarea
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          rows={2}
          maxLength={500}
          placeholder="Optional"
        />
      </label>

      {submitError && <div className="person-popup-state person-popup-state--error">{submitError}</div>}

      <div className="person-popup-form-actions">
        <button type="button" className="person-popup-secondary-btn" onClick={onCancel} disabled={isSaving}>
          Cancel
        </button>
        <button type="submit" className="person-popup-view-btn" disabled={isSaving}>
          {isSaving ? 'Creating…' : 'Create vote'}
        </button>
      </div>
    </form>
  );
}

function ProfileEditForm({ member, onCancel, onSaved }) {
  const [nickname, setNickname]         = useState(member.nickname || '');
  const [displayRole, setDisplayRole]   = useState(member.display_role || '');
  const [bio, setBio]                   = useState(member.bio || '');
  const [avatarEmoji, setAvatarEmoji]   = useState(member.avatar_emoji || '');
  const [isSaving, setSaving]           = useState(false);
  const [submitError, setSubmitError]   = useState(null);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSaving(true);
    setSubmitError(null);

    const updates = {};
    if (nickname.trim() !== (member.nickname || '')) updates.nickname = nickname.trim();
    if (displayRole !== (member.display_role || '')) updates.display_role = displayRole.trim();
    if (bio !== (member.bio || '')) updates.bio = bio.trim();
    if (avatarEmoji !== (member.avatar_emoji || '')) updates.avatar_emoji = avatarEmoji.trim();

    if (Object.keys(updates).length === 0) {
      setSaving(false);
      onCancel();
      return;
    }

    try {
      const updated = await updateMemberProfile(member.session_id, updates);
      onSaved(updated);
    } catch (err) {
      setSubmitError(err.message || 'Could not save');
    } finally {
      setSaving(false);
    }
  };

  return (
    <form className="person-popup-form" onSubmit={handleSubmit}>
      <h3 className="person-popup-form-title">Edit profile</h3>

      <label className="person-popup-field">
        <span>Nickname</span>
        <input
          type="text"
          value={nickname}
          onChange={(e) => setNickname(e.target.value)}
          maxLength={64}
          required
        />
      </label>

      <label className="person-popup-field">
        <span>Chat role</span>
        <input
          type="text"
          value={displayRole}
          onChange={(e) => setDisplayRole(e.target.value)}
          placeholder="e.g. Vibes Officer"
          maxLength={64}
        />
      </label>

      <label className="person-popup-field">
        <span>Avatar emoji</span>
        <input
          type="text"
          value={avatarEmoji}
          onChange={(e) => setAvatarEmoji(e.target.value)}
          placeholder="🍻"
          maxLength={8}
        />
      </label>

      <label className="person-popup-field">
        <span>Description</span>
        <textarea
          value={bio}
          onChange={(e) => setBio(e.target.value)}
          rows={3}
          maxLength={500}
          placeholder="Starts most of the chaos…"
        />
      </label>

      {submitError && <div className="person-popup-state person-popup-state--error">{submitError}</div>}

      <div className="person-popup-form-actions">
        <button type="button" className="person-popup-secondary-btn" onClick={onCancel} disabled={isSaving}>
          Cancel
        </button>
        <button type="submit" className="person-popup-view-btn" disabled={isSaving}>
          {isSaving ? 'Saving…' : 'Save'}
        </button>
      </div>
    </form>
  );
}
