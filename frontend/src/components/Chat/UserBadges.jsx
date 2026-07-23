import React, { useEffect, useRef, useState } from 'react';
import './UserBadges.css';

// Reusable badge row for message headers (and anywhere a user identity shows).
// `badges` is an array of:
//   { id, label, description?, icon?, text?, variant? }
// - icon-only badges (e.g. the Hub Bot ✨) stay tiny; text badges show a pill.
// - Tapping/clicking a badge opens a small popover with label + description.
const UserBadges = ({ badges = [] }) => {
  const [openId, setOpenId] = useState(null);
  const rootRef = useRef(null);

  useEffect(() => {
    if (!openId) return undefined;
    const close = (e) => {
      if (!rootRef.current?.contains(e.target)) setOpenId(null);
    };
    const onKey = (e) => {
      if (e.key === 'Escape') setOpenId(null);
    };
    document.addEventListener('click', close);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('click', close);
      document.removeEventListener('keydown', onKey);
    };
  }, [openId]);

  if (!badges.length) return null;

  return (
    <span className="user-badges" ref={rootRef}>
      {badges.map((badge) => (
        <span key={badge.id} className="user-badge-wrap">
          <button
            type="button"
            className={`user-badge user-badge--${badge.variant || 'default'}${badge.text ? '' : ' user-badge--icon-only'}`}
            aria-label={badge.label}
            aria-expanded={openId === badge.id}
            title={badge.label}
            onClick={(e) => {
              e.stopPropagation();
              setOpenId((prev) => (prev === badge.id ? null : badge.id));
            }}
          >
            {badge.icon && <span className="user-badge__icon" aria-hidden="true">{badge.icon}</span>}
            {badge.text && <span className="user-badge__text">{badge.text}</span>}
          </button>
          {openId === badge.id && (
            <span className="user-badge-popover" role="tooltip">
              <strong>{badge.label}</strong>
              {badge.description && <span>{badge.description}</span>}
            </span>
          )}
        </span>
      ))}
    </span>
  );
};

export default UserBadges;
