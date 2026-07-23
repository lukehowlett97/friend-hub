import React from 'react';

export const NOTE_TYPES = ['general', 'idea', 'memory', 'story', 'plan', 'recommendation', 'rule'];
export const EDIT_MODES = ['owner_only', 'collaborative'];

const stripHash = (value) => (value || '').replace(/^#+/, '');
const SHORT_ID_RE = /^[A-Za-z][A-Za-z0-9_-]{1,18}$/;

export default function NoteEditor({ form, setForm, onSubmit, submitLabel = 'Save Note', compact = false }) {
  const showReferenceTag = Object.prototype.hasOwnProperty.call(form, 'reference_tag');
  const referenceTag = stripHash(form.reference_tag || '');
  const referenceTagInvalid = showReferenceTag && referenceTag && !SHORT_ID_RE.test(referenceTag);

  return (
    <form className={`feature-form stacked-form note-editor${compact ? ' compact' : ''}`} onSubmit={onSubmit}>
      <input
        value={form.title}
        onChange={(event) => setForm({ ...form, title: event.target.value })}
        placeholder="Note title"
        maxLength={220}
        required
      />
      <div className="form-row">
        <select value={form.note_type} onChange={(event) => setForm({ ...form, note_type: event.target.value })}>
          {NOTE_TYPES.map((type) => <option key={type} value={type}>{type}</option>)}
        </select>
        <select value={form.edit_mode} onChange={(event) => setForm({ ...form, edit_mode: event.target.value })}>
          {EDIT_MODES.map((mode) => <option key={mode} value={mode}>{mode}</option>)}
        </select>
      </div>
      {showReferenceTag && (
        <label className="form-label-small note-reference-field">
          <span>Reference tag</span>
          <span className="note-reference-input">
            <span aria-hidden="true">#</span>
            <input
              value={referenceTag}
              onChange={(event) => setForm({ ...form, reference_tag: stripHash(event.target.value) })}
              maxLength={19}
              placeholder="N-1 or core-vision"
              aria-invalid={referenceTagInvalid || undefined}
              required
            />
          </span>
          <small>
            {referenceTagInvalid
              ? 'Start with a letter; use letters, numbers, hyphens or underscores.'
              : `Type #${referenceTag || 'N-1'} in chat to link to this note.`}
          </small>
        </label>
      )}
      <textarea
        value={form.body}
        onChange={(event) => setForm({ ...form, body: event.target.value })}
        placeholder="Write the note..."
        rows={compact ? 5 : 8}
      />
      <label className="form-label-small">
        <input
          type="checkbox"
          checked={!!form.is_pinned}
          onChange={(event) => setForm({ ...form, is_pinned: event.target.checked })}
        />
        Pin to home
      </label>
      <button type="submit">{submitLabel}</button>
    </form>
  );
}
