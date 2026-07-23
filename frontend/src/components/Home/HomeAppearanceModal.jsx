import React, { useCallback, useEffect, useRef, useState } from 'react';
import { fetchPhotos, removeHomeCoverPhoto, setHomeCoverPhoto, updateHomeAppearance } from '../../services/api.js';
import './HomeAppearanceModal.css';

const HomeAppearanceModal = ({ open, appearance, onClose, onUpdated, canEdit = true }) => {
  const [photos, setPhotos] = useState([]);
  const [loadingPhotos, setLoadingPhotos] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [position, setPosition] = useState({ x: 50, y: 50 });
  const [isDragging, setIsDragging] = useState(false);
  const previewRef = useRef(null);
  const dragStateRef = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    const handleKeyDown = (event) => { if (event.key === 'Escape') onClose(); };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [open, onClose]);

  useEffect(() => {
    if (!open) return;
    setError(null);
    setPosition({
      x: typeof appearance?.cover_position_x === 'number' ? appearance.cover_position_x : 50,
      y: typeof appearance?.cover_position_y === 'number' ? appearance.cover_position_y : 50,
    });
    setLoadingPhotos(true);
    fetchPhotos(40)
      .then((data) => setPhotos(data.photos || []))
      .catch((err) => setError(err.message))
      .finally(() => setLoadingPhotos(false));
  }, [open, appearance?.cover_photo_id, appearance?.cover_position_x, appearance?.cover_position_y]);

  if (!open) return null;

  const currentPhotoId = appearance?.cover_photo_id ?? null;
  const previewUrl = appearance?.cover_photo_url || null;

  const handlePick = async (photoId) => {
    if (!canEdit || busy) return;
    setBusy(true);
    setError(null);
    try {
      const next = await setHomeCoverPhoto(photoId);
      onUpdated?.(next);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const handleRemove = async () => {
    if (!canEdit || busy) return;
    setBusy(true);
    setError(null);
    try {
      const next = await removeHomeCoverPhoto();
      onUpdated?.(next);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const handleSavePosition = async () => {
    if (!canEdit || busy || !currentPhotoId) return;
    setBusy(true);
    setError(null);
    try {
      const next = await updateHomeAppearance({
        cover_position_x: position.x,
        cover_position_y: position.y,
      });
      onUpdated?.(next);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  // Drag the preview to reposition the cover. Because the image uses
  // `object-fit: cover`, dragging it down should reveal more of the top of the
  // photo — so pointer movement maps inversely onto object-position. We scale
  // the delta by the preview size so a full drag sweeps the whole 0–100 range.
  const handleDragStart = useCallback((event) => {
    if (!canEdit || busy || !currentPhotoId) return;
    const rect = previewRef.current?.getBoundingClientRect();
    if (!rect) return;
    const point = event.touches ? event.touches[0] : event;
    dragStateRef.current = {
      startX: point.clientX,
      startY: point.clientY,
      startPos: { ...position },
      width: rect.width,
      height: rect.height,
    };
    setIsDragging(true);
    if (event.cancelable) event.preventDefault();
  }, [canEdit, busy, currentPhotoId, position]);

  useEffect(() => {
    if (!isDragging) return undefined;

    const clamp = (n) => Math.max(0, Math.min(100, n));

    const handleMove = (event) => {
      const state = dragStateRef.current;
      if (!state) return;
      const point = event.touches ? event.touches[0] : event;
      const dx = point.clientX - state.startX;
      const dy = point.clientY - state.startY;
      // 100% of position spans (width - 0); invert so dragging right/down moves
      // the photo with the cursor rather than against it.
      const nextX = state.width ? clamp(state.startPos.x - (dx / state.width) * 100) : state.startPos.x;
      const nextY = state.height ? clamp(state.startPos.y - (dy / state.height) * 100) : state.startPos.y;
      setPosition({ x: Math.round(nextX), y: Math.round(nextY) });
      if (event.cancelable) event.preventDefault();
    };

    const handleEnd = () => {
      dragStateRef.current = null;
      setIsDragging(false);
    };

    window.addEventListener('mousemove', handleMove);
    window.addEventListener('mouseup', handleEnd);
    window.addEventListener('touchmove', handleMove, { passive: false });
    window.addEventListener('touchend', handleEnd);
    return () => {
      window.removeEventListener('mousemove', handleMove);
      window.removeEventListener('mouseup', handleEnd);
      window.removeEventListener('touchmove', handleMove);
      window.removeEventListener('touchend', handleEnd);
    };
  }, [isDragging]);

  const canReposition = canEdit && !busy && !!currentPhotoId;

  return (
    <div
      className="home-appearance-modal"
      role="dialog"
      aria-modal="true"
      aria-label="Homepage appearance settings"
    >
      <button
        className="home-appearance-modal__backdrop"
        type="button"
        aria-label="Close"
        onClick={onClose}
      />
      <div className="home-appearance-modal__sheet">
        <header className="home-appearance-modal__header">
          <h2>Hub cover</h2>
          <button
            type="button"
            className="home-appearance-modal__close"
            aria-label="Close"
            onClick={onClose}
          >×</button>
        </header>

        {error && <div className="inline-error">{error}</div>}

        <div
          ref={previewRef}
          className={`home-appearance-modal__preview${canReposition ? ' is-draggable' : ''}${isDragging ? ' is-dragging' : ''}`}
          onMouseDown={handleDragStart}
          onTouchStart={handleDragStart}
        >
          {previewUrl ? (
            <>
              <img
                src={previewUrl}
                alt="Current Hub cover"
                draggable={false}
                style={{ objectPosition: `${position.x}% ${position.y}%` }}
              />
              {canReposition && (
                <span className="home-appearance-modal__drag-hint">Drag to reposition</span>
              )}
            </>
          ) : (
            <div className="home-appearance-modal__preview-empty">No cover set</div>
          )}
        </div>

        {currentPhotoId && (
          <div className="home-appearance-modal__actions">
            <button
              type="button"
              className="home-appearance-modal__save"
              disabled={!canEdit || busy}
              onClick={handleSavePosition}
            >Save position</button>
            <button
              type="button"
              className="home-appearance-modal__remove"
              disabled={!canEdit || busy}
              onClick={handleRemove}
            >Remove cover</button>
          </div>
        )}

        <h3 className="home-appearance-modal__subhead">Pick a photo</h3>
        {loadingPhotos && <div className="inline-notice">Loading photos…</div>}
        {!loadingPhotos && photos.length === 0 && (
          <div className="placeholder-panel compact">No photos uploaded yet.</div>
        )}
        <div className="home-appearance-modal__grid">
          {photos.map((photo) => (
            <button
              key={photo.id}
              type="button"
              className={`home-appearance-modal__photo${photo.id === currentPhotoId ? ' is-current' : ''}`}
              disabled={!canEdit || busy}
              onClick={() => handlePick(photo.id)}
              aria-label={photo.caption || photo.original_filename || 'Photo'}
            >
              <img src={photo.thumbnail_url || photo.url} alt="" />
              {photo.id === currentPhotoId && <span className="home-appearance-modal__badge">Current</span>}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
};

export default HomeAppearanceModal;
