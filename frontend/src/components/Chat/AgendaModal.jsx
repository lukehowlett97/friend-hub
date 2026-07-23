import React, { useEffect, useMemo, useState } from 'react';
import { createChatEvent, fetchMembers } from '../../services/api.js';
import { useAuth } from '../../auth/AuthProvider.jsx';
import { openNativeDatePicker } from '../../utils/nativeDatePicker.js';
import './AgendaModal.css';

const EVENT_TYPES = [
  { value: 'general_vote', label: 'General' },
  { value: 'nickname_vote', label: 'Nickname' },
  { value: 'role_vote', label: 'Chat role' },
];

const isAdminRole = (role) => role === 'owner' || role === 'admin';

const defaultIsoOffsetMinutes = (offsetMinutes) => {
  const now = new Date();
  const future = new Date(now.getTime() + offsetMinutes * 60 * 1000);
  const pad = (n) => String(n).padStart(2, '0');
  return `${future.getFullYear()}-${pad(future.getMonth() + 1)}-${pad(future.getDate())}T${pad(future.getHours())}:${pad(future.getMinutes())}`;
};

const AgendaModal = ({ onClose, onCreated }) => {
  const { user } = useAuth();
  const isAdmin = isAdminRole(user?.role);
  const [members, setMembers] = useState([]);
  const [eventType, setEventType] = useState('general_vote');
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [targetUserId, setTargetUserId] = useState('');
  const [proposedNickname, setProposedNickname] = useState('');
  const [proposedRole, setProposedRole] = useState('');
  const [pollOptions, setPollOptions] = useState('Yes\nNo');
  const [opensAt, setOpensAt] = useState(() => defaultIsoOffsetMinutes(2));
  const [closesAt, setClosesAt] = useState(() => defaultIsoOffsetMinutes(12));
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    fetchMembers().then((data) => setMembers(data.members || [])).catch(() => setMembers([]));
  }, []);

  useEffect(() => {
    const handler = (event) => { if (event.key === 'Escape') onClose(); };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  const memberOptions = useMemo(
    () => members.filter((m) => m.session_id !== user?.session_id),
    [members, user?.session_id],
  );

  const requiresAdmin = eventType !== 'general_vote';
  const submitDisabled = submitting || (requiresAdmin && !isAdmin);

  const handleSubmit = async (event) => {
    event.preventDefault();
    setError(null);

    if (!title.trim()) { setError('Title is required'); return; }
    if (!opensAt || !closesAt) { setError('Voting opens and closes times are required'); return; }
    if (new Date(closesAt) <= new Date(opensAt)) { setError('Voting close must be after open'); return; }

    const payload = {
      event_type: eventType,
      title: title.trim(),
      description: description.trim() || null,
      voting_opens_at: new Date(opensAt).toISOString(),
      voting_closes_at: new Date(closesAt).toISOString(),
    };

    if (eventType === 'nickname_vote' || eventType === 'role_vote') {
      if (!targetUserId) { setError('Pick a target member'); return; }
      payload.target_user_id = targetUserId;
    }
    if (eventType === 'nickname_vote') {
      if (!proposedNickname.trim()) { setError('Proposed nickname is required'); return; }
      payload.proposed_nickname = proposedNickname.trim();
    }
    if (eventType === 'role_vote') {
      if (!proposedRole.trim()) { setError('Proposed chat role is required'); return; }
      payload.proposed_role = proposedRole.trim();
    }
    if (eventType === 'general_vote') {
      const options = pollOptions.split('\n').map((opt) => opt.trim()).filter(Boolean);
      if (options.length < 2) { setError('Add at least two poll options'); return; }
      payload.poll_question = title.trim();
      payload.poll_options = options;
    }

    setSubmitting(true);
    try {
      await createChatEvent(payload);
      onCreated?.();
      onClose();
    } catch (err) {
      setError(err.message || 'Failed to schedule motion');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="agenda-modal-overlay" onClick={onClose}>
      <div className="agenda-modal" onClick={(e) => e.stopPropagation()}>
        <div className="agenda-modal-header">
          <div>
            <h2>Schedule a motion</h2>
            <p>Open a timed council vote in chat</p>
          </div>
          <button type="button" className="agenda-modal-close" onClick={onClose} aria-label="Close">✕</button>
        </div>

        <form className="agenda-modal-form" onSubmit={handleSubmit}>
          <div>
            <label>Motion type</label>
            <div className="agenda-event-type-row" role="group">
              {EVENT_TYPES.map((type) => {
                const disabled = (type.value !== 'general_vote') && !isAdmin;
                return (
                  <button
                    key={type.value}
                    type="button"
                    className={eventType === type.value ? 'active' : ''}
                    onClick={() => setEventType(type.value)}
                    disabled={disabled}
                    title={disabled ? 'Admins/owner only' : ''}
                  >
                    {type.label}
                  </button>
                );
              })}
            </div>
          </div>

          <div>
            <label>{eventType === 'general_vote' ? 'Poll question' : 'Title'}</label>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              maxLength={eventType === 'general_vote' ? 220 : 120}
              placeholder={eventType === 'general_vote' ? 'Where should we go Friday?' : 'Short label, e.g. Rename Mike'}
              required
            />
          </div>

          <div>
            <label>Description (optional)</label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={2}
              placeholder="Why are we voting on this?"
            />
          </div>

          {(eventType === 'nickname_vote' || eventType === 'role_vote') && (
            <div>
              <label>Target member</label>
              <select value={targetUserId} onChange={(e) => setTargetUserId(e.target.value)} required>
                <option value="">Select…</option>
                {memberOptions.map((m) => (
                  <option key={m.id} value={m.id}>{m.nickname}</option>
                ))}
              </select>
            </div>
          )}

          {eventType === 'nickname_vote' && (
            <div>
              <label>Proposed nickname</label>
              <input
                value={proposedNickname}
                onChange={(e) => setProposedNickname(e.target.value)}
                maxLength={50}
                placeholder='e.g. "The Maybe Merchant"'
                required
              />
            </div>
          )}

          {eventType === 'role_vote' && (
            <div>
              <label>Proposed chat role</label>
              <input
                value={proposedRole}
                onChange={(e) => setProposedRole(e.target.value)}
                maxLength={64}
                placeholder='e.g. "Vibes Officer"'
                required
              />
            </div>
          )}

          {eventType === 'general_vote' && (
            <div>
              <label>Poll options (one per line)</label>
              <textarea
                value={pollOptions}
                onChange={(e) => setPollOptions(e.target.value)}
                rows={4}
              />
            </div>
          )}

          <div className="agenda-time-row">
            <div>
              <label>Voting opens</label>
              <input
                type="datetime-local"
                value={opensAt}
                onChange={(e) => setOpensAt(e.target.value)}
                onClick={openNativeDatePicker}
                required
              />
            </div>
            <div>
              <label>Voting closes</label>
              <input
                type="datetime-local"
                value={closesAt}
                onChange={(e) => setClosesAt(e.target.value)}
                onClick={openNativeDatePicker}
                required
              />
            </div>
          </div>

          {requiresAdmin && !isAdmin && (
            <p className="agenda-modal-error">Only admins or the owner can create this motion type.</p>
          )}
          {error && <p className="agenda-modal-error">{error}</p>}

          <div className="agenda-modal-actions">
            <button type="button" className="agenda-modal-cancel" onClick={onClose}>Cancel</button>
            <button type="submit" className="agenda-modal-submit" disabled={submitDisabled}>
              {submitting ? 'Scheduling…' : 'Schedule motion'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

export default AgendaModal;
