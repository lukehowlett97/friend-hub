import React, { useEffect, useState, useCallback } from 'react';
import { apiFetch } from '../api/client';
import './ArchivePage.css';

const TYPE_LABELS = {
  idea: 'Idea',
  poll: 'Poll',
  event: 'Event',
  reminder: 'Reminder',
};

const TYPE_ICONS = {
  idea: '!',
  poll: '%',
  event: '@',
  reminder: '^',
};

function fmtDate(iso) {
  if (!iso) return null;
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
}

function ArchivedItem({ item }) {
  return (
    <div className="archive-item">
      <span className="archive-item__icon" aria-hidden="true">
        {TYPE_ICONS[item.type] ?? '·'}
      </span>
      <div className="archive-item__body">
        <div className="archive-item__topline">
          <span className="archive-item__type">{TYPE_LABELS[item.type] ?? item.type}</span>
          <span className="archive-item__short-id">{item.short_id}</span>
        </div>
        <p className="archive-item__title">{item.title}</p>
        {item.body && <p className="archive-item__body-text">{item.body}</p>}
        <div className="archive-item__meta">
          {item.creator?.nickname && <span>By {item.creator.nickname}</span>}
          {fmtDate(item.created_at) && <span>Created {fmtDate(item.created_at)}</span>}
          {fmtDate(item.archived_at) && <span>Archived {fmtDate(item.archived_at)}</span>}
        </div>
      </div>
    </div>
  );
}

function DeletedPhoto({ photo }) {
  return (
    <div className="archive-photo">
      <div className="archive-photo__thumb">
        <span className="archive-photo__placeholder" aria-hidden="true">▧</span>
      </div>
      <div className="archive-photo__body">
        <p className="archive-photo__name">{photo.original_filename ?? photo.filename}</p>
        {photo.caption && <p className="archive-photo__caption">{photo.caption}</p>}
        <div className="archive-item__meta">
          {photo.uploaded_by && <span>By {photo.uploaded_by}</span>}
          {fmtDate(photo.created_at) && <span>Uploaded {fmtDate(photo.created_at)}</span>}
          {fmtDate(photo.deleted_at) && <span>Deleted {fmtDate(photo.deleted_at)}</span>}
        </div>
      </div>
    </div>
  );
}

const TABS = ['items', 'photos'];
const TYPE_FILTERS = ['all', 'idea', 'poll', 'event', 'reminder'];

export default function ArchivePage() {
  const [items, setItems] = useState([]);
  const [photos, setPhotos] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [tab, setTab] = useState('items');
  const [filter, setFilter] = useState('all');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await apiFetch('/api/v1/admin/archive');
      if (!res.ok) throw new Error(`Failed to load archive (${res.status})`);
      const data = await res.json();
      setItems(data.items || []);
      setPhotos(data.photos || []);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const filteredItems = filter === 'all' ? items : items.filter(i => i.type === filter);

  return (
    <section className="page archive-page">
      <header className="page-header">
        <h1>Archive</h1>
        <p className="page-subtitle">All deleted items and photos — admin view.</p>
      </header>

      <div className="archive-tabs">
        {TABS.map(t => (
          <button
            key={t}
            type="button"
            className={`archive-tab-btn${tab === t ? ' active' : ''}`}
            onClick={() => setTab(t)}
          >
            {t === 'items' ? `Items${items.length ? ` (${items.length})` : ''}` : `Photos${photos.length ? ` (${photos.length})` : ''}`}
          </button>
        ))}
      </div>

      {loading && <p className="archive-status">Loading…</p>}
      {error && <p className="archive-status archive-status--error">{error}</p>}

      {!loading && !error && tab === 'items' && (
        <>
          <div className="archive-filters">
            {TYPE_FILTERS.map(t => (
              <button
                key={t}
                type="button"
                className={`archive-filter-btn${filter === t ? ' active' : ''}`}
                onClick={() => setFilter(t)}
              >
                {t === 'all' ? 'All' : TYPE_LABELS[t]}
              </button>
            ))}
          </div>

          {filteredItems.length === 0 ? (
            <p className="archive-status">No archived items{filter !== 'all' ? ` of type "${TYPE_LABELS[filter]}"` : ''}.</p>
          ) : (
            <div className="archive-list">
              {filteredItems.map(item => (
                <ArchivedItem key={item.id} item={item} />
              ))}
            </div>
          )}
        </>
      )}

      {!loading && !error && tab === 'photos' && (
        <>
          {photos.length === 0 ? (
            <p className="archive-status">No deleted photos.</p>
          ) : (
            <div className="archive-photos-list">
              {photos.map(photo => (
                <DeletedPhoto key={photo.id} photo={photo} />
              ))}
            </div>
          )}
        </>
      )}
    </section>
  );
}
