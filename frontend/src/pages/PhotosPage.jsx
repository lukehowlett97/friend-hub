import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { apiFetch } from '../api/client.js';
import { fetchHomeAppearance, fetchPhotoMonths, fetchPhotos, fetchPhotoSenders, setHomeCoverPhoto, uploadPhoto } from '../services/api';
import PhotoModal from '../components/Photos/PhotoModal.jsx';
import './PhotosPage.css';

const PAGE_SIZE = 120;
const MEDIA_TYPES = {
  all: 'All media',
  photos: 'Photos',
  gifs: 'GIFs',
  videos: 'Videos',
  audio: 'Audio',
};

function groupByMonth(items) {
  const groups = [];
  const seen = new Map();
  for (const item of items) {
    const date = new Date(item.taken_at || item.created_at);
    const key = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`;
    const label = date.toLocaleDateString('en-GB', { month: 'long', year: 'numeric' });
    if (!seen.has(key)) {
      seen.set(key, { key, label, photos: [] });
      groups.push(seen.get(key));
    }
    seen.get(key).photos.push(item);
  }
  return groups;
}

function ActiveFilterPill({ label, onRemove }) {
  return (
    <span className="photos-filter-pill">
      {label}
      <button type="button" className="photos-filter-pill-remove" onClick={onRemove} aria-label={`Remove filter: ${label}`}>×</button>
    </span>
  );
}

function itemMatchesMonth(item, month) {
  if (!month) return true;
  const date = new Date(item.taken_at || item.created_at);
  if (Number.isNaN(date.getTime())) return false;
  const key = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`;
  return key === month;
}

function itemMatchesSearch(item, searchLower) {
  if (!searchLower) return true;
  return (
    (item.caption || '').toLowerCase().includes(searchLower) ||
    (item.original_filename || '').toLowerCase().includes(searchLower) ||
    (item.tags || []).some(t => t.toLowerCase().includes(searchLower)) ||
    (item.original_sender || '').toLowerCase().includes(searchLower) ||
    (item.uploaded_by || '').toLowerCase().includes(searchLower)
  );
}

const PhotosPage = () => {
  const [photos, setPhotos]           = useState([]);
  const [videos, setVideos]           = useState([]);
  const [audioFiles, setAudioFiles]   = useState([]);
  const [openVideo, setOpenVideo]     = useState(null);
  const [openAudio, setOpenAudio]     = useState(null);
  const [hasMore, setHasMore]         = useState(true);
  const [photoTotal, setPhotoTotal]   = useState(null);
  const [loading, setLoading]         = useState(false);
  const [error, setError]             = useState(null);
  const [openPhoto, setOpenPhoto]     = useState(null);
  const [hubCoverPhotoId, setHubCoverPhotoId] = useState(null);
  const [settingHubCoverId, setSettingHubCoverId] = useState(null);

  // Filters
  const [search, setSearch]           = useState('');
  const [activeTag, setActiveTag]     = useState('');
  const [activeSender, setActiveSender] = useState('');
  const [activeSource, setActiveSource] = useState('');
  const [activeMonth, setActiveMonth] = useState(''); // "YYYY-MM"
  const [mediaType, setMediaType]     = useState('all');
  const [sort, setSort]               = useState('newest');

  // Upload state
  const [pendingFile, setPendingFile] = useState(null);
  const [caption, setCaption]         = useState('');
  const [tagsInput, setTagsInput]     = useState('');
  const [isUploading, setIsUploading] = useState(false);
  const fileInputRef                  = useRef(null);

  const [hideGifs, setHideGifs]       = useState(false);
  const [allSenders, setAllSenders]   = useState([]);
  const [allMonths, setAllMonths]     = useState([]);

  // Selection state (bulk foundation)
  const [selectMode, setSelectMode]   = useState(false);
  const [selected, setSelected]       = useState(new Set());

  const offsetRef = useRef(0);

  // Build date filter from activeMonth
  const monthToDateRange = (month) => {
    if (!month) return { start_at: null, end_at: null };
    const [year, mon] = month.split('-').map(Number);
    const start = new Date(year, mon - 1, 1);
    const end = new Date(year, mon, 0); // last day of month
    return {
      start_at: start.toISOString().slice(0, 10),
      end_at: end.toISOString().slice(0, 10),
    };
  };

  const buildOpts = useCallback(() => {
    const opts = { sort };
    if (activeTag)    opts.tag        = activeTag;
    if (activeSender) opts.sender     = activeSender;
    if (activeSource) opts.source_type = activeSource;
    const { start_at, end_at } = monthToDateRange(activeMonth);
    if (start_at) opts.start_at = start_at;
    if (end_at)   opts.end_at   = end_at;
    return opts;
  }, [activeTag, activeSender, activeSource, activeMonth, sort]);

  const loadPage = useCallback(async (reset = false) => {
    if (loading) return;
    setLoading(true);
    setError(null);
    const offset = reset ? 0 : offsetRef.current;
    try {
      const opts = buildOpts();
      opts.offset = offset;
      const [photoData, videoData, audioData] = await Promise.all([
        fetchPhotos(PAGE_SIZE, opts),
        reset ? apiFetch('/api/v1/videos?limit=200').then(r => r.ok ? r.json() : { videos: [] }) : Promise.resolve(null),
        reset ? apiFetch('/api/v1/audio?limit=200').then(r => r.ok ? r.json() : { audio: [] }) : Promise.resolve(null),
      ]);
      const incoming = photoData.photos || [];
      const nextOffset = offset + incoming.length;
      const nextTotal = typeof photoData.total === 'number' ? photoData.total : null;
      setPhotoTotal(nextTotal);
      setPhotos(prev => {
        if (reset) return incoming;
        // Offsets can shift if photos are added/removed between page fetches
        const seen = new Set(prev.map(p => p.id));
        return [...prev, ...incoming.filter(p => !seen.has(p.id))];
      });
      offsetRef.current = nextOffset;
      setHasMore(nextTotal !== null ? nextOffset < nextTotal : incoming.length === PAGE_SIZE);
      if (reset) {
        // Normalise videos to share the same tile interface as photos
        const incomingVideos = (videoData?.videos || []).map(v => ({
          ...v,
          _isVideo: true,
          _mediaType: 'video',
          thumbnail_url: v.thumbnail_url,
          url: v.url,
          caption: v.caption,
          original_filename: v.original_filename,
          taken_at: v.taken_at,
          source_type: v.source_type,
        }));
        setVideos(incomingVideos);
        const incomingAudio = (audioData?.audio || []).map(a => ({
          ...a,
          _isAudio: true,
          _mediaType: 'audio',
          url: a.url,
          caption: a.caption,
          original_filename: a.original_filename,
          taken_at: a.taken_at,
          source_type: a.source_type,
        }));
        setAudioFiles(incomingAudio);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [buildOpts, loading]);

  // Reset and reload whenever filters change
  useEffect(() => {
    offsetRef.current = 0;
    setPhotos([]);
    setPhotoTotal(null);
    setHasMore(true);
    setSelected(new Set());
    loadPage(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTag, activeSender, activeSource, activeMonth, mediaType, sort]);

  const shouldAutoLoadPhotos = ['all', 'photos', 'gifs'].includes(mediaType);

  // Load the next page whenever the sentinel under the grid approaches the
  // viewport; stop auto-loading after an error so we don't hammer the server.
  const sentinelRef = useRef(null);
  useEffect(() => {
    const el = sentinelRef.current;
    if (!el || !shouldAutoLoadPhotos || loading || !hasMore || error || photos.length === 0) return undefined;
    const observer = new IntersectionObserver(
      entries => { if (entries.some(entry => entry.isIntersecting)) loadPage(false); },
      { rootMargin: '1500px 0px' },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [shouldAutoLoadPhotos, loading, hasMore, error, photos.length, loadPage]);

  // Full month list for the current filters, so the picker can jump to months
  // that haven't been scrolled into view yet
  useEffect(() => {
    fetchPhotoMonths({ tag: activeTag, sender: activeSender, source_type: activeSource })
      .then(data => setAllMonths(data?.months || []))
      .catch(() => setAllMonths([]));
  }, [activeTag, activeSender, activeSource]);

  useEffect(() => {
    fetchHomeAppearance()
      .then(data => setHubCoverPhotoId(data?.cover_photo_id ?? null))
      .catch(() => {});
    fetchPhotoSenders()
      .then(data => setAllSenders(data?.senders || []))
      .catch(() => {});
  }, []);

  const handleSetHubCover = async (photoId) => {
    if (!photoId || settingHubCoverId === photoId) return;
    setSettingHubCoverId(photoId);
    setError(null);
    try {
      const next = await setHomeCoverPhoto(photoId);
      setHubCoverPhotoId(next?.cover_photo_id ?? photoId);
      setOpenPhoto(cur => cur ? { ...cur, isCurrentHubCover: true } : cur);
    } catch (err) {
      setError(err.message);
    } finally {
      setSettingHubCoverId(null);
    }
  };

  const handleFileSelect = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setPendingFile({ file, preview: URL.createObjectURL(file) });
    setCaption('');
    setTagsInput('');
    e.target.value = '';
  };

  const handleUpload = async (e) => {
    e.preventDefault();
    if (!pendingFile) return;
    setIsUploading(true);
    setError(null);
    try {
      const tags = tagsInput.split(',').map(t => t.trim().toLowerCase()).filter(Boolean);
      await uploadPhoto(pendingFile.file, { caption: caption.trim() || null, tags });
      URL.revokeObjectURL(pendingFile.preview);
      setPendingFile(null);
      offsetRef.current = 0;
      loadPage(true);
    } catch (err) {
      setError(err.message);
    } finally {
      setIsUploading(false);
    }
  };

  const cancelUpload = () => {
    if (pendingFile) URL.revokeObjectURL(pendingFile.preview);
    setPendingFile(null);
  };

  // client-side search filter (title/caption match)
  const searchLower = search.trim().toLowerCase();
  const visiblePhotos = photos.filter(p => {
    const isGif = p.content_type === 'image/gif';
    if (mediaType === 'videos' || mediaType === 'audio') return false;
    if (mediaType === 'photos' && isGif) return false;
    if (mediaType === 'gifs' && !isGif) return false;
    if (hideGifs && mediaType === 'all' && isGif) return false;
    return itemMatchesSearch(p, searchLower);
  });

  const visibleVideos = videos.filter(v => {
    if (mediaType !== 'all' && mediaType !== 'videos') return false;
    if (activeSource && v.source_type !== activeSource) return false;
    if (!itemMatchesMonth(v, activeMonth)) return false;
    return itemMatchesSearch(v, searchLower);
  });

  const visibleAudio = audioFiles.filter(a => {
    if (mediaType !== 'all' && mediaType !== 'audio') return false;
    if (activeSource && a.source_type !== activeSource) return false;
    if (!itemMatchesMonth(a, activeMonth)) return false;
    return itemMatchesSearch(a, searchLower);
  });

  const availableTags = useMemo(
    () => [...new Set(photos.flatMap(p => p.tags || []))].sort(),
    [photos],
  );

  // Prefer the server's full sender list; fall back to senders seen in loaded pages
  const availableSenders = useMemo(() => {
    if (allSenders.length > 0) return allSenders;
    return [...new Set(photos.map(p => p.original_sender || p.uploaded_by).filter(Boolean))].sort();
  }, [allSenders, photos]);

  // Merge and sort by date for unified timeline
  const allMedia = [...visiblePhotos, ...visibleVideos, ...visibleAudio].sort((a, b) => {
    const da = new Date(a.taken_at || a.created_at);
    const db = new Date(b.taken_at || b.created_at);
    return sort === 'oldest' ? da - db : db - da;
  });

  const monthGroups = groupByMonth(allMedia);

  // Months for the jump picker: prefer the server's full list, fall back to
  // months seen in loaded media
  const loadedMonths = [...new Set([
    ...allMonths,
    ...[...photos, ...videos, ...audioFiles].map(item => {
      const d = new Date(item.taken_at || item.created_at);
      if (Number.isNaN(d.getTime())) return null;
      return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
    }).filter(Boolean),
  ])].sort((a, b) => sort === 'oldest' ? a.localeCompare(b) : b.localeCompare(a));

  const toggleSelect = (id) => {
    setSelected(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const handleTileClick = (photo) => {
    if (selectMode) {
      toggleSelect(photo.id);
      return;
    }
    setOpenPhoto({
      id: photo.id,
      url: photo.url,
      thumbnail_url: photo.thumbnail_url,
      label: photo.caption || photo.original_filename,
      caption: photo.caption,
      tags: photo.tags,
      message_id: photo.message_id,
      source_type: photo.source_type,
      taken_at: photo.taken_at,
      created_at: photo.created_at,
      uploaded_by: photo.uploaded_by,
      original_sender: photo.original_sender,
      isCurrentHubCover: hubCoverPhotoId === photo.id,
    });
  };

  const activeFilterCount = [activeTag, activeSender, activeSource, activeMonth, mediaType !== 'all' ? mediaType : ''].filter(Boolean).length;

  return (
    <section className="photos-page">
      {/* Sticky controls */}
      <div className="photos-controls">
        <div className="photos-search-row">
          <input
            type="search"
            className="photos-search-input"
            placeholder="Search media…"
            value={search}
            onChange={e => setSearch(e.target.value)}
            aria-label="Search photos"
          />
          <button
            type="button"
            className={`photos-upload-fab${pendingFile ? ' hidden' : ''}`}
            onClick={() => fileInputRef.current?.click()}
            aria-label="Upload photo"
            title="Upload photo"
          >＋</button>
          <input ref={fileInputRef} type="file" accept="image/*" style={{ display: 'none' }} onChange={handleFileSelect} />
        </div>

        <div className="photos-filter-row">
          <select
            className="photos-filter-select"
            value={mediaType}
            onChange={e => setMediaType(e.target.value)}
            aria-label="Filter by media type"
          >
            {Object.entries(MEDIA_TYPES).map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>

          <select
            className="photos-filter-select"
            value={activeSender}
            onChange={e => setActiveSender(e.target.value)}
            aria-label="Filter by sender"
          >
            <option value="">Sender</option>
            {availableSenders.map(s => <option key={s} value={s}>{s}</option>)}
          </select>

          <select
            className="photos-filter-select"
            value={activeMonth}
            onChange={e => setActiveMonth(e.target.value)}
            aria-label="Filter by month"
          >
            <option value="">Month</option>
            {loadedMonths.map(m => {
              const [y, mo] = m.split('-').map(Number);
              const label = new Date(y, mo - 1).toLocaleDateString('en-GB', { month: 'short', year: 'numeric' });
              return <option key={m} value={m}>{label}</option>;
            })}
          </select>

          <select
            className="photos-filter-select"
            value={activeTag}
            onChange={e => setActiveTag(e.target.value)}
            aria-label="Filter by tag"
          >
            <option value="">Tag</option>
            {availableTags.map(t => <option key={t} value={t}>#{t}</option>)}
          </select>

          <select
            className="photos-filter-select"
            value={activeSource}
            onChange={e => setActiveSource(e.target.value)}
            aria-label="Filter by source"
          >
            <option value="">Source</option>
            <option value="manual_upload">Uploaded</option>
            <option value="messenger_import">Messenger</option>
          </select>

          <select
            className="photos-filter-select"
            value={sort}
            onChange={e => setSort(e.target.value)}
            aria-label="Sort photos"
          >
            <option value="newest">Newest first</option>
            <option value="oldest">Oldest first</option>
            <option value="uploaded">Recently uploaded</option>
          </select>

          <label className="photos-filter-toggle">
            <input
              type="checkbox"
              checked={hideGifs}
              onChange={e => setHideGifs(e.target.checked)}
            />
            Hide GIFs
          </label>
        </div>

        {activeFilterCount > 0 && (
          <div className="photos-active-filters">
            {activeTag     && <ActiveFilterPill label={`#${activeTag}`}  onRemove={() => setActiveTag('')} />}
            {mediaType !== 'all' && <ActiveFilterPill label={MEDIA_TYPES[mediaType]} onRemove={() => setMediaType('all')} />}
            {activeSender  && <ActiveFilterPill label={activeSender}      onRemove={() => setActiveSender('')} />}
            {activeSource  && <ActiveFilterPill label={activeSource === 'messenger_import' ? 'Messenger' : 'Uploaded'} onRemove={() => setActiveSource('')} />}
            {activeMonth   && (() => {
              const [y, mo] = activeMonth.split('-').map(Number);
              const label = new Date(y, mo - 1).toLocaleDateString('en-GB', { month: 'short', year: 'numeric' });
              return <ActiveFilterPill label={label} onRemove={() => setActiveMonth('')} />;
            })()}
            <button type="button" className="photos-clear-all" onClick={() => { setActiveTag(''); setActiveSender(''); setActiveSource(''); setActiveMonth(''); setMediaType('all'); }}>
              Clear all
            </button>
          </div>
        )}
      </div>

      {/* Upload form */}
      {pendingFile && (
        <div className="photos-upload-drawer">
          <form className="photos-upload-form" onSubmit={handleUpload}>
            <img className="photos-upload-preview" src={pendingFile.preview} alt="Preview" />
            <div className="photos-upload-fields">
              <input
                className="photos-upload-caption"
                type="text"
                value={caption}
                onChange={e => setCaption(e.target.value)}
                placeholder="Add a caption…"
                maxLength={500}
                autoFocus
              />
              <input
                className="photos-upload-tags"
                type="text"
                value={tagsInput}
                onChange={e => setTagsInput(e.target.value)}
                placeholder="Tags — comma separated"
              />
              {availableTags.length > 0 && (
                <div className="photos-upload-tag-suggestions">
                  {availableTags.slice(0, 8).map(tag => (
                    <button
                      key={tag} type="button"
                      className="photos-upload-tag-suggestion-chip"
                      onClick={() => {
                        const cur = tagsInput.split(',').map(t => t.trim().toLowerCase()).filter(Boolean);
                        if (!cur.includes(tag.toLowerCase())) {
                          setTagsInput(cur.length ? `${tagsInput}, ${tag}` : tag);
                        }
                      }}
                    >#{tag}</button>
                  ))}
                </div>
              )}
              <div className="photos-upload-actions">
                <button type="submit" className="photos-upload-submit" disabled={isUploading}>
                  {isUploading ? 'Uploading…' : 'Upload'}
                </button>
                <button type="button" className="photos-upload-cancel" onClick={cancelUpload}>Cancel</button>
              </div>
            </div>
          </form>
        </div>
      )}

      {error && <div className="photos-error">{error}</div>}

      {photoTotal !== null && (
        <div className="photos-result-count">
          {photos.length.toLocaleString()} of {photoTotal.toLocaleString()} photos and GIFs loaded
        </div>
      )}

      {/* Select mode bar */}
      {selectMode && (
        <div className="photos-select-bar">
          <span>{selected.size} selected</span>
          <button type="button" onClick={() => { setSelectMode(false); setSelected(new Set()); }}>Cancel</button>
          {/* TODO: add batch actions (tag/archive) when backend endpoints are added */}
        </div>
      )}

      {/* Month-grouped grid */}
      <div className="photos-grid-area">
        {monthGroups.length === 0 && !loading && (
          <div className="photos-empty">No media yet</div>
        )}

        {monthGroups.map(group => (
          <section key={group.key} className="photos-month-group" id={`month-${group.key}`}>
            <h2 className="photos-month-heading">
              {group.label}
              <span className="photos-month-count">{group.photos.length}</span>
            </h2>
            <div className="photos-grid">
              {group.photos.map(item => item._isVideo ? (
                <button
                  key={`v-${item.id}`}
                  type="button"
                  className="photos-tile photos-tile--video"
                  onClick={() => setOpenVideo(item)}
                  aria-label={item.caption || item.original_filename || 'Video'}
                >
                  {item.thumbnail_url ? (
                    <img src={item.thumbnail_url} alt={item.caption || ''} loading="lazy" decoding="async" />
                  ) : (
                    <div className="photos-tile-video-placeholder" />
                  )}
                  <span className="photos-tile-play" aria-hidden="true">▶</span>
                  {item.source_type === 'messenger_import' && (
                    <span className="photos-tile-badge" title="Messenger">💬</span>
                  )}
                </button>
              ) : item._isAudio ? (
                <button
                  key={`a-${item.id}`}
                  type="button"
                  className="photos-tile photos-tile--audio"
                  onClick={() => setOpenAudio(item)}
                  aria-label={item.caption || item.original_filename || 'Audio'}
                >
                  <span className="photos-tile-audio-icon" aria-hidden="true">♫</span>
                  <span className="photos-tile-audio-name">{item.caption || item.original_filename || 'Audio'}</span>
                  {item.source_type === 'messenger_import' && (
                    <span className="photos-tile-badge" title="Messenger">💬</span>
                  )}
                </button>
              ) : (
                <button
                  key={`p-${item.id}`}
                  type="button"
                  className={`photos-tile${selected.has(item.id) ? ' selected' : ''}`}
                  onClick={() => handleTileClick(item)}
                  onContextMenu={e => { e.preventDefault(); setSelectMode(true); toggleSelect(item.id); }}
                  aria-label={item.caption || item.original_filename || 'Photo'}
                >
                  <img
                    src={item.thumbnail_url || item.url}
                    alt={item.caption || item.original_filename || ''}
                    loading="lazy"
                    decoding="async"
                  />
                  {selected.has(item.id) && (
                    <span className="photos-tile-check" aria-hidden="true">✓</span>
                  )}
                  {item.source_type === 'messenger_import' && (
                    <span className="photos-tile-badge" aria-label="Messenger import" title="Messenger">💬</span>
                  )}
                </button>
              ))}
            </div>
          </section>
        ))}

        <div ref={sentinelRef} className="photos-scroll-sentinel" aria-hidden="true" />

        {loading && <div className="photos-loading">Loading…</div>}

        {!loading && hasMore && ['all', 'photos', 'gifs'].includes(mediaType) && visiblePhotos.length > 0 && (
          <button type="button" className="photos-load-more" onClick={() => loadPage(false)}>
            Load more
          </button>
        )}
      </div>

      <PhotoModal
        photo={openPhoto ? {
          ...openPhoto,
          isSettingHubCover: settingHubCoverId === openPhoto.id,
          isCurrentHubCover: hubCoverPhotoId === openPhoto.id,
          onSetAsHubCover: () => handleSetHubCover(openPhoto.id),
        } : null}
        onClose={() => setOpenPhoto(null)}
      />

      {openVideo && (
        <div className="video-modal-overlay" onClick={() => setOpenVideo(null)} role="dialog" aria-modal="true">
          <div className="video-modal-inner" onClick={e => e.stopPropagation()}>
            <button className="video-modal-close" onClick={() => setOpenVideo(null)} aria-label="Close">×</button>
            <video
              controls
              autoPlay
              preload="auto"
              poster={openVideo.thumbnail_url || undefined}
              className="video-modal-player"
            >
              <source src={openVideo.url} />
            </video>
            {(openVideo.caption || openVideo.original_filename) && (
              <p className="video-modal-caption">{openVideo.caption || openVideo.original_filename}</p>
            )}
          </div>
        </div>
      )}

      {openAudio && (
        <div className="video-modal-overlay" onClick={() => setOpenAudio(null)} role="dialog" aria-modal="true">
          <div className="video-modal-inner" onClick={e => e.stopPropagation()}>
            <button className="video-modal-close" onClick={() => setOpenAudio(null)} aria-label="Close">×</button>
            <div className="audio-modal-card">
              <span className="audio-modal-icon" aria-hidden="true">♫</span>
              <p className="video-modal-caption">{openAudio.caption || openAudio.original_filename}</p>
              <audio controls autoPlay className="audio-modal-player">
                <source src={openAudio.url} />
              </audio>
            </div>
          </div>
        </div>
      )}
    </section>
  );
};

export default PhotosPage;
