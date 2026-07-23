import React from 'react';

function formatDate(value) {
  if (!value) return '';
  return new Date(value).toLocaleString([], { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
}

export default function NoteCard({ note, onOpen, onPin }) {
  const preview = (note.body || '').trim();
  const creator = note.creator?.nickname || 'Friend';
  return (
    <article className="planning-card note-card">
      <button type="button" className="note-card__main" onClick={() => onOpen?.(note)}>
        <div className="hub-item-meta__line">
          {note.short_id && <strong>{note.short_id}</strong>}
          <span>{note.note_type}</span>
          <span>{note.edit_mode}</span>
        </div>
        <h2>{note.title}</h2>
        {preview && <p>{preview.length > 180 ? `${preview.slice(0, 180)}...` : preview}</p>}
        <div className="note-card__meta">
          <span>{creator}</span>
          <span>{formatDate(note.updated_at || note.created_at)}</span>
          {note.comment_count > 0 && <span>{note.comment_count} comments</span>}
        </div>
      </button>
      {note.permissions?.can_pin && (
        <button
          type="button"
          className={`hub-btn hub-btn--icon hub-btn--pin${note.pinned_to_home ? ' active' : ''}`}
          onClick={() => onPin?.(note)}
          aria-label={`${note.pinned_to_home ? 'Unpin' : 'Pin'} ${note.short_id || note.title}`}
          title={note.pinned_to_home ? 'Unpin' : 'Pin'}
        >
          <span aria-hidden="true">📌</span>
        </button>
      )}
    </article>
  );
}

