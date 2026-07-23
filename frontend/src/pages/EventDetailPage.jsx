import React, { useEffect, useMemo, useRef, useState } from 'react';
import { format, parseISO } from 'date-fns';
import AddToCalendarButton from '../components/Planning/AddToCalendarButton.jsx';
import EngagementPanel from '../components/Planning/EngagementPanel.jsx';
import HubItemCardMeta from '../components/Planning/HubItemCardMeta.jsx';
import TagChipInput from '../components/TagChipInput.jsx';
import {
  createEventPost,
  deletePhoto,
  fetchEvents,
  fetchEventPosts,
  fetchPhotos,
  fetchMembers,
  pinHubItem,
  rsvpEvent,
  sendHubItemToChat,
  setPhotoCover,
  updateCoverPosition,
  updateEvent,
  updateEventInvites,
  updateHubItem,
  uploadPhoto,
} from '../services/api.js';
import { useAuth } from '../auth/AuthProvider.jsx';
import { openNativeDatePicker } from '../utils/nativeDatePicker.js';
import './FeaturePages.css';

const parseEventDate = (event) => (event?.starts_at ? parseISO(event.starts_at) : null);

const formatEventDate = (event) => {
  const date = parseEventDate(event);
  return date ? format(date, 'EEEE d MMMM yyyy, h:mm a') : 'Time TBC';
};

const EventTime = ({ event, className = 'eyebrow' }) => {
  const date = parseEventDate(event);
  return date ? (
    <time className={className} dateTime={date.toISOString()}>{formatEventDate(event)}</time>
  ) : (
    <span className={className}>Time TBC</span>
  );
};

const mapsUrl = (location) => `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(location)}`;

const parseTags = (value) => value
  .split(',')
  .map((tag) => tag.trim().replace(/^#/, ''))
  .filter(Boolean);

const RSVP_OPTIONS = [
  { key: 'yes', label: 'Yes', countKey: 'yes_count' },
  { key: 'maybe', label: 'Maybe', countKey: 'maybe_count' },
  { key: 'no', label: 'No', countKey: 'no_count' },
];

const rsvpVotersFor = (event, response) => (
  (event.rsvps || []).filter((rsvp) => rsvp.response === response)
);

const EventRsvpResults = ({ event, onOpenVoters }) => {
  const total = RSVP_OPTIONS.reduce((sum, option) => sum + (event[option.countKey] || 0), 0);

  return (
    <div className="event-rsvp-results-card">
      <div className="event-rsvp-results-header">
        <h3>Group response</h3>
        <span>{total} RSVP{total === 1 ? '' : 's'}</span>
      </div>
      <div className="event-rsvp-chart event-rsvp-chart--interactive" aria-label="RSVP vote distribution">
        {RSVP_OPTIONS.map((option) => {
          const count = event[option.countKey] || 0;
          const pct = total ? Math.round((count / total) * 100) : 0;
          const width = count > 0 ? Math.max(7, pct) : 0;
          return (
            <button
              key={option.key}
              type="button"
              className={`event-rsvp-bar event-rsvp-bar--${option.key}`}
              onClick={() => onOpenVoters(option.key)}
              aria-label={`Show ${option.label} voters: ${count} RSVP${count === 1 ? '' : 's'}, ${pct}%`}
            >
              <span className="event-rsvp-bar__label">{option.label}</span>
              <span className="event-rsvp-bar__track" aria-hidden="true">
                <span style={{ width: `${width}%` }} />
              </span>
              <strong>{count}</strong>
              <em>{pct}%</em>
            </button>
          );
        })}
      </div>
    </div>
  );
};

const EventRsvpVoterSheet = ({ event, response, onClose }) => {
  if (!response) return null;

  const option = RSVP_OPTIONS.find((item) => item.key === response);
  const voters = rsvpVotersFor(event, response);

  return (
    <div className="event-rsvp-sheet-backdrop" role="presentation" onClick={onClose}>
      <section
        className="event-rsvp-sheet"
        role="dialog"
        aria-modal="true"
        aria-labelledby="event-rsvp-sheet-title"
        onClick={(clickEvent) => clickEvent.stopPropagation()}
      >
        <div className="event-rsvp-sheet__header">
          <div>
            <h3 id="event-rsvp-sheet-title">{option?.label || 'RSVP'} voters</h3>
            <p>{voters.length ? `${voters.length} friend${voters.length === 1 ? '' : 's'}` : 'No one yet'}</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close RSVP voter list">×</button>
        </div>

        {voters.length > 0 ? (
          <div className="event-rsvp-voter-list event-rsvp-voter-list--sheet">
            {voters.map(({ user }) => (
              <span
                key={user?.id || user?.username || user?.nickname}
                className="event-rsvp-voter"
              >
                {user?.avatar_url ? <img src={user.avatar_url} alt="" /> : <span>{(user?.nickname || '?')[0].toUpperCase()}</span>}
                <em>{user?.nickname || 'Friend'}</em>
              </span>
            ))}
          </div>
        ) : (
          <div className="event-rsvp-empty-state">No one yet</div>
        )}
      </section>
    </div>
  );
};

const EventSection = ({ title, action, children, className = '' }) => (
  <section className={`event-detail-section event-detail-section-card${className ? ` ${className}` : ''}`}>
    <div className="event-detail-section-heading">
      <h2>{title}</h2>
      {action}
    </div>
    {children}
  </section>
);

const EmptyEventState = ({ children }) => (
  <div className="event-empty-state">
    <span aria-hidden="true">+</span>
    <p>{children}</p>
  </div>
);

const currentUserRsvp = (event, user) => (
  event.rsvps?.find((rsvp) => rsvp.user?.id === user?.id)?.response || null
);

const rsvpSummaryText = (event) => {
  const yes = event.yes_count || 0;
  const maybe = event.maybe_count || 0;
  const no = event.no_count || 0;
  const top = [...RSVP_OPTIONS]
    .sort((a, b) => (event[b.countKey] || 0) - (event[a.countKey] || 0))[0];
  if (!yes && !maybe && !no) return 'No RSVPs yet';
  return `${top.label} is leading · ${yes} yes · ${maybe} maybe · ${no} no`;
};

const EventHeaderMeta = ({ event }) => (
  <div className="event-detail-meta-grid">
    <div>
      <span>Date</span>
      <strong><EventTime event={event} className="event-detail-meta-time" /></strong>
    </div>
    {event.location && (
      <div>
        <span>Location</span>
        <a className="event-detail-location" href={mapsUrl(event.location)} target="_blank" rel="noreferrer">
          {event.location}
        </a>
      </div>
    )}
  </div>
);

const EventDetailPage = ({ eventId, onNavigate }) => {
  const { user: currentUser } = useAuth();
  const [events, setEvents] = useState([]);
  const [posts, setPosts] = useState([]);
  const [photos, setPhotos] = useState([]);
  const [members, setMembers] = useState([]);
  const [error, setError] = useState(null);
  const [tagText, setTagText] = useState('');
  const [postText, setPostText] = useState('');
  const [eventForm, setEventForm] = useState({ title: '', starts_at: '', location: '', cover_photo_url: '', photo_tag_id: '', description: '', reference_tag: '' });
  const [inviteIds, setInviteIds] = useState([]);
  const [isEditing, setIsEditing] = useState(false);
  const [isSavingEvent, setIsSavingEvent] = useState(false);
  const [isSavingTags, setIsSavingTags] = useState(false);
  const [isPosting, setIsPosting] = useState(false);
  const [isUploadingPhoto, setIsUploadingPhoto] = useState(false);
  const [pendingEventPhoto, setPendingEventPhoto] = useState(null); // { file, preview }
  const [eventPhotoCaption, setEventPhotoCaption] = useState('');
  const [eventPhotoTags, setEventPhotoTags] = useState('');
  const [activeRsvpVoters, setActiveRsvpVoters] = useState(null);
  const [photoToDelete, setPhotoToDelete] = useState(null);
  const [isDeletingPhoto, setIsDeletingPhoto] = useState(false);
  const [isRepositioningCover, setIsRepositioningCover] = useState(false);
  const [coverPosition, setCoverPosition] = useState({ x: 50, y: 50 });
  const [isSavingCoverPosition, setIsSavingCoverPosition] = useState(false);
  const coverDragRef = useRef(null);
  const [coverPickerOpen, setCoverPickerOpen] = useState(false);
  const [coverPickerMode, setCoverPickerMode] = useState('event'); // 'event' | 'all'
  const [allPhotos, setAllPhotos] = useState([]);
  const [isUploadingCover, setIsUploadingCover] = useState(false);
  const [isApplyingCover, setIsApplyingCover] = useState(false);
  const coverFileInputRef = useRef(null);

  const loadEvents = () => {
    fetchEvents()
      .then((data) => {
        setEvents(data.events || []);
        setError(null);
      })
      .catch((err) => setError(err.message));
  };

  const loadPosts = () => {
    fetchEventPosts(eventId)
      .then((data) => {
        setPosts(data.posts || []);
        setError(null);
      })
      .catch((err) => setError(err.message));
  };

  const loadPhotos = () => {
    fetchPhotos(30, { event_id: eventId })
      .then((data) => {
        setPhotos(data.photos || []);
        setError(null);
      })
      .catch((err) => setError(err.message));
  };

  useEffect(() => {
    loadEvents();
    loadPosts();
    loadPhotos();
    fetchMembers().then((data) => setMembers(data.members || [])).catch(() => setMembers([]));
  }, [eventId]);

  const event = useMemo(
    () => events.find((item) => item.id === eventId),
    [events, eventId],
  );

  useEffect(() => {
    setTagText((event?.hub_item?.tags || []).join(', '));
    setInviteIds((event?.invites || []).map((member) => member.id));
    if (event) {
      const date = parseEventDate(event);
      setEventForm({
        title: event.title || '',
        starts_at: date ? new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16) : '',
        location: event.location || '',
        cover_photo_url: event.cover_photo_url || '',
        photo_tag_id: event.photo_tag_id || event.hub_item?.short_id || '',
        description: event.description || '',
        reference_tag: (event.hub_item?.short_id || event.short_id || '').replace(/^#+/, ''),
      });
      if (!isRepositioningCover) {
        setCoverPosition({
          x: typeof event.cover_photo_position_x === 'number' ? event.cover_photo_position_x : 50,
          y: typeof event.cover_photo_position_y === 'number' ? event.cover_photo_position_y : 50,
        });
      }
    }
  }, [event?.id, event?.hub_item?.id, event?.cover_photo_position_x, event?.cover_photo_position_y, isRepositioningCover]);

  const isAdmin = currentUser?.role === 'owner' || currentUser?.role === 'admin';
  const isCreator = !!event && event.creator?.id === currentUser?.id;
  const canEdit = !!event && (isAdmin || isCreator);
  const hasCover = !!event?.cover_photo_url;
  const canSetCover = !!event && !!currentUser && (!hasCover || canEdit);

  const canDeletePhoto = (photo) => {
    if (!currentUser) return false;
    if (isAdmin) return true;
    if (isCreator) return true;
    if (photo?.uploaded_by_session_id && photo.uploaded_by_session_id === currentUser.session_id) return true;
    return false;
  };

  const handleRsvp = async (response) => {
    try {
      await rsvpEvent(eventId, response);
      loadEvents();
    } catch (err) {
      setError(err.message);
    }
  };

  const togglePin = async (item) => {
    try {
      await pinHubItem(item.id, !item.pinned_to_home);
      loadEvents();
    } catch (err) {
      setError(err.message);
    }
  };

  const sendToChat = async (item) => {
    await sendHubItemToChat(item.id);
    loadEvents();
  };

  const prepareChatMessage = (item) => {
    onNavigate(`/chat?draft=${encodeURIComponent(item.short_id || '')}`);
  };

  const saveTags = async (submitEvent) => {
    submitEvent.preventDefault();
    if (!event?.hub_item?.id) return;
    setIsSavingTags(true);
    try {
      await updateHubItem(event.hub_item.id, { tags: parseTags(tagText) });
      loadEvents();
    } catch (err) {
      setError(err.message);
    } finally {
      setIsSavingTags(false);
    }
  };

  const saveEvent = async (submitEvent) => {
    submitEvent.preventDefault();
    setIsSavingEvent(true);
    try {
      // Strip reference_tag (lives on hub_item) and cover_photo_url (managed
      // via the cover picker / setPhotoCover) before sending.
      const { reference_tag: nextReferenceTag, cover_photo_url: _ignoredCover, ...eventPayload } = eventForm;
      await updateEvent(eventId, {
        ...eventPayload,
        starts_at: new Date(eventPayload.starts_at).toISOString(),
      });
      await updateEventInvites(eventId, inviteIds);
      const currentShortIdBody = (event?.hub_item?.short_id || '').replace(/^#+/, '');
      if (event?.hub_item?.id && nextReferenceTag && nextReferenceTag !== currentShortIdBody) {
        await updateHubItem(event.hub_item.id, { short_id: `#${nextReferenceTag}` });
      }
      loadEvents();
      setIsEditing(false);
    } catch (err) {
      setError(err.message);
    } finally {
      setIsSavingEvent(false);
    }
  };

  const handlePhotoFileSelect = (inputEvent) => {
    const file = inputEvent.target.files?.[0];
    inputEvent.target.value = '';
    if (!file || !event) return;
    const eventTag = event.photo_tag_id || event.hub_item?.short_id || '';
    setPendingEventPhoto({ file, preview: URL.createObjectURL(file) });
    setEventPhotoCaption('');
    setEventPhotoTags(eventTag);
  };

  const submitEventPhoto = async (e) => {
    e.preventDefault();
    if (!pendingEventPhoto) return;
    setIsUploadingPhoto(true);
    try {
      const tags = eventPhotoTags.split(',').map(t => t.trim().toLowerCase().replace(/^#/, '')).filter(Boolean);
      const result = await uploadPhoto(pendingEventPhoto.file, {
        caption: eventPhotoCaption.trim() || null,
        tags,
        event_id: eventId,
      });
      URL.revokeObjectURL(pendingEventPhoto.preview);
      setPendingEventPhoto(null);
      if (!event.cover_photo_url && result.photo?.id) {
        try {
          await setPhotoCover(result.photo.id);
          loadEvents();
        } catch (coverErr) {
          // Cover-set failed (e.g. another upload won the race) — surface but
          // don't fail the upload itself; the photo is already saved.
          setError(coverErr.message);
        }
      }
      loadPhotos();
    } catch (err) {
      setError(err.message);
    } finally {
      setIsUploadingPhoto(false);
    }
  };

  const cancelEventPhoto = () => {
    if (pendingEventPhoto) URL.revokeObjectURL(pendingEventPhoto.preview);
    setPendingEventPhoto(null);
  };

  const addEventPhotoTag = (tag) => {
    const current = eventPhotoTags.split(',').map(t => t.trim().toLowerCase().replace(/^#/, '')).filter(Boolean);
    if (!current.includes(tag.toLowerCase().replace(/^#/, ''))) {
      setEventPhotoTags(current.length ? `${eventPhotoTags}, ${tag}` : tag);
    }
  };

  const usePhotoAsCover = async (photo) => {
    try {
      await setPhotoCover(photo.id);
      loadEvents();
    } catch (err) {
      setError(err.message);
    }
  };

  const loadAllPhotos = async () => {
    try {
      const data = await fetchPhotos(60);
      setAllPhotos(data.photos || []);
    } catch (err) {
      setError(err.message);
    }
  };

  const openCoverPicker = () => {
    setCoverPickerOpen(true);
    setCoverPickerMode('event');
  };

  const switchCoverPickerMode = (mode) => {
    setCoverPickerMode(mode);
    if (mode === 'all' && allPhotos.length === 0) loadAllPhotos();
  };

  const applyCover = async (photo) => {
    if (!photo?.id) return;
    setIsApplyingCover(true);
    try {
      await setPhotoCover(photo.id);
      setCoverPickerOpen(false);
      loadEvents();
    } catch (err) {
      setError(err.message);
    } finally {
      setIsApplyingCover(false);
    }
  };

  const handleCoverFileSelect = async (inputEvent) => {
    const file = inputEvent.target.files?.[0];
    inputEvent.target.value = '';
    if (!file) return;
    const eventTag = event?.photo_tag_id || event?.hub_item?.short_id || '';
    setIsUploadingCover(true);
    try {
      const uploaded = await uploadPhoto(file, {
        tags: eventTag ? [eventTag.replace(/^#/, '')] : [],
        event_id: eventId,
      });
      if (uploaded?.photo?.id) {
        await setPhotoCover(uploaded.photo.id);
        setCoverPickerOpen(false);
        loadEvents();
        loadPhotos();
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setIsUploadingCover(false);
    }
  };

  const removeCover = async () => {
    try {
      await updateEvent(eventId, { cover_photo_url: '' });
      loadEvents();
    } catch (err) {
      setError(err.message);
    }
  };

  const startCoverReposition = () => {
    setCoverPosition({
      x: typeof event?.cover_photo_position_x === 'number' ? event.cover_photo_position_x : 50,
      y: typeof event?.cover_photo_position_y === 'number' ? event.cover_photo_position_y : 50,
    });
    setIsRepositioningCover(true);
  };

  const cancelCoverReposition = () => {
    setIsRepositioningCover(false);
    setCoverPosition({
      x: typeof event?.cover_photo_position_x === 'number' ? event.cover_photo_position_x : 50,
      y: typeof event?.cover_photo_position_y === 'number' ? event.cover_photo_position_y : 50,
    });
  };

  const saveCoverReposition = async () => {
    if (!event?.hub_item?.id) return;
    setIsSavingCoverPosition(true);
    try {
      await updateCoverPosition(event.hub_item.id, coverPosition.x, coverPosition.y);
      setIsRepositioningCover(false);
      loadEvents();
    } catch (err) {
      setError(err.message);
    } finally {
      setIsSavingCoverPosition(false);
    }
  };

  const handleCoverPointerDown = (downEvent) => {
    if (!isRepositioningCover) return;
    // Ignore pointer-downs on interactive controls inside the frame (Save /
    // Cancel) — otherwise preventDefault + pointer capture eats their click.
    if (downEvent.target?.closest?.('.event-cover-reposition-actions, button')) return;
    const container = coverDragRef.current;
    if (!container) return;
    downEvent.preventDefault();
    container.setPointerCapture?.(downEvent.pointerId);
    const startX = downEvent.clientX;
    const startY = downEvent.clientY;
    const startPosition = { ...coverPosition };
    const rect = container.getBoundingClientRect();
    const width = rect.width || 1;
    const height = rect.height || 1;

    const handleMove = (moveEvent) => {
      const deltaX = moveEvent.clientX - startX;
      const deltaY = moveEvent.clientY - startY;
      const nextX = Math.max(0, Math.min(100, startPosition.x - (deltaX / width) * 100));
      const nextY = Math.max(0, Math.min(100, startPosition.y - (deltaY / height) * 100));
      setCoverPosition({ x: Math.round(nextX), y: Math.round(nextY) });
    };

    const handleUp = (upEvent) => {
      container.releasePointerCapture?.(upEvent.pointerId);
      container.removeEventListener('pointermove', handleMove);
      container.removeEventListener('pointerup', handleUp);
      container.removeEventListener('pointercancel', handleUp);
    };

    container.addEventListener('pointermove', handleMove);
    container.addEventListener('pointerup', handleUp);
    container.addEventListener('pointercancel', handleUp);
  };

  const confirmDeletePhoto = async () => {
    if (!photoToDelete) return;
    setIsDeletingPhoto(true);
    try {
      await deletePhoto(photoToDelete.id);
      setPhotoToDelete(null);
      loadPhotos();
      loadEvents();
    } catch (err) {
      setError(err.message);
    } finally {
      setIsDeletingPhoto(false);
    }
  };

  const toggleInvite = (memberId, checked) => {
    setInviteIds((current) => (
      checked
        ? Array.from(new Set([...current, memberId]))
        : current.filter((id) => id !== memberId)
    ));
  };

  const createPost = async (submitEvent) => {
    submitEvent.preventDefault();
    if (!postText.trim()) return;
    setIsPosting(true);
    try {
      await createEventPost(eventId, postText);
      setPostText('');
      loadPosts();
    } catch (err) {
      setError(err.message);
    } finally {
      setIsPosting(false);
    }
  };

  if (!event && !error) {
    return (
      <section className="page feature-page">
        <button type="button" className="back-link-button" onClick={() => onNavigate('/events')}>Back to Events</button>
        <div className="placeholder-panel compact">Loading event...</div>
      </section>
    );
  }

  return (
    <section className="page feature-page event-detail-page">
      <button type="button" className="back-link-button" onClick={() => onNavigate('/events')}>Back to Events</button>

      {error && <div className="inline-error">{error}</div>}

      {event ? (
        <article className="event-detail-card">
          {event.cover_photo_url && (
            <div
              ref={coverDragRef}
              className={`event-cover-frame${isRepositioningCover ? ' is-repositioning' : ''}`}
              onPointerDown={handleCoverPointerDown}
            >
              <img
                className="event-cover-photo"
                src={event.cover_photo_url}
                alt=""
                draggable={false}
                style={{ objectPosition: `${coverPosition.x}% ${coverPosition.y}%` }}
              />
              {canEdit && !isRepositioningCover && (
                <button
                  type="button"
                  className="event-cover-reposition-btn"
                  onClick={startCoverReposition}
                >
                  Reposition
                </button>
              )}
              {isRepositioningCover && (
                <>
                  <span className="event-cover-reposition-hint">Drag to reposition</span>
                  <div className="event-cover-reposition-actions">
                    <button
                      type="button"
                      className="event-cover-reposition-cancel"
                      onClick={cancelCoverReposition}
                      disabled={isSavingCoverPosition}
                    >
                      Cancel
                    </button>
                    <button
                      type="button"
                      className="event-cover-reposition-save"
                      onClick={saveCoverReposition}
                      disabled={isSavingCoverPosition}
                    >
                      {isSavingCoverPosition ? 'Saving…' : 'Save'}
                    </button>
                  </div>
                </>
              )}
            </div>
          )}
          <header className="event-detail-header">
            <div className="event-detail-kicker">
              <span className="poll-source-pill">{event.hub_item?.short_id || `#E-${event.id}`}</span>
              <span>{rsvpSummaryText(event)}</span>
            </div>
            <div className="event-detail-title-row">
              <h1>{event.title}</h1>
              {canEdit && (
                <button
                  type="button"
                  className={`event-edit-toggle-btn${isEditing ? ' active' : ''}`}
                  onClick={() => setIsEditing(v => !v)}
                >
                  {isEditing ? 'Cancel' : 'Edit'}
                </button>
              )}
            </div>
            <div className="event-detail-primary-actions">
              <AddToCalendarButton event={event} className="add-calendar--secondary" />
              <HubItemCardMeta item={event.hub_item} onPin={togglePin} onSendToChat={sendToChat} onPrepareChatMessage={prepareChatMessage} />
            </div>
            <EventHeaderMeta event={event} />
            {event.description && <p className="event-detail-description">{event.description}</p>}
            {event.creator && (
              <p className="event-creator-line">
                Created by{' '}
                <button
                  type="button"
                  className="event-creator-link"
                  onClick={() => event.creator.username && onNavigate(`/profile/${event.creator.username}`)}
                >
                  {event.creator.nickname}
                </button>
              </p>
            )}
          </header>

          {event.invites?.length > 0 && (
            <div className="event-invites">
              <strong>Invited</strong>
              <span>{event.invites.map((member) => member.nickname).join(', ')}</span>
            </div>
          )}

          {canEdit && isEditing && (
            <section className="event-detail-section event-edit-panel">
              <h2>Edit Event</h2>
              <form className="event-edit-form" onSubmit={saveEvent}>
                <input
                  value={eventForm.title}
                  onChange={(inputEvent) => setEventForm({ ...eventForm, title: inputEvent.target.value })}
                  placeholder="Event title"
                  required
                />
                <input
                  type="datetime-local"
                  value={eventForm.starts_at}
                  onChange={(inputEvent) => setEventForm({ ...eventForm, starts_at: inputEvent.target.value })}
                  onClick={openNativeDatePicker}
                  required
                />
                <input
                  value={eventForm.location}
                  onChange={(inputEvent) => setEventForm({ ...eventForm, location: inputEvent.target.value })}
                  placeholder="Location"
                />
                <div className="event-cover-picker">
                  <div className="event-cover-picker-row">
                    {event.cover_photo_url ? (
                      <img className="event-cover-picker-preview" src={event.cover_photo_url} alt="Current cover" />
                    ) : (
                      <div className="event-cover-picker-preview event-cover-picker-preview--empty">No cover photo</div>
                    )}
                    <div className="event-cover-picker-actions">
                      <input
                        ref={coverFileInputRef}
                        type="file"
                        accept="image/*"
                        onChange={handleCoverFileSelect}
                        style={{ display: 'none' }}
                      />
                      <button
                        type="button"
                        onClick={() => coverFileInputRef.current?.click()}
                        disabled={isUploadingCover}
                      >
                        {isUploadingCover ? 'Uploading…' : 'Upload new'}
                      </button>
                      <button
                        type="button"
                        onClick={openCoverPicker}
                        disabled={isApplyingCover}
                      >
                        Pick from photos
                      </button>
                      {event.cover_photo_url && (
                        <button type="button" onClick={removeCover} className="event-cover-picker-remove">
                          Remove
                        </button>
                      )}
                    </div>
                  </div>

                  {coverPickerOpen && (
                    <div className="event-cover-picker-pane">
                      <div className="event-cover-picker-tabs" role="tablist">
                        <button
                          type="button"
                          role="tab"
                          aria-selected={coverPickerMode === 'event'}
                          className={coverPickerMode === 'event' ? 'active' : ''}
                          onClick={() => switchCoverPickerMode('event')}
                        >
                          This event ({photos.length})
                        </button>
                        <button
                          type="button"
                          role="tab"
                          aria-selected={coverPickerMode === 'all'}
                          className={coverPickerMode === 'all' ? 'active' : ''}
                          onClick={() => switchCoverPickerMode('all')}
                        >
                          All photos
                        </button>
                        <button
                          type="button"
                          className="event-cover-picker-close"
                          onClick={() => setCoverPickerOpen(false)}
                          aria-label="Close picker"
                        >
                          ✕
                        </button>
                      </div>

                      {(() => {
                        const items = coverPickerMode === 'event' ? photos : allPhotos;
                        if (!items.length) {
                          return (
                            <p className="event-cover-picker-empty">
                              {coverPickerMode === 'event'
                                ? 'No photos for this event yet — upload one below or switch to All photos.'
                                : 'No photos found.'}
                            </p>
                          );
                        }
                        return (
                          <div className="event-cover-picker-grid">
                            {items.map((photo) => {
                              const isCurrent = !!event.cover_photo_url && event.cover_photo_url === photo.url;
                              return (
                                <button
                                  key={photo.id}
                                  type="button"
                                  className={`event-cover-picker-tile${isCurrent ? ' is-current' : ''}`}
                                  onClick={() => applyCover(photo)}
                                  disabled={isApplyingCover}
                                  title={isCurrent ? 'Current cover' : 'Set as cover'}
                                >
                                  <img src={photo.thumbnail_url || photo.url} alt={photo.caption || ''} />
                                  {isCurrent && <span className="event-cover-picker-current">Current</span>}
                                </button>
                              );
                            })}
                          </div>
                        );
                      })()}
                    </div>
                  )}
                </div>
                <label className="event-edit-field">
                  <span>Reference tag</span>
                  <span className="event-edit-short-id">
                    <span className="event-edit-short-id-hash">#</span>
                    <input
                      value={eventForm.reference_tag}
                      onChange={(inputEvent) => setEventForm({
                        ...eventForm,
                        reference_tag: inputEvent.target.value.replace(/^#+/, ''),
                      })}
                      maxLength={19}
                      placeholder="E-4 or holiday-2026"
                    />
                  </span>
                  <small className="event-edit-hint">
                    {eventForm.reference_tag
                      ? `Type #${eventForm.reference_tag} in chat to link to this event.`
                      : 'Used to link to this event in chat.'}
                  </small>
                </label>
                <input
                  value={eventForm.photo_tag_id}
                  onChange={(inputEvent) => setEventForm({ ...eventForm, photo_tag_id: inputEvent.target.value })}
                  placeholder="Photo tag ID, e.g. #E-4"
                />
                <textarea
                  value={eventForm.description}
                  onChange={(inputEvent) => setEventForm({ ...eventForm, description: inputEvent.target.value })}
                  placeholder="Details"
                  rows="3"
                />
                <div className="event-invite-picker">
                  {members.map((member) => (
                    <label key={member.id || member.session_id}>
                      <input
                        type="checkbox"
                        checked={inviteIds.includes(member.id)}
                        onChange={(inputEvent) => toggleInvite(member.id, inputEvent.target.checked)}
                      />
                      {member.nickname}
                    </label>
                  ))}
                </div>
                <button type="submit" disabled={isSavingEvent}>{isSavingEvent ? 'Saving...' : 'Save event'}</button>
              </form>

              <form className="event-tags-form" onSubmit={(e) => { e.preventDefault(); saveTags(e); }}>
                <label>Tags</label>
                <TagChipInput
                  value={tagText}
                  onChange={setTagText}
                  onSubmit={() => saveTags({ preventDefault: () => {} })}
                  placeholder="food, weekend, planning"
                  disabled={isSavingTags || !event.hub_item}
                  maxTags={8}
                />
              </form>
            </section>
          )}

          <EventSection
            title="RSVP"
            className="event-rsvp-section"
            action={<span className="event-section-meta">{rsvpSummaryText(event)}</span>}
          >
            <div className="event-rsvp-actions event-rsvp-actions--detail-segmented" role="group" aria-label="Your RSVP">
              {RSVP_OPTIONS.map((option) => (
                <button
                  key={option.key}
                  type="button"
                  className={currentUserRsvp(event, currentUser) === option.key ? 'active' : ''}
                  onClick={() => handleRsvp(option.key)}
                  aria-pressed={currentUserRsvp(event, currentUser) === option.key}
                >
                  <span>{option.label}</span>
                  {currentUserRsvp(event, currentUser) === option.key && <em>Selected</em>}
                </button>
              ))}
            </div>
            <EventRsvpResults event={event} onOpenVoters={setActiveRsvpVoters} />
          </EventSection>

          <EventSection
            title="Photos"
            className="event-photos-section"
            action={!pendingEventPhoto ? (
              <label className="upload-control event-photo-upload">
                Upload photo
                <input type="file" accept="image/*" onChange={handlePhotoFileSelect} hidden />
              </label>
            ) : <span className="event-section-meta">{event.photo_tag_id || event.hub_item?.short_id || 'No tag'}</span>}
          >
            {!pendingEventPhoto ? (
              null
            ) : (
              <form className="photo-upload-form" onSubmit={submitEventPhoto}>
                <img className="photo-upload-preview" src={pendingEventPhoto.preview} alt="Preview" />
                <div className="photo-upload-fields">
                  <input
                    className="photo-upload-caption"
                    type="text"
                    value={eventPhotoCaption}
                    onChange={e => setEventPhotoCaption(e.target.value)}
                    placeholder="Add a caption…"
                    maxLength={500}
                    autoFocus
                  />
                  <input
                    className="photo-upload-tags"
                    type="text"
                    value={eventPhotoTags}
                    onChange={e => setEventPhotoTags(e.target.value)}
                    placeholder="Tags — comma separated"
                  />
                  {photos.length > 0 && (
                    <div className="photo-upload-tag-suggestions">
                      <span className="photo-upload-tag-suggestions-label">Suggest:</span>
                      {[...new Set(photos.flatMap(p => p.tags || []))].sort().map(tag => (
                        <button key={tag} type="button" className="photo-upload-tag-suggestion-chip" onClick={() => addEventPhotoTag(tag)}>
                          #{tag}
                        </button>
                      ))}
                    </div>
                  )}
                  <div className="photo-upload-actions">
                    <button type="submit" className="photo-upload-submit" disabled={isUploadingPhoto}>
                      {isUploadingPhoto ? 'Uploading…' : 'Upload'}
                    </button>
                    <button type="button" className="photo-upload-cancel" onClick={cancelEventPhoto}>Cancel</button>
                  </div>
                </div>
              </form>
            )}

            <div className="event-photo-grid">
              {photos.length > 0 ? photos.map((photo) => {
                const isCurrentCover = !!event.cover_photo_url && event.cover_photo_url === photo.url;
                const showSetCover = canSetCover && !isCurrentCover;
                const showDelete = canDeletePhoto(photo);
                return (
                  <article key={photo.id} className="event-photo-card">
                    <img src={photo.thumbnail_url || photo.url} alt={photo.original_filename} />
                    <span>{photo.tag_id}</span>
                    {isCurrentCover && <span className="event-photo-cover-badge">Cover</span>}
                    <div className="event-photo-card-actions">
                      {showSetCover && (
                        <button type="button" onClick={() => usePhotoAsCover(photo)}>Use as cover</button>
                      )}
                      {showDelete && (
                        <button
                          type="button"
                          className="event-photo-delete-btn"
                          onClick={() => setPhotoToDelete(photo)}
                        >
                          Delete
                        </button>
                      )}
                    </div>
                  </article>
                );
              }) : <EmptyEventState>No event photos yet. Add the first one.</EmptyEventState>}
            </div>
          </EventSection>

          <EventSection title="Posts" className="event-posts-section">
            <form className="event-post-form" onSubmit={createPost}>
              <textarea
                value={postText}
                onChange={(event) => setPostText(event.target.value)}
                placeholder="Post an update for this event"
                rows="3"
              />
              <button type="submit" disabled={isPosting}>{isPosting ? 'Posting...' : 'Post'}</button>
            </form>
            <div className="event-post-list">
              {posts.length > 0 ? posts.map((post) => (
                <article key={post.id} className="event-post-card">
                  <div className="event-post-card__header">
                    <strong>{post.creator?.nickname || 'Friend'}</strong>
                    {post.created_at && <span>{new Date(post.created_at).toLocaleString()}</span>}
                  </div>
                  <p>{post.content}</p>
                  <EngagementPanel
                    targetType="event_post"
                    targetId={post.id}
                    reactions={[]}
                    commentCount={post.comment_count}
                    onChange={loadPosts}
                  />
                </article>
              )) : <EmptyEventState>No updates yet.</EmptyEventState>}
            </div>
          </EventSection>

          <EventSection title="Reactions and comments" className="event-engagement-section">
            <EngagementPanel targetType="event" targetId={event.id} reactions={event.reactions} commentCount={event.comment_count} onChange={loadEvents} />
          </EventSection>
        </article>
      ) : (
        <div className="placeholder-panel compact">Event not found</div>
      )}

      {event && (
        <EventRsvpVoterSheet
          event={event}
          response={activeRsvpVoters}
          onClose={() => setActiveRsvpVoters(null)}
        />
      )}

      {photoToDelete && (
        <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="delete-photo-title">
          <div className="modal-card confirm-delete-modal">
            <h3 id="delete-photo-title">Delete this photo?</h3>
            <p>This can't be undone. The photo will be removed for everyone.</p>
            {photoToDelete.thumbnail_url && (
              <img className="confirm-delete-modal__preview" src={photoToDelete.thumbnail_url} alt="" />
            )}
            <div className="confirm-delete-modal__actions">
              <button
                type="button"
                className="confirm-delete-modal__cancel"
                onClick={() => setPhotoToDelete(null)}
                disabled={isDeletingPhoto}
              >
                Cancel
              </button>
              <button
                type="button"
                className="confirm-delete-modal__delete"
                onClick={confirmDeletePhoto}
                disabled={isDeletingPhoto}
              >
                {isDeletingPhoto ? 'Deleting…' : 'Delete'}
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
};

export default EventDetailPage;
