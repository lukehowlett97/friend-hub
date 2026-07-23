import React, { useEffect, useState } from 'react';
import NoteEditor from '../components/Notes/NoteEditor.jsx';
import UserAvatar from '../components/Chat/UserAvatar.jsx';
import {
  createNoteComment,
  deleteNote,
  fetchNote,
  fetchNoteComments,
  fetchNoteRevisions,
  pinNote,
  unpinNote,
  updateNote,
} from '../services/api.js';
import './FeaturePages.css';

function formatDate(value) {
  if (!value) return '';
  return new Date(value).toLocaleString();
}

export default function NoteDetailPage({ noteId, onNavigate }) {
  const [note, setNote] = useState(null);
  const [comments, setComments] = useState([]);
  const [revisions, setRevisions] = useState([]);
  const [commentDraft, setCommentDraft] = useState('');
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState(null);
  const [showHistory, setShowHistory] = useState(false);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    Promise.all([
      fetchNote(noteId),
      fetchNoteComments(noteId).catch(() => ({ comments: [] })),
    ])
      .then(([noteData, commentsData]) => {
        setNote(noteData.note);
        setComments(commentsData.comments || []);
        setForm({
          title: noteData.note.title || '',
          body: noteData.note.body || '',
          note_type: noteData.note.note_type || 'general',
          edit_mode: noteData.note.edit_mode || 'owner_only',
          is_pinned: !!noteData.note.pinned_to_home,
          reference_tag: (noteData.note.short_id || '').replace(/^#+/, ''),
        });
        setError(null);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  };

  useEffect(load, [noteId]);

  const saveNote = async (event) => {
    event.preventDefault();
    try {
      const result = await updateNote(note.id, form);
      setNote(result.note);
      setEditing(false);
      load();
    } catch (err) {
      setError(err.message);
    }
  };

  const archiveNote = async () => {
    if (!window.confirm(`Archive "${note.title}"?`)) return;
    try {
      await deleteNote(note.id);
      onNavigate?.('/notes');
    } catch (err) {
      setError(err.message);
    }
  };

  const togglePin = async () => {
    try {
      const result = note.pinned_to_home ? await unpinNote(note.id) : await pinNote(note.id);
      setNote(result.note);
    } catch (err) {
      setError(err.message);
    }
  };

  const submitComment = async (event) => {
    event.preventDefault();
    if (!commentDraft.trim()) return;
    try {
      await createNoteComment(note.id, commentDraft);
      setCommentDraft('');
      load();
    } catch (err) {
      setError(err.message);
    }
  };

  const loadHistory = async () => {
    try {
      const data = await fetchNoteRevisions(note.id);
      setRevisions(data.revisions || []);
      setShowHistory((value) => !value);
    } catch (err) {
      setError(err.message);
    }
  };

  const copyReference = async () => {
    if (!note?.short_id) return;
    try { await navigator.clipboard?.writeText(note.short_id); }
    catch { /* ignore clipboard failures */ }
  };

  if (loading) return <section className="page feature-page"><div className="inline-notice">Loading...</div></section>;
  if (!note) return <section className="page feature-page"><div className="inline-error">{error || 'Note not found'}</div></section>;

  return (
    <section className="page feature-page note-detail-page">
      <header className="page-header note-detail-header">
        <button type="button" className="view-all-btn" onClick={() => onNavigate?.('/notes')}>← Notes</button>
        <div>
          <h1>{note.title}</h1>
          <p className="page-subtitle">
            {note.short_id || '#N'} · {note.note_type} · updated {formatDate(note.updated_at)}
          </p>
        </div>
      </header>

      {error && <div className="inline-error">{error}</div>}

      <div className="planning-card note-detail-card">
        <div className="hub-item-meta">
          <div className="hub-item-meta__line">
            {note.short_id && <strong>{note.short_id}</strong>}
            <span>{note.edit_mode}</span>
            {note.creator && <span>{note.creator.nickname}</span>}
          </div>
          <div className="hub-item-meta__actions">
            {note.short_id && <button type="button" className="hub-btn" onClick={copyReference}>Copy ref</button>}
            {note.permissions?.can_pin && (
              <button type="button" className={`hub-btn hub-btn--pin${note.pinned_to_home ? ' active' : ''}`} onClick={togglePin}>
                {note.pinned_to_home ? 'Unpin' : 'Pin'}
              </button>
            )}
            {note.permissions?.can_edit && <button type="button" className="hub-btn" onClick={() => setEditing((value) => !value)}>{editing ? 'Cancel' : 'Edit'}</button>}
            {note.permissions?.can_delete && <button type="button" className="hub-btn danger" onClick={archiveNote}>Archive</button>}
          </div>
        </div>

        {editing && form ? (
          <NoteEditor form={form} setForm={setForm} onSubmit={saveNote} submitLabel="Save Note" />
        ) : (
          <div className="note-body">
            {(note.body || '').split('\n').map((line, index) => (
              <p key={index}>{line || '\u00a0'}</p>
            ))}
          </div>
        )}
      </div>

      <section className="planning-card">
        <div className="planning-card-header">
          <div>
            <span className="eyebrow">Comments</span>
            <h2>{comments.length} comment{comments.length === 1 ? '' : 's'}</h2>
          </div>
        </div>
        <div className="note-comments">
          {comments.map((comment) => (
            <div key={comment.id} className="note-comment">
              <UserAvatar nickname={comment.creator?.nickname || 'Friend'} size={28} avatarUrl={comment.creator?.avatar_url} />
              <div>
                <strong>{comment.creator?.nickname || 'Friend'}</strong>
                <p>{comment.content}</p>
                <span>{formatDate(comment.created_at)}</span>
              </div>
            </div>
          ))}
        </div>
        {note.permissions?.can_comment && (
          <form className="feature-form note-comment-form" onSubmit={submitComment}>
            <textarea value={commentDraft} onChange={(event) => setCommentDraft(event.target.value)} placeholder="Add a comment" rows={3} />
            <button type="submit">Comment</button>
          </form>
        )}
      </section>

      {note.permissions?.can_view_revisions && (
        <section className="planning-card">
          <div className="planning-card-header">
            <div>
              <span className="eyebrow">History</span>
              <h2>{note.revision_count} revision{note.revision_count === 1 ? '' : 's'}</h2>
            </div>
            <button type="button" onClick={loadHistory}>{showHistory ? 'Hide' : 'View'}</button>
          </div>
          {showHistory && (
            <div className="note-revisions">
              {revisions.map((revision) => (
                <div key={revision.id} className="note-revision">
                  <strong>{revision.changer?.nickname || 'Someone'} edited this note</strong>
                  <span>{formatDate(revision.created_at)}</span>
                </div>
              ))}
              {revisions.length === 0 && <p className="dashboard-meta">No revisions yet.</p>}
            </div>
          )}
        </section>
      )}
    </section>
  );
}
