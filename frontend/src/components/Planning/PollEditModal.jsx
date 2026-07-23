import React, { useEffect, useState } from 'react';
import { updatePoll, updateHubItem } from '../../services/api.js';
import './PollEditModal.css';

const toLocalInputValue = (iso) => {
  if (!iso) return '';
  try {
    const dt = new Date(iso);
    if (Number.isNaN(dt.getTime())) return '';
    const pad = (n) => String(n).padStart(2, '0');
    return `${dt.getFullYear()}-${pad(dt.getMonth() + 1)}-${pad(dt.getDate())}T${pad(dt.getHours())}:${pad(dt.getMinutes())}`;
  } catch {
    return '';
  }
};

const stripHash = (value) => (value || '').replace(/^#+/, '');

const SHORT_ID_RE = /^[A-Za-z][A-Za-z0-9_-]{1,18}$/;

const PollEditModal = ({ poll, onClose, onSaved }) => {
  const isAgenda = poll?.source === 'chat_agenda';
  const isGeneralAgenda = isAgenda && poll?.event_type === 'general_vote';
  const isDerivedQuestion = isAgenda && !isGeneralAgenda;

  const initialTitle = poll?.hub_item?.title || poll?.question || '';
  const initialBody = poll?.hub_item?.body || '';
  const initialShortId = stripHash(poll?.short_id || poll?.hub_item?.short_id || '');
  const hubItemId = poll?.hub_item?.id || poll?.hub_item_id || null;

  const [title, setTitle] = useState(initialTitle);
  const [question, setQuestion] = useState(poll?.question || '');
  const [description, setDescription] = useState(initialBody);
  const [shortIdBody, setShortIdBody] = useState(initialShortId);
  const [opensAt, setOpensAt] = useState(toLocalInputValue(poll?.voting_opens_at));
  const [closesAt, setClosesAt] = useState(toLocalInputValue(poll?.deadline_at));
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    const handler = (event) => { if (event.key === 'Escape') onClose(); };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  const shortIdInvalid = shortIdBody && !SHORT_ID_RE.test(shortIdBody);
  const shortIdChanged = shortIdBody && shortIdBody !== initialShortId;

  const handleSubmit = async (event) => {
    event.preventDefault();
    if (!title.trim()) { setError('Title is required'); return; }
    if (!shortIdBody.trim()) { setError('Reference tag is required'); return; }
    if (shortIdInvalid) {
      setError('Reference tag must start with a letter and contain only letters, numbers, hyphens or underscores (2-19 chars)');
      return;
    }
    if (opensAt && closesAt && new Date(closesAt) <= new Date(opensAt)) {
      setError('Voting close must be after voting open');
      return;
    }
    setSubmitting(true);
    setError(null);
    const payload = {
      title: title.trim(),
      description: description.trim() || null,
    };
    if (!isDerivedQuestion) {
      payload.question = (isGeneralAgenda ? question : title).trim();
    }
    if (opensAt) payload.voting_opens_at = new Date(opensAt).toISOString();
    if (closesAt) payload.deadline_at = new Date(closesAt).toISOString();
    try {
      await updatePoll(poll.id, payload);
      // The reference tag lives on the hub_item, not the poll row; update it
      // separately so we can surface a clean conflict error when the tag is
      // already taken.
      if (shortIdChanged && hubItemId) {
        await updateHubItem(hubItemId, { short_id: `#${shortIdBody.trim()}` });
      }
      onSaved?.();
      onClose();
    } catch (err) {
      setError(err.message || 'Failed to update poll');
    } finally {
      setSubmitting(false);
    }
  };

  if (!poll) return null;

  return (
    <div className="poll-edit-overlay" onClick={onClose}>
      <div className="poll-edit-modal" onClick={(e) => e.stopPropagation()}>
        <div className="poll-edit-header">
          <div>
            <h2>Edit poll</h2>
            <p>Changes are saved to history.</p>
          </div>
          <button type="button" className="poll-edit-close" onClick={onClose} aria-label="Close">✕</button>
        </div>

        <form className="poll-edit-form" onSubmit={handleSubmit}>
          <label>
            <span>Title</span>
            <input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={120} required />
          </label>

          {isGeneralAgenda && (
            <label>
              <span>Poll question</span>
              <input value={question} onChange={(e) => setQuestion(e.target.value)} maxLength={220} required />
            </label>
          )}

          {isDerivedQuestion && (
            <p className="poll-edit-hint">
              The question for {poll.event_type === 'nickname_vote' ? 'nickname' : 'role'} motions is generated from the target and proposal — only the title, description, reference tag and timing can be edited here.
            </p>
          )}

          <label>
            <span>Description</span>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
              maxLength={2000}
              placeholder="Optional context"
            />
          </label>

          <label>
            <span>Reference tag <small>(used to link to this poll in chat)</small></span>
            <div className="poll-edit-short-id">
              <span className="poll-edit-short-id-hash">#</span>
              <input
                value={shortIdBody}
                onChange={(e) => setShortIdBody(stripHash(e.target.value))}
                maxLength={19}
                placeholder="P-8 or mike-rename"
                aria-invalid={shortIdInvalid || undefined}
              />
            </div>
            <small className="poll-edit-short-id-hint">
              {shortIdInvalid
                ? 'Must start with a letter; only letters, numbers, hyphens and underscores (2–19 chars).'
                : 'Type ' + (shortIdBody ? `#${shortIdBody}` : '#P-8') + ' in chat to link to this poll.'}
            </small>
          </label>

          <div className="poll-edit-time-row">
            <label>
              <span>Voting opens</span>
              <input
                type="datetime-local"
                value={opensAt}
                onChange={(e) => setOpensAt(e.target.value)}
              />
            </label>
            <label>
              <span>Voting closes</span>
              <input
                type="datetime-local"
                value={closesAt}
                onChange={(e) => setClosesAt(e.target.value)}
              />
            </label>
          </div>

          {error && <p className="poll-edit-error">{error}</p>}

          <div className="poll-edit-actions">
            <button type="button" className="poll-edit-cancel" onClick={onClose}>Cancel</button>
            <button type="submit" className="poll-edit-submit" disabled={submitting}>
              {submitting ? 'Saving…' : 'Save changes'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

export default PollEditModal;
