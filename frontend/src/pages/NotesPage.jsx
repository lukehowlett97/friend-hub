import React, { useEffect, useMemo, useState } from 'react';
import NoteCard from '../components/Notes/NoteCard.jsx';
import NoteEditor from '../components/Notes/NoteEditor.jsx';
import { createNote, fetchNotes, pinNote, unpinNote } from '../services/api.js';
import './FeaturePages.css';

const EMPTY_FORM = { title: '', body: '', note_type: 'general', edit_mode: 'owner_only', is_pinned: false };
const NOTE_TYPES = ['all', 'general', 'idea', 'memory', 'story', 'plan', 'recommendation', 'rule'];

export default function NotesPage({ onNavigate }) {
  const [notes, setNotes] = useState([]);
  const [query, setQuery] = useState('');
  const [type, setType] = useState('all');
  const [sort, setSort] = useState('updated');
  const [form, setForm] = useState(EMPTY_FORM);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const loadNotes = () => {
    setLoading(true);
    fetchNotes({ q: query, note_type: type, sort, limit: 100 })
      .then((data) => { setNotes(data.notes || []); setError(null); })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    const timer = setTimeout(loadNotes, 150);
    return () => clearTimeout(timer);
  }, [query, type, sort]);

  const pinned = useMemo(() => notes.filter((note) => note.pinned_to_home), [notes]);
  const unpinned = useMemo(() => notes.filter((note) => !note.pinned_to_home), [notes]);
  const visibleNotes = [...pinned, ...unpinned];

  const submitNote = async (event) => {
    event.preventDefault();
    try {
      const result = await createNote(form);
      setForm(EMPTY_FORM);
      onNavigate?.(`/notes/${result.note.id}`);
    } catch (err) {
      setError(err.message);
    }
  };

  const togglePin = async (note) => {
    try {
      if (note.pinned_to_home) await unpinNote(note.id);
      else await pinNote(note.id);
      loadNotes();
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <section className="page feature-page notes-page">
      <header className="page-header">
        <h1>Notes</h1>
        <p className="page-subtitle">Shared text for ideas, memories, plans, recommendations, and rules.</p>
      </header>

      <NoteEditor form={form} setForm={setForm} onSubmit={submitNote} submitLabel="Add Note" compact />

      {error && <div className="inline-error">{error}</div>}

      <div className="filter-tabs note-filter-tabs">
        <input
          className="note-search-input"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search notes"
        />
        <select value={type} onChange={(event) => setType(event.target.value)}>
          {NOTE_TYPES.map((item) => <option key={item} value={item}>{item}</option>)}
        </select>
        <select value={sort} onChange={(event) => setSort(event.target.value)}>
          <option value="updated">recently updated</option>
          <option value="created">recently created</option>
        </select>
      </div>

      {loading && <div className="inline-notice">Loading...</div>}

      <div className="feature-list">
        {visibleNotes.map((note) => (
          <NoteCard
            key={note.id}
            note={note}
            onOpen={(item) => onNavigate?.(`/notes/${item.id}`)}
            onPin={togglePin}
          />
        ))}
        {!loading && visibleNotes.length === 0 && <div className="placeholder-panel compact">No notes yet.</div>}
      </div>
    </section>
  );
}

