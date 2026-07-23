import React, { useState, useEffect } from 'react';
import { updateDraftAction, sendHubItemToChat } from '../../services/api.js';
import './DraftActionCard.css';

// ── Type meta ─────────────────────────────────────────────────────────────────

const TYPE_META = {
  poll:     { label: 'Poll',     icon: '📊', cls: 'dac--poll' },
  event:    { label: 'Event',    icon: '📅', cls: 'dac--event' },
  reminder: { label: 'Reminder', icon: '🔔', cls: 'dac--reminder' },
};

// ── Date/time helpers ─────────────────────────────────────────────────────────

function pad(n) { return String(n).padStart(2, '0'); }

function isoToDate(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d)) return '';
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function isoToTime(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d)) return '';
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function mergeDatetime(dateStr, timeStr, fallbackIso) {
  const base = dateStr || isoToDate(fallbackIso);
  const time = timeStr || isoToTime(fallbackIso) || '00:00';
  if (!base) return null;
  return new Date(`${base}T${time}`).toISOString();
}

// ── Shared sub-components ─────────────────────────────────────────────────────

function Field({ label, children }) {
  return (
    <div className="dac-field">
      <span className="dac-field-label">{label}</span>
      {children}
    </div>
  );
}

function DateTimeInput({ isoValue, onChange }) {
  const dateVal = isoToDate(isoValue);
  const timeVal = isoToTime(isoValue);
  return (
    <div className="dac-datetime-row">
      <input
        className="dac-input"
        type="date"
        value={dateVal}
        onChange={e => onChange(mergeDatetime(e.target.value, timeVal, isoValue))}
      />
      <input
        className="dac-input"
        type="time"
        value={timeVal}
        onChange={e => onChange(mergeDatetime(dateVal, e.target.value, isoValue))}
      />
    </div>
  );
}

// ── Per-type editors ──────────────────────────────────────────────────────────

function PollEditor({ title, setTitle, draft, setDraft }) {
  const options = Array.isArray(draft.options) ? draft.options : [];
  const setOption = (i, val) => { const next = [...options]; next[i] = val; setDraft(d => ({ ...d, options: next })); };
  const addOption = () => setDraft(d => ({ ...d, options: [...options, ''] }));
  const removeOption = i => setDraft(d => ({ ...d, options: options.filter((_, j) => j !== i) }));

  return (
    <div className="dac-fields">
      <Field label="Question">
        <input className="dac-input" type="text" value={title} onChange={e => setTitle(e.target.value)} placeholder="What are you voting on?" />
      </Field>
      <Field label="Options">
        <div className="dac-options-list">
          {options.map((opt, i) => (
            <div key={i} className="dac-option-row">
              <input className="dac-input" type="text" value={opt} onChange={e => setOption(i, e.target.value)} placeholder={`Option ${i + 1}`} />
              <button type="button" className="dac-remove-btn" onClick={() => removeOption(i)} aria-label="Remove">×</button>
            </div>
          ))}
          <button type="button" className="dac-add-btn" onClick={addOption}>+ Add option</button>
        </div>
      </Field>
      <Field label="Closes">
        <DateTimeInput isoValue={draft.closes_at} onChange={v => setDraft(d => ({ ...d, closes_at: v }))} />
      </Field>
      <TagsEditor draft={draft} setDraft={setDraft} />
    </div>
  );
}

function EventEditor({ title, setTitle, draft, setDraft }) {
  return (
    <div className="dac-fields">
      <Field label="Event name">
        <input className="dac-input" type="text" value={title} onChange={e => setTitle(e.target.value)} placeholder="What's happening?" />
      </Field>
      <Field label="Location">
        <input className="dac-input" type="text" value={draft.location || ''} onChange={e => setDraft(d => ({ ...d, location: e.target.value }))} placeholder="Where?" />
      </Field>
      <Field label="Starts">
        <DateTimeInput isoValue={draft.starts_at} onChange={v => setDraft(d => ({ ...d, starts_at: v }))} />
      </Field>
      <Field label="Ends">
        <DateTimeInput isoValue={draft.ends_at} onChange={v => setDraft(d => ({ ...d, ends_at: v }))} />
      </Field>
      <Field label="Description">
        <textarea className="dac-input dac-textarea" value={draft.description || ''} onChange={e => setDraft(d => ({ ...d, description: e.target.value }))} placeholder="Optional details" rows={2} />
      </Field>
      <TagsEditor draft={draft} setDraft={setDraft} />
    </div>
  );
}

function ReminderEditor({ title, setTitle, draft, setDraft }) {
  return (
    <div className="dac-fields">
      <Field label="Reminder">
        <input className="dac-input" type="text" value={title} onChange={e => setTitle(e.target.value)} placeholder="What's the reminder?" />
      </Field>
      <Field label="When">
        <DateTimeInput isoValue={draft.remind_at} onChange={v => setDraft(d => ({ ...d, remind_at: v }))} />
      </Field>
      <Field label="Context">
        <textarea className="dac-input" rows={3} value={draft.context || ''} onChange={e => setDraft(d => ({ ...d, context: e.target.value }))} placeholder="Optional context for Hub Bot" />
      </Field>
      <TagsEditor draft={draft} setDraft={setDraft} />
    </div>
  );
}

// ── Shared tags editor ────────────────────────────────────────────────────────

function TagsEditor({ draft, setDraft }) {
  const tags = Array.isArray(draft.tags) ? draft.tags : [];
  const [input, setInput] = useState('');

  const addTag = (raw) => {
    const tag = raw.trim().replace(/^#+/, '').toLowerCase();
    if (!tag || tags.includes(tag)) return;
    setDraft(d => ({ ...d, tags: [...(d.tags || []), tag] }));
  };

  const handleKey = (e) => {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault();
      addTag(input);
      setInput('');
    }
    if (e.key === 'Backspace' && input === '' && tags.length > 0) {
      setDraft(d => ({ ...d, tags: d.tags.slice(0, -1) }));
    }
  };

  return (
    <Field label="Tags">
      <div className="dac-tags-row">
        {tags.map(tag => (
          <span key={tag} className="dac-tag">
            #{tag}
            <button type="button" onClick={() => setDraft(d => ({ ...d, tags: d.tags.filter(t => t !== tag) }))} aria-label={`Remove #${tag}`}>×</button>
          </span>
        ))}
        <input
          className="dac-tag-input"
          type="text"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKey}
          onBlur={() => { if (input.trim()) { addTag(input); setInput(''); } }}
          placeholder={tags.length ? '' : 'Add tags…'}
        />
      </div>
    </Field>
  );
}

const EDITORS = { poll: PollEditor, event: EventEditor, reminder: ReminderEditor };

// ── Accepted card detail ──────────────────────────────────────────────────────

function formatAcceptedDate(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  if (isNaN(d)) return null;
  return new Intl.DateTimeFormat(undefined, {
    weekday: 'short', day: 'numeric', month: 'short',
    hour: 'numeric', minute: '2-digit',
  }).format(d);
}

function getAcceptedDate(item_type, payload_json) {
  if (item_type === 'event')    return formatAcceptedDate(payload_json.starts_at);
  if (item_type === 'reminder') return formatAcceptedDate(payload_json.remind_at);
  if (item_type === 'poll')     return formatAcceptedDate(payload_json.closes_at);
  return null;
}

function getViewRoute(draftAction) {
  const { item_type, created_event_id, created_poll_id, created_reminder_id, created_hub_item_id } = draftAction;
  if (item_type === 'event' && created_event_id) return `/events/${created_event_id}`;
  if (item_type === 'poll' && (created_poll_id || created_hub_item_id)) return '/polls';
  if (item_type === 'reminder' && (created_reminder_id || created_hub_item_id)) return '/reminders';
  if (created_hub_item_id) return '/items';
  return null;
}

const ITEM_PREFIX = { event: 'E', poll: 'P', reminder: 'R' };

function getShortId(draftAction) {
  const { item_type, created_event_id, created_poll_id, created_reminder_id } = draftAction;
  const prefix = ITEM_PREFIX[item_type];
  const num = created_event_id || created_poll_id || created_reminder_id;
  return prefix && num ? `#${prefix}-${num}` : null;
}

function AcceptedResult({ draftAction }) {
  const { item_type, payload_json = {}, created_hub_item_id } = draftAction;
  const date = getAcceptedDate(item_type, payload_json);
  const route = getViewRoute(draftAction);
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);
  const [sendError, setSendError] = useState(null);

  const handleSendToChat = async () => {
    if (!created_hub_item_id) return;
    setSending(true);
    setSendError(null);
    try {
      await sendHubItemToChat(created_hub_item_id);
      setSent(true);
      setTimeout(() => setSent(false), 3000);
    } catch (err) {
      setSendError(err.message);
    } finally {
      setSending(false);
    }
  };

  const shortId = getShortId(draftAction);
  const tags = Array.isArray(payload_json.tags) ? payload_json.tags : [];

  return (
    <div className="dac-result">
      <div className="dac-result-meta">
        {shortId && <span className="dac-short-id">{shortId}</span>}
        {date && <span className="dac-result-date">{date}</span>}
      </div>
      {tags.length > 0 && (
        <div className="dac-result-tags">
          {tags.map(t => <span key={t} className="dac-result-tag">#{t}</span>)}
        </div>
      )}
      <div className="dac-result-actions">
        {route && (
          <a href={route} className="dac-result-btn dac-result-btn--view">
            View →
          </a>
        )}
        {created_hub_item_id && (
          <button
            type="button"
            className={`dac-result-btn dac-result-btn--chat${sent ? ' sent' : ''}`}
            onClick={handleSendToChat}
            disabled={sending || sent}
          >
            {sent ? '✓ Sent' : sending ? '…' : '↗ Send to chat'}
          </button>
        )}
      </div>
      {sendError && <span className="dac-result-error">{sendError}</span>}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export default function DraftActionCard({ draftAction, onAccept, onReject, loading = false, error = null }) {
  const { item_type, status, title, payload_json = {} } = draftAction;

  const typeMeta = TYPE_META[item_type] || { label: item_type, icon: '📌', cls: '' };
  const isDraft    = status === 'draft';
  const isAccepted = status === 'accepted';

  const [editTitle, setEditTitle]     = useState(title);
  const [editPayload, setEditPayload] = useState(payload_json);
  const [saving, setSaving]           = useState(false);
  const [saveError, setSaveError]     = useState(null);

  useEffect(() => {
    setEditTitle(title);
    setEditPayload(payload_json);
  }, [draftAction.id, status]);

  const Editor = EDITORS[item_type];

  const handleConfirm = async () => {
    setSaving(true);
    setSaveError(null);
    try {
      await updateDraftAction(draftAction.id, { title: editTitle, payload_json: editPayload });
      onAccept(draftAction.id);
    } catch (err) {
      setSaveError(err.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className={`dac-card ${typeMeta.cls}`}>
      <div className="dac-header">
        <span className="dac-type-badge">{typeMeta.icon} {typeMeta.label}</span>
        {isDraft && <span className="dac-eyebrow">Confirm to create</span>}
        {isAccepted && <span className="dac-eyebrow dac-eyebrow--done">✓ Created</span>}
        {status === 'rejected' && <span className="dac-eyebrow dac-eyebrow--dismissed">Dismissed</span>}
      </div>

      {isDraft && Editor ? (
        <Editor title={editTitle} setTitle={setEditTitle} draft={editPayload} setDraft={setEditPayload} />
      ) : (
        <p className="dac-static-title">{title}</p>
      )}

      {(error || saveError) && <p className="dac-error">{error || saveError}</p>}

      {isDraft && (
        <div className="dac-actions">
          <button className="dac-btn dac-btn-confirm" onClick={handleConfirm} disabled={saving || loading}>
            {saving || loading ? 'Creating…' : '✓ Create'}
          </button>
          <button className="dac-btn dac-btn-dismiss" onClick={() => onReject(draftAction.id)} disabled={saving || loading}>
            Dismiss
          </button>
        </div>
      )}

      {isAccepted && <AcceptedResult draftAction={draftAction} />}
    </div>
  );
}
