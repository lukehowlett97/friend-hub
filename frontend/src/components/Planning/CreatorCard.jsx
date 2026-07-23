import React from 'react';
import UserAvatar from '../Chat/UserAvatar.jsx';

const CreatorCard = ({ creator, onNavigate, verb = 'Created by' }) => {
  const nickname = creator?.nickname || 'Friend';
  const canNavigate = !!creator?.username && !!onNavigate;

  const content = (
    <>
      <UserAvatar nickname={nickname} size={30} avatarUrl={creator?.avatar_url} />
      <span>
        <em>{verb}</em>
        <strong>{nickname}</strong>
      </span>
    </>
  );

  if (!canNavigate) {
    return <div className="creator-card">{content}</div>;
  }

  return (
    <button
      type="button"
      className="creator-card creator-card--button"
      onClick={() => onNavigate(`/profile/${creator.username}`)}
    >
      {content}
    </button>
  );
};

export default CreatorCard;
