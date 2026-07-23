import React, { useState } from 'react';
import { getColorForNickname } from '../../utils/colorUtils';

const UserAvatar = ({ nickname = '?', size = 32, avatarUrl = null, avatarEmoji = null }) => {
  const [imgError, setImgError] = useState(false);

  const sharedStyle = {
    width: size,
    height: size,
    minWidth: size,
    borderRadius: '50%',
    flexShrink: 0,
    objectFit: 'cover',
    display: 'block',
  };

  if (avatarUrl && !imgError) {
    return (
      <img
        src={avatarUrl}
        alt={nickname}
        title={nickname}
        style={sharedStyle}
        onError={() => setImgError(true)}
      />
    );
  }

  if (avatarEmoji) {
    const fontSize = Math.round(size * 0.58);
    return (
      <div
        aria-label={nickname}
        title={nickname}
        style={{
          ...sharedStyle,
          background: 'linear-gradient(145deg, #f8fbff 0%, #d8e6ff 100%)',
          border: '1px solid rgba(102, 126, 234, 0.28)',
          boxShadow: 'inset 0 -2px 4px rgba(70, 91, 160, 0.12)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize,
          lineHeight: 1,
          userSelect: 'none',
        }}
      >
        {avatarEmoji}
      </div>
    );
  }

  const bg       = getColorForNickname(nickname);
  const fontSize = Math.round(size * 0.45);
  const initial  = nickname.charAt(0).toUpperCase();

  return (
    <div
      aria-label={nickname}
      title={nickname}
      style={{
        ...sharedStyle,
        backgroundColor: bg,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        color: '#fff',
        fontSize,
        fontWeight: 700,
        userSelect: 'none',
      }}
    >
      {initial}
    </div>
  );
};

export default UserAvatar;
