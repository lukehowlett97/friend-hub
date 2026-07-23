import React, { useEffect, useRef, useState } from 'react';
import {
  deleteAvatar,
  fetchMemberActivity,
  fetchMemberByUsername,
  fetchMemberMessages,
  fetchMemberPhotos,
  fetchMemberProfileSummary,
  fetchStats,
  updateMemberProfile,
  uploadAvatar,
} from '../services/api.js';
import { useAuth } from '../auth/AuthProvider.jsx';
import UserAvatar from '../components/Chat/UserAvatar.jsx';
import PhotoModal from '../components/Photos/PhotoModal.jsx';
import { buildChatMessageHref } from '../utils/chatLinks.js';
import './ProfilePage.css';

const ROLE_COLORS = { owner: '#8a5600', admin: '#284ea6', member: '#415066' };
const ROLE_BG = { owner: '#fff1d6', admin: '#e6f0ff', member: '#eef2f6' };

const ACTION_ICONS = {
  created: '✨',
  updated: '✏️',
  deleted: '🗑️',
  voted: '🗳️',
  rsvped: '📅',
  completed: '✅',
  commented: '💬',
  reacted: '❤️',
};

function getActivityUrl(item) {
  const { target_type, target_id } = item;
  if (target_type === 'event' && target_id) return `/events/${target_id}`;
  if (target_type === 'poll') return '/polls';
  if (target_type === 'hub_item') return '/items';
  if (target_type === 'idea') return '/ideas';
  if (target_type === 'reminder') return '/reminders';
  if (target_type === 'message') return target_id ? buildChatMessageHref(target_id) : '/chat';
  if (target_type === 'event_post') return '/events';
  return null;
}

function fmtDate(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' });
}

function fmtRelative(iso) {
  if (!iso) return '—';
  const diff = (Date.now() - new Date(iso)) / 1000;
  if (diff < 120) return 'Just now';
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return fmtDate(iso);
}

function numberLabel(value) {
  return (value || 0).toLocaleString();
}

function handleCardKeyDown(event, action) {
  if (event.key !== 'Enter' && event.key !== ' ') return;
  event.preventDefault();
  action();
}

function clampPercent(value) {
  return Math.max(0, Math.min(100, value));
}

function CollapsibleSection({ title, count, isOpen, onToggle, children }) {
  return (
    <section className="profile-section">
      <button type="button" className="profile-section-header" onClick={onToggle} aria-expanded={isOpen}>
        <span className="profile-section-title">{title}</span>
        <span className="profile-section-meta">
          {typeof count === 'number' && <span>{numberLabel(count)}</span>}
          <span className="profile-section-chevron" aria-hidden="true">{isOpen ? '⌃' : '⌄'}</span>
        </span>
      </button>
      {isOpen && <div className="profile-section-body">{children}</div>}
    </section>
  );
}

function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error('Failed to read file'));
    reader.readAsDataURL(file);
  });
}

function createCroppedAvatarDataUrl(source, zoom, cropX, cropY) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => {
      const canvas = document.createElement('canvas');
      const size = 512;
      const cropSize = Math.min(image.naturalWidth, image.naturalHeight) / zoom;
      const sx = (image.naturalWidth - cropSize) * (cropX / 100);
      const sy = (image.naturalHeight - cropSize) * (cropY / 100);
      canvas.width = size;
      canvas.height = size;
      const ctx = canvas.getContext('2d');
      ctx.drawImage(image, sx, sy, cropSize, cropSize, 0, 0, size, size);
      resolve(canvas.toDataURL('image/jpeg', 0.9));
    };
    image.onerror = () => reject(new Error('Failed to prepare image'));
    image.src = source;
  });
}

export default function ProfilePage({ username: usernameProp, onNavigate }) {
  const { user: currentUser, logout, updateUser } = useAuth();

  const targetUsername = usernameProp || currentUser?.username;
  const isOwnProfile = !usernameProp || usernameProp === currentUser?.username;

  const [member, setMember] = useState(null);
  const [summary, setSummary] = useState(null);
  const [stats, setStats] = useState(null);
  const [photos, setPhotos] = useState([]);
  const [activity, setActivity] = useState([]);
  const [messageHistory, setMessageHistory] = useState([]);
  const [isLoading, setLoading] = useState(true);
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);
  const [historyError, setHistoryError] = useState(null);
  const [error, setError] = useState(null);
  const [editForm, setEditForm] = useState({ nickname: '', display_role: '', bio: '', avatar_emoji: '' });
  const [isEditing, setIsEditing] = useState(false);
  const [editError, setEditError] = useState(null);
  const [saving, setSaving] = useState(false);
  const [avatarUploading, setAvatarUploading] = useState(false);
  const [avatarError, setAvatarError] = useState(null);
  const [avatarModalOpen, setAvatarModalOpen] = useState(false);
  const [cropSource, setCropSource] = useState(null);
  const [cropZoom, setCropZoom] = useState(1);
  const [cropX, setCropX] = useState(50);
  const [cropY, setCropY] = useState(50);
  const [cropDragActive, setCropDragActive] = useState(false);
  const [photosOpen, setPhotosOpen] = useState(true);
  const [openPhoto, setOpenPhoto] = useState(null);
  const [activityOpen, setActivityOpen] = useState(false);
  const [messagesOpen, setMessagesOpen] = useState(false);
  const fileInputRef = useRef(null);
  const cropCanvasRef = useRef(null);
  const cropImageRef = useRef(null);
  const cropDragRef = useRef(null);

  useEffect(() => {
    if (!targetUsername) return;
    setLoading(true);
    setError(null);
    Promise.all([
      fetchMemberByUsername(targetUsername),
      fetchMemberProfileSummary(targetUsername),
      fetchMemberPhotos(targetUsername),
      isOwnProfile ? fetchStats() : Promise.resolve(null),
      fetchMemberActivity(targetUsername),
    ])
      .then(([m, s, p, st, a]) => {
        if (!m) {
          setError('Member not found');
          return;
        }
        setMember(m);
        setSummary(s);
        setPhotos(p || []);
        setStats(st);
        setActivity(a || []);
        setEditForm({
          nickname: m.nickname || '',
          display_role: m.display_role || '',
          bio: m.bio || '',
          avatar_emoji: m.avatar_emoji || '',
        });
      })
      .catch(() => setError('Failed to load profile'))
      .finally(() => setLoading(false));
  }, [targetUsername, isOwnProfile]);

  useEffect(() => {
    if (!targetUsername) return;
    setIsLoadingHistory(true);
    setHistoryError(null);
    Promise.all([
      fetchMemberMessages(targetUsername, 20, 0, 'current'),
      fetchMemberMessages(targetUsername, 20, 0, 'imported'),
    ])
      .then(([currentMessages, importedMessages]) => {
        const seen = new Set();
        const messages = [...(currentMessages || []), ...(importedMessages || [])]
          .filter((message) => {
            if (seen.has(message.id)) return false;
            seen.add(message.id);
            return true;
          })
          .sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0));
        setMessageHistory(messages);
      })
      .catch(() => setHistoryError('Failed to load message history'))
      .finally(() => setIsLoadingHistory(false));
  }, [targetUsername]);

  const openSettings = () => {
    setEditForm({
      nickname: member.nickname || '',
      display_role: member.display_role || '',
      bio: member.bio || '',
      avatar_emoji: member.avatar_emoji || '',
    });
    setIsEditing(true);
    setEditError(null);
  };

  const handleSaveProfile = async (e) => {
    e.preventDefault();
    setSaving(true);
    setEditError(null);
    try {
      const updated = await updateMemberProfile(member.session_id, {
        nickname: editForm.nickname.trim(),
        display_role: editForm.display_role.trim(),
        bio: editForm.bio.trim(),
        avatar_emoji: editForm.avatar_emoji.trim(),
      });
      setMember((prev) => ({ ...prev, ...updated }));
      if (isOwnProfile && updateUser) {
        updateUser({ ...currentUser, nickname: updated.nickname, avatar_url: updated.avatar_url });
      }
      setIsEditing(false);
    } catch (err) {
      setEditError(err.message);
    } finally {
      setSaving(false);
    }
  };

  const handleAvatarFile = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    setAvatarError(null);
    try {
      const dataUrl = await readFileAsDataUrl(file);
      setCropSource(dataUrl);
      setCropZoom(1);
      setCropX(50);
      setCropY(50);
      cropDragRef.current = null;
      setCropDragActive(false);
      setAvatarModalOpen(false);
    } catch (err) {
      setAvatarError(err.message);
    }
  };

  const handleUploadCroppedAvatar = async () => {
    if (!cropSource) return;
    setAvatarUploading(true);
    setAvatarError(null);
    try {
      const dataUrl = await createCroppedAvatarDataUrl(cropSource, cropZoom, cropX, cropY);
      const { avatar_url } = await uploadAvatar(dataUrl);
      const cacheSafeAvatar = `${avatar_url}?v=${Date.now()}`;
      setMember((prev) => ({ ...prev, avatar_url: cacheSafeAvatar }));
      if (isOwnProfile && updateUser) {
        updateUser({ ...currentUser, avatar_url: cacheSafeAvatar });
      }
      if (isOwnProfile && targetUsername) {
        const mod = await import('../components/Chat/PersonPopup.jsx');
        mod.clearPersonCache?.(targetUsername);
      }
      setCropSource(null);
      cropDragRef.current = null;
      setCropDragActive(false);
    } catch (err) {
      setAvatarError(err.message);
    } finally {
      setAvatarUploading(false);
    }
  };

  const handleRemoveAvatar = async () => {
    setAvatarUploading(true);
    setAvatarError(null);
    try {
      await deleteAvatar();
      setMember((prev) => ({ ...prev, avatar_url: null }));
      if (isOwnProfile && updateUser) {
        updateUser({ ...currentUser, avatar_url: null });
      }
      setAvatarModalOpen(false);
    } catch (err) {
      setAvatarError(err.message);
    } finally {
      setAvatarUploading(false);
    }
  };

  const handleLogout = async () => {
    await logout();
  };

  useEffect(() => {
    if (!cropSource) {
      cropImageRef.current = null;
      return undefined;
    }
    const image = new Image();
    image.onload = () => {
      cropImageRef.current = image;
      drawCropPreview();
    };
    image.src = cropSource;
    return () => {
      cropImageRef.current = null;
    };
  }, [cropSource]);

  const drawCropPreview = () => {
    const canvas = cropCanvasRef.current;
    const image = cropImageRef.current;
    if (!canvas || !image) return;
    const size = 512;
    const cropSize = Math.min(image.naturalWidth, image.naturalHeight) / cropZoom;
    const sx = (image.naturalWidth - cropSize) * (cropX / 100);
    const sy = (image.naturalHeight - cropSize) * (cropY / 100);
    canvas.width = size;
    canvas.height = size;
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, size, size);
    ctx.drawImage(image, sx, sy, cropSize, cropSize, 0, 0, size, size);
  };

  useEffect(() => {
    drawCropPreview();
  }, [cropZoom, cropX, cropY]);

  const startCropDrag = (e) => {
    e.preventDefault();
    e.currentTarget.setPointerCapture?.(e.pointerId);
    cropDragRef.current = {
      pointerId: e.pointerId,
      startClientX: e.clientX,
      startClientY: e.clientY,
      startCropX: cropX,
      startCropY: cropY,
      frameWidth: e.currentTarget.getBoundingClientRect().width || 1,
    };
    setCropDragActive(true);
  };

  const moveCropDrag = (e) => {
    const drag = cropDragRef.current;
    if (!drag || drag.pointerId !== e.pointerId) return;
    e.preventDefault();
    const sensitivity = 100 / drag.frameWidth / Math.max(1, cropZoom);
    const deltaX = (e.clientX - drag.startClientX) * sensitivity;
    const deltaY = (e.clientY - drag.startClientY) * sensitivity;
    setCropX(clampPercent(drag.startCropX - deltaX));
    setCropY(clampPercent(drag.startCropY - deltaY));
  };

  const stopCropDrag = () => {
    cropDragRef.current = null;
    setCropDragActive(false);
  };

  if (!targetUsername) return null;

  if (isLoading) {
    return (
      <section className="page profile-page">
        <div className="placeholder-panel">Loading profile…</div>
      </section>
    );
  }

  if (error) {
    return (
      <section className="page profile-page">
        <div className="placeholder-panel">{error}</div>
      </section>
    );
  }

  if (!member) return null;

  const pollVotes = stats?.poll_participation?.find((p) => p.nickname === member.nickname)?.votes ?? null;
  const currentMessageCount = summary?.current_message_count ?? member.message_count ?? 0;
  const importedMessageCount = summary?.imported_message_count ?? 0;
  const totalMessageCount = summary?.total_message_count ?? (currentMessageCount + importedMessageCount);
  const linkedIdentities = summary?.linked_imported_identities || [];

  return (
    <section className="page profile-page">
      <div className="profile-hero">
        <button
          type="button"
          className="profile-avatar-wrap"
          onClick={() => setAvatarModalOpen(true)}
          aria-label="Open profile picture"
        >
          <UserAvatar
            nickname={member.nickname}
            size={112}
            avatarUrl={member.avatar_url}
            avatarEmoji={member.avatar_emoji || (member.is_bot ? '🤖' : null)}
          />
          <span className={`profile-online-dot ${member.is_online ? 'online' : ''}`} />
        </button>

        <div className="profile-hero-body">
          <div className="profile-name-row">
            <h1 className="profile-nickname">{member.nickname}</h1>
            {isOwnProfile && (
              <button className="profile-edit-btn" type="button" onClick={openSettings}>
                Edit
              </button>
            )}
          </div>

          {member.username && <p className="profile-username">@{member.username}</p>}

          <div className="profile-badges">
            <span
              className="profile-role-badge"
              style={{ background: ROLE_BG[member.role] || ROLE_BG.member, color: ROLE_COLORS[member.role] || ROLE_COLORS.member }}
            >
              {member.is_bot ? 'bot' : member.role}
            </span>
            {member.display_role && <span className="profile-display-role">{member.display_role}</span>}
          </div>

          {member.bio && <p className="profile-bio">{member.bio}</p>}
          {linkedIdentities.length > 0 && (
            <div className="profile-linked-identities">
              {linkedIdentities.map((identity) => (
                <span key={identity.id}>
                  {identity.source_display_name} · {numberLabel(identity.message_count)}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>

      {isOwnProfile && isEditing && (
        <form className="profile-settings" onSubmit={handleSaveProfile}>
          <div className="profile-settings-head">
            <h2>Profile settings</h2>
            <button type="button" onClick={() => setIsEditing(false)}>Close</button>
          </div>
          <label>
            Nickname
            <input
              value={editForm.nickname}
              onChange={(e) => setEditForm((prev) => ({ ...prev, nickname: e.target.value }))}
              maxLength={64}
            />
          </label>
          <label>
            Chat role
            <input
              value={editForm.display_role}
              onChange={(e) => setEditForm((prev) => ({ ...prev, display_role: e.target.value }))}
              maxLength={64}
              placeholder="Vibes Officer, Friendly Assistant"
            />
          </label>
          <label>
            Avatar emoji
            <input
              value={editForm.avatar_emoji}
              onChange={(e) => setEditForm((prev) => ({ ...prev, avatar_emoji: e.target.value }))}
              maxLength={8}
              placeholder="🙂"
            />
          </label>
          <label>
            Bio
            <textarea
              value={editForm.bio}
              onChange={(e) => setEditForm((prev) => ({ ...prev, bio: e.target.value }))}
              maxLength={500}
              rows={4}
            />
          </label>
          {editError && <p className="profile-edit-error">{editError}</p>}
          <div className="profile-edit-actions">
            <button type="submit" className="profile-save-btn" disabled={saving}>
              {saving ? 'Saving…' : 'Save settings'}
            </button>
            <button type="button" className="profile-cancel-btn" onClick={() => setIsEditing(false)}>
              Cancel
            </button>
          </div>
        </form>
      )}

      <div className="profile-stats-grid">
        <div className="profile-stat-card profile-stat-card--wide">
          <span className="profile-stat-value">{numberLabel(totalMessageCount)}</span>
          <span className="profile-stat-label">Messages sent</span>
          <span className="profile-stat-breakdown">
            {numberLabel(currentMessageCount)} current · {numberLabel(importedMessageCount)} imported
          </span>
        </div>
        {pollVotes !== null && (
          <div className="profile-stat-card">
            <span className="profile-stat-value">{numberLabel(pollVotes)}</span>
            <span className="profile-stat-label">Polls voted</span>
          </div>
        )}
        <div className="profile-stat-card">
          <span className="profile-stat-value">{member.is_online ? 'Online' : fmtRelative(member.last_seen)}</span>
          <span className="profile-stat-label">Last seen</span>
        </div>
        <div className="profile-stat-card">
          <span className="profile-stat-value">{fmtDate(member.joined_at)}</span>
          <span className="profile-stat-label">Member since</span>
        </div>
      </div>

      {isOwnProfile && (
        <div className="profile-actions">
          <button type="button" className="profile-logout-btn" onClick={handleLogout}>
            Sign out
          </button>
        </div>
      )}

      <CollapsibleSection title="Photos" count={photos.length} isOpen={photosOpen} onToggle={() => setPhotosOpen((open) => !open)}>
        {photos.length === 0 ? (
          <p className="profile-activity-empty">No photos yet</p>
        ) : (
          <div className="profile-scroll-panel">
            <div className="profile-photo-grid">
              {photos.map((photo) => (
                <button
                  type="button"
                  key={photo.id}
                  className="profile-photo-card"
                  onClick={() => setOpenPhoto(photo)}
                  aria-label={photo.caption || photo.original_filename || 'Photo'}
                >
                  <img src={photo.thumbnail_url || photo.url} alt="" />
                  <span>{photo.caption || photo.original_filename || fmtDate(photo.created_at)}</span>
                </button>
              ))}
            </div>
          </div>
        )}
      </CollapsibleSection>

      <CollapsibleSection title="Recent activity" count={activity.length} isOpen={activityOpen} onToggle={() => setActivityOpen((open) => !open)}>
        {activity.length === 0 ? (
          <p className="profile-activity-empty">No activity yet</p>
        ) : (
          <div className="profile-scroll-panel">
            <ul className="profile-activity-list">
              {activity.map((item) => {
                const url = getActivityUrl(item);
                const openItem = () => url && onNavigate?.(url);
                return (
                  <li
                    key={item.id}
                    className={`profile-activity-item${url ? ' clickable' : ''}`}
                    onClick={openItem}
                    onKeyDown={(event) => url && handleCardKeyDown(event, openItem)}
                    role={url ? 'button' : undefined}
                    tabIndex={url ? 0 : undefined}
                  >
                    <span className="profile-activity-icon">{ACTION_ICONS[item.action] || '•'}</span>
                    <div className="profile-activity-body">
                      <span className="profile-activity-summary">{item.summary}</span>
                      <span className="profile-activity-time">{fmtRelative(item.created_at)}</span>
                    </div>
                  </li>
                );
              })}
            </ul>
          </div>
        )}
      </CollapsibleSection>

      <CollapsibleSection title="Message history" count={messageHistory.length} isOpen={messagesOpen} onToggle={() => setMessagesOpen((open) => !open)}>
        {isLoadingHistory ? (
          <p className="profile-activity-empty">Loading history…</p>
        ) : historyError ? (
          <p className="profile-activity-empty">{historyError}</p>
        ) : messageHistory.length === 0 ? (
          <p className="profile-activity-empty">No messages yet</p>
        ) : (
          <div className="profile-scroll-panel">
            <ul className="profile-activity-list">
              {messageHistory.map((message) => {
                const openMessage = () => onNavigate?.(buildChatMessageHref(message.id));
                return (
                  <li
                    key={message.id}
                    className="profile-activity-item clickable"
                    onClick={openMessage}
                    onKeyDown={(event) => handleCardKeyDown(event, openMessage)}
                    role="button"
                    tabIndex={0}
                  >
                    <div className="profile-activity-body">
                      <span className="profile-activity-summary">
                        {message.is_imported && <span className="profile-message-source">Messenger</span>}
                        {message.content}
                      </span>
                      <span className="profile-activity-time">{fmtRelative(message.created_at)}</span>
                    </div>
                  </li>
                );
              })}
            </ul>
          </div>
        )}
      </CollapsibleSection>

      <input ref={fileInputRef} type="file" accept="image/*" hidden onChange={handleAvatarFile} />

      {avatarModalOpen && (
        <div className="profile-modal-backdrop" role="presentation" onClick={() => setAvatarModalOpen(false)}>
          <div className="profile-avatar-modal" role="dialog" aria-modal="true" aria-label="Profile picture" onClick={(e) => e.stopPropagation()}>
            <button type="button" className="profile-modal-close" onClick={() => setAvatarModalOpen(false)} aria-label="Close">×</button>
            <UserAvatar
              nickname={member.nickname}
              size={220}
              avatarUrl={member.avatar_url}
              avatarEmoji={member.avatar_emoji || (member.is_bot ? '🤖' : null)}
            />
            {isOwnProfile && (
              <div className="profile-modal-actions">
                <button type="button" onClick={() => fileInputRef.current?.click()} disabled={avatarUploading}>
                  Change photo
                </button>
                {member.avatar_url && (
                  <button type="button" className="danger" onClick={handleRemoveAvatar} disabled={avatarUploading}>
                    Remove photo
                  </button>
                )}
              </div>
            )}
            {avatarError && <p className="profile-edit-error">{avatarError}</p>}
          </div>
        </div>
      )}

      {cropSource && (
        <div className="profile-modal-backdrop" role="presentation" onClick={() => !avatarUploading && setCropSource(null)}>
          <div className="profile-crop-modal" role="dialog" aria-modal="true" aria-label="Crop profile picture" onClick={(e) => e.stopPropagation()}>
            <button type="button" className="profile-modal-close" onClick={() => setCropSource(null)} aria-label="Close" disabled={avatarUploading}>×</button>
            <div
              className={`profile-crop-frame${cropDragActive ? ' is-dragging' : ''}`}
              onPointerDown={startCropDrag}
              onPointerMove={moveCropDrag}
              onPointerUp={stopCropDrag}
              onPointerCancel={stopCropDrag}
              role="presentation"
            >
              <canvas ref={cropCanvasRef} aria-hidden="true" />
            </div>
            <p className="profile-crop-hint">Drag the photo to frame it</p>
            <label className="profile-crop-control">
              Zoom
              <input
                type="range"
                min="1"
                max="3"
                step="0.05"
                value={cropZoom}
                onChange={(e) => setCropZoom(Number(e.target.value))}
              />
            </label>
            <div className="profile-modal-actions">
              <button type="button" onClick={handleUploadCroppedAvatar} disabled={avatarUploading}>
                {avatarUploading ? 'Uploading…' : 'Use photo'}
              </button>
              <button
                type="button"
                onClick={() => { setCropX(50); setCropY(50); setCropZoom(1); }}
                disabled={avatarUploading}
              >
                Reset
              </button>
              <button type="button" onClick={() => setCropSource(null)} disabled={avatarUploading}>
                Cancel
              </button>
            </div>
            {avatarError && <p className="profile-edit-error">{avatarError}</p>}
          </div>
        </div>
      )}

      <PhotoModal
        photo={openPhoto ? { ...openPhoto, showSeeInPhotos: true } : null}
        onClose={() => setOpenPhoto(null)}
      />
    </section>
  );
}
