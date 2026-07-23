import React, { useEffect, useState } from 'react';
import { updateReminder } from '../../services/api.js';
import { openNativeDatePicker } from '../../utils/nativeDatePicker.js';
import './PollEditModal.css';

const RECURRENCE_OPTIONS = [
  { value: '', label: 'One-time' },
  { value: 'daily', label: 'Daily' },
  { value: 'weekly', label: 'Weekly' },
  { value: 'every_N_days', label: 'Every N days' },
];

function toLocalDatetime(iso) {
  if (!iso) return '';
  try {
    const dt = new Date(iso);
    if (Number.isNaN(dt.getTime())) return '';
    const pad = (n) => String(n).padStart(2, '0');
    return `${dt.getFullYear()}-${pad(dt.getMonth() + 1)}-${pad(dt.getDate())}T${pad(dt.getHours())}:${pad(dt.getMinutes())}`;
  } catch {
    return '';
  }
}

const ReminderEditModal = ({ reminder, members = [], onClose, onSaved }) => {
  const [title, setTitle] = useState(reminder?.title || reminder?.text || '');
  const [context, setContext] = useState(reminder?.context || '');
  const [dueAt, setDueAt] = useState(toLocalDatetime(reminder?.due_at));
  const [recurrence, setRecurrence] = useState(reminder?.recurrence || '');
  const [recurrenceDays, setRecurrenceDays] = useState(reminder?.recurrence_days || '');
  const [recurrenceEndsAt, setRecurrenceEndsAt] = useState(toLocalDatetime(reminder?.recurrence_ends_at));
  const [assigneeIds, setAssigneeIds] = useState(
    (reminder?.assignees || []).map((a) => a.id).filter(Boolean)
  );
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    const handler = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  const toggleAssignee = (id, checked) => {
    setAssigneeIds((prev) => checked ? [...prev, id] : prev.filter((x) => x !== id));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!title.trim()) { setError('Title is required'); return; }
    if (!dueAt) { setError('Due date and time are required'); return; }
    if (recurrence === 'every_N_days' && (!recurrenceDays || Number(recurrenceDays) < 2)) {
      setError('Enter the number of days (minimum 2)'); return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await updateReminder(reminder.id, {
        title: title.trim(),
        context: context.trim() || null,
        due_at: new Date(dueAt).toISOString(),
        recurrence: recurrence || null,
        recurrence_days: recurrence === 'every_N_days' ? parseInt(recurrenceDays, 10) || null : null,
        recurrence_ends_at: recurrence && recurrenceEndsAt
          ? new Date(recurrenceEndsAt).toISOString()
          : null,
        assignee_user_ids: assigneeIds,
      });
      onSaved?.();
      onClose();
    } catch (err) {
      setError(err.message || 'Failed to update reminder');
    } finally {
      setSubmitting(false);
    }
  };

  if (!reminder) return null;

  return (
    <div className="poll-edit-overlay" onClick={onClose}>
      <div className="poll-edit-modal" onClick={(e) => e.stopPropagation()}>
        <div className="poll-edit-header">
          <div>
            <h2>Edit reminder</h2>
            <p>Changes apply immediately.</p>
          </div>
          <button type="button" className="poll-edit-close" onClick={onClose} aria-label="Close">✕</button>
        </div>

        <form className="poll-edit-form" onSubmit={handleSubmit}>
          <label>
            <span>Title</span>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              maxLength={220}
              placeholder="What needs to be done?"
              required
            />
          </label>

          <label>
            <span>Context <small>(optional — shown on the card and sent with push reminders)</small></span>
            <textarea
              value={context}
              onChange={(e) => setContext(e.target.value)}
              rows={3}
              maxLength={2000}
              placeholder="Any extra detail about this reminder…"
            />
          </label>

          <label>
            <span>Due date &amp; time</span>
            <input
              type="datetime-local"
              value={dueAt}
              onChange={(e) => setDueAt(e.target.value)}
              onClick={openNativeDatePicker}
              required
            />
          </label>

          <div>
            <label>
              <span>Recurrence</span>
              <div className="reminder-edit-recurrence-row">
                <select
                  value={recurrence}
                  onChange={(e) => { setRecurrence(e.target.value); setRecurrenceDays(''); }}
                >
                  {RECURRENCE_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>{o.label}</option>
                  ))}
                </select>
                {recurrence === 'every_N_days' && (
                  <input
                    type="number"
                    min="2"
                    max="365"
                    placeholder="days"
                    value={recurrenceDays}
                    onChange={(e) => setRecurrenceDays(e.target.value)}
                    className="reminder-edit-days-input"
                    required
                  />
                )}
              </div>
            </label>
            {recurrence && (
              <label style={{ marginTop: '8px' }}>
                <span>Ends <small>(optional)</small></span>
                <input
                  type="datetime-local"
                  value={recurrenceEndsAt}
                  onChange={(e) => setRecurrenceEndsAt(e.target.value)}
                  onClick={openNativeDatePicker}
                />
              </label>
            )}
          </div>

          {members.length > 0 && (
            <div>
              <span className="poll-edit-form-section-label">Assigned to</span>
              <div className="reminder-edit-assignees">
                {members.map((m) => (
                  <label key={m.id} className="reminder-edit-assignee-check">
                    <input
                      type="checkbox"
                      checked={assigneeIds.includes(m.id)}
                      onChange={(e) => toggleAssignee(m.id, e.target.checked)}
                    />
                    {m.nickname}
                  </label>
                ))}
              </div>
            </div>
          )}

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

export default ReminderEditModal;
