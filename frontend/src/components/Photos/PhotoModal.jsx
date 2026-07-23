import React, { useEffect } from 'react';
import { navigate } from '../../utils/navigate';
import { buildChatMessageHref } from '../../utils/chatLinks.js';
import './PhotoModal.css';

function formatDate(isoString) {
  if (!isoString) return null;
  const d = new Date(isoString);
  return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' });
}

function sourceLabel(source_type) {
  if (source_type === 'messenger_import') return 'Facebook Messenger';
  if (source_type === 'manual_upload') return 'Uploaded';
  return source_type || null;
}

const PhotoModal = ({ photo, onClose }) => {
  useEffect(() => {
    if (!photo) return undefined;
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [photo, onClose]);

  if (!photo) return null;

  const displayDate = photo.taken_at
    ? formatDate(photo.taken_at)
    : formatDate(photo.created_at);

  const sender = photo.original_sender || photo.uploaded_by;

  return (
    <div className="photo-modal" role="dialog" aria-modal="true" aria-label={photo.label || 'Photo'}>
      <button className="photo-modal__backdrop" type="button" aria-label="Close photo" onClick={onClose} />

      <div className="photo-modal__content">
        <button className="photo-modal__close" type="button" aria-label="Close photo" onClick={onClose}>
          ✕
        </button>

        <div className="photo-modal__image-wrap">
          <img src={photo.url} alt={photo.label || 'Shared photo'} />
        </div>

        <div className="photo-modal__meta">
          {photo.caption && (
            <p className="photo-modal__caption">{photo.caption}</p>
          )}

          <dl className="photo-modal__details">
            {sender && (
              <>
                <dt>{photo.original_sender ? 'Original sender' : 'Uploaded by'}</dt>
                <dd>{sender}</dd>
              </>
            )}
            {displayDate && (
              <>
                <dt>{photo.taken_at ? 'Date taken' : 'Uploaded'}</dt>
                <dd>{displayDate}</dd>
              </>
            )}
            {photo.source_type && (
              <>
                <dt>Source</dt>
                <dd>{sourceLabel(photo.source_type)}</dd>
              </>
            )}
          </dl>

          {photo.tags?.length > 0 && (
            <div className="photo-modal__tags" aria-label="Tags">
              {photo.tags.map(tag => (
                <span key={tag} className="photo-modal__tag">#{tag}</span>
              ))}
            </div>
          )}

          <div className="photo-modal__actions">
            {photo.showSeeInPhotos && (
              <button
                className="photo-modal__action"
                type="button"
                onClick={() => { onClose(); navigate('/photos'); }}
              >
                See in photos
              </button>
            )}
            {photo.message_id && (
              <button
                className="photo-modal__action"
                type="button"
                onClick={() => { onClose(); navigate(buildChatMessageHref(photo.message_id)); }}
              >
                See in chat
              </button>
            )}
            {photo.onSetAsHubCover && (
              <button
                className="photo-modal__action"
                type="button"
                disabled={photo.isSettingHubCover}
                onClick={() => photo.onSetAsHubCover()}
              >
                {photo.isSettingHubCover
                  ? 'Setting…'
                  : photo.isCurrentHubCover ? 'Hub cover ✓' : 'Set as Hub cover'}
              </button>
            )}
            {/* TODO: add edit caption/tags and delete actions when PATCH /api/v1/photos/{id} endpoint is implemented */}
          </div>
        </div>
      </div>
    </div>
  );
};

export default PhotoModal;
