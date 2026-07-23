import React, { useEffect, useState } from 'react';
import CreatorCard from '../components/Planning/CreatorCard.jsx';
import EngagementPanel from '../components/Planning/EngagementPanel.jsx';
import HubItemCardMeta from '../components/Planning/HubItemCardMeta.jsx';
import ReminderEditModal from '../components/Planning/ReminderEditModal.jsx';
import {
  completeReminder,
  createReminder,
  deleteReminder,
  fetchMembers,
  fetchReminders,
  pinHubItem,
  sendHubItemToChat,
} from '../services/api.js';
import { useAuth } from '../auth/AuthProvider.jsx';
import { openNativeDatePicker } from '../utils/nativeDatePicker.js';
import './FeaturePages.css';

const RECURRENCE_OPTIONS = [
  { value: '', label: 'One-time' },
  { value: 'daily', label: 'Daily' },
  { value: 'weekly', label: 'Weekly' },
  { value: 'every_N_days', label: 'Every N days' },
];

function recurrenceLabel(reminder) {
  if (!reminder.recurrence) return null;
  if (reminder.recurrence === 'daily') return 'Repeats daily';
  if (reminder.recurrence === 'weekly') return 'Repeats weekly';
  if (reminder.recurrence === 'every_N_days' && reminder.recurrence_days)
    return `Repeats every ${reminder.recurrence_days} days`;
  return null;
}

const EMPTY_FORM = {
  title: '',
  due_date: '',
  due_time: '',
  context: '',
  assignee_user_ids: [],
  recurrence: '',
  recurrence_days: '',
  recurrence_ends_at: '',
};

const RemindersPage = ({ onNavigate }) => {
  const { user } = useAuth();
  const [reminders, setReminders] = useState([]);
  const [members, setMembers] = useState([]);
  const [error, setError] = useState(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [editingReminder, setEditingReminder] = useState(null);

  const loadReminders = () => {
    fetchReminders()
      .then((data) => { setReminders(data.reminders || []); setError(null); })
      .catch((err) => setError(err.message));
  };

  useEffect(() => {
    loadReminders();
    fetchMembers().then((data) => setMembers(data.members || [])).catch(() => setMembers([]));
  }, []);

  const submitReminder = async (e) => {
    e.preventDefault();
    try {
      await createReminder({
        title: form.title,
        due_at: new Date(`${form.due_date}T${form.due_time}`).toISOString(),
        context: form.context.trim() || null,
        assignee_user_ids: form.assignee_user_ids,
        recurrence: form.recurrence || null,
        recurrence_days: form.recurrence === 'every_N_days' ? parseInt(form.recurrence_days, 10) || null : null,
        recurrence_ends_at: form.recurrence && form.recurrence_ends_at
          ? new Date(form.recurrence_ends_at).toISOString()
          : null,
      });
      setForm(EMPTY_FORM);
      loadReminders();
    } catch (err) {
      setError(err.message);
    }
  };

  const toggleAssignee = (memberId, checked) => {
    setForm((f) => ({
      ...f,
      assignee_user_ids: checked
        ? [...f.assignee_user_ids, memberId]
        : f.assignee_user_ids.filter((id) => id !== memberId),
    }));
  };

  const toggleComplete = async (reminder) => {
    try { await completeReminder(reminder.id, !reminder.is_completed); loadReminders(); }
    catch (err) { setError(err.message); }
  };

  const editReminder = (reminder) => {
    setEditingReminder(reminder);
  };

  const removeReminder = async (reminder) => {
    if (!window.confirm('Delete this reminder?\n\nThis will move it to the archive.')) return;
    try { await deleteReminder(reminder.id); loadReminders(); }
    catch (err) { setError(err.message); }
  };

  const togglePin = async (item) => {
    try { await pinHubItem(item.id, !item.pinned_to_home); loadReminders(); }
    catch (err) { setError(err.message); }
  };

  const sendToChat = async (item) => { await sendHubItemToChat(item.id); loadReminders(); };
  const prepareChatMessage = (item) => onNavigate?.(`/chat?draft=${encodeURIComponent(item.short_id || '')}`);

  const canManage = (reminder) => {
    const role = user?.role;
    return role === 'owner' || role === 'admin' || reminder.creator?.id === user?.id;
  };

  return (
    <section className="page feature-page">
      <header className="page-header">
        <h1>Reminders</h1>
        <p className="page-subtitle">Track shared jobs, admin, and plan prep.</p>
      </header>

      <form className="feature-form stacked-form reminder-form" onSubmit={submitReminder}>
        <input
          value={form.title}
          onChange={(e) => setForm({ ...form, title: e.target.value })}
          placeholder="Reminder title"
          required
        />
        <input
          type="date"
          value={form.due_date}
          onChange={(e) => setForm({ ...form, due_date: e.target.value })}
          onClick={openNativeDatePicker}
          required
        />
        <input
          type="time"
          value={form.due_time}
          onChange={(e) => setForm({ ...form, due_time: e.target.value })}
          onClick={openNativeDatePicker}
          required
        />

        {/* Recurrence */}
        <div className="form-row">
          <select
            value={form.recurrence}
            onChange={(e) => setForm({ ...form, recurrence: e.target.value, recurrence_days: '' })}
            style={{ flex: 1 }}
          >
            {RECURRENCE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>

          {form.recurrence === 'every_N_days' && (
            <input
              type="number"
              min="2"
              max="365"
              placeholder="days"
              value={form.recurrence_days}
              onChange={(e) => setForm({ ...form, recurrence_days: e.target.value })}
              style={{ width: '80px' }}
              required
            />
          )}
        </div>

        {form.recurrence && (
          <label className="form-label-small">
            Ends (optional)
            <input
              type="datetime-local"
              value={form.recurrence_ends_at}
              onChange={(e) => setForm({ ...form, recurrence_ends_at: e.target.value })}
              onClick={openNativeDatePicker}
            />
          </label>
        )}

        <textarea
          className="reminder-context-input"
          value={form.context}
          onChange={(e) => setForm({ ...form, context: e.target.value })}
          placeholder="Context for Hub Bot's reminder message"
          rows={3}
        />

        {/* Assignees */}
        <div className="assignee-picker">
          {members.map((member) => (
            <label key={member.id || member.session_id}>
              <input
                type="checkbox"
                checked={form.assignee_user_ids.includes(member.id)}
                onChange={(e) => toggleAssignee(member.id, e.target.checked)}
              />
              {member.nickname}
            </label>
          ))}
        </div>

        <button type="submit">Add Reminder</button>
      </form>

      {error && <div className="inline-error">{error}</div>}

      <div className="feature-list">
        {reminders.map((reminder) => (
          <article key={reminder.id} className={`planning-card ${reminder.is_completed ? 'is-complete' : ''}`}>
            <HubItemCardMeta
              item={reminder.hub_item}
              onPin={togglePin}
              onSendToChat={sendToChat}
              onPrepareChatMessage={prepareChatMessage}
              canEdit={canManage(reminder)}
              canDelete={canManage(reminder)}
              onEdit={() => editReminder(reminder)}
              onDelete={() => removeReminder(reminder)}
              editLabel="Edit reminder"
              deleteLabel="Delete reminder"
            />
            <div className="planning-card-header">
              <div>
                <h2>{reminder.title || reminder.text}</h2>
                <p>
                  {reminder.due_at ? `Due ${new Date(reminder.due_at).toLocaleString()}` : 'No due date'}
                  {reminder.assignees?.length > 0
                    ? ` · ${reminder.assignees.map((u) => u.nickname).join(', ')}`
                    : ''}
                </p>
                {recurrenceLabel(reminder) && (
                  <p className="reminder-recurrence-badge">
                    🔁 {recurrenceLabel(reminder)}
                    {reminder.recurrence_ends_at
                      ? ` until ${new Date(reminder.recurrence_ends_at).toLocaleDateString()}`
                      : ''}
                  </p>
                )}
                {reminder.last_triggered_at && (
                  <p className="reminder-last-fired">
                    Last fired {new Date(reminder.last_triggered_at).toLocaleString()}
                  </p>
                )}
                {reminder.context && (
                  <p className="reminder-context">{reminder.context}</p>
                )}
                <CreatorCard creator={reminder.creator} onNavigate={onNavigate} />
              </div>
              <div className="row-actions">
                <button type="button" onClick={() => toggleComplete(reminder)}>
                  {reminder.is_completed ? 'Reopen' : 'Complete'}
                </button>
              </div>
            </div>
            <EngagementPanel
              targetType="reminder"
              targetId={reminder.id}
              reactions={reminder.reactions}
              commentCount={reminder.comment_count}
              onChange={loadReminders}
            />
          </article>
        ))}
      </div>

      {editingReminder && (
        <ReminderEditModal
          reminder={editingReminder}
          members={members}
          onClose={() => setEditingReminder(null)}
          onSaved={() => { setEditingReminder(null); loadReminders(); }}
        />
      )}
    </section>
  );
};

export default RemindersPage;
