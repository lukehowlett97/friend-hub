import React, { useEffect, useState } from 'react';
import { createComment, fetchComments, toggleReaction } from '../../services/api.js';
import ReactionModal from '../Reactions/ReactionModal.jsx';
import UserAvatar from '../Chat/UserAvatar.jsx';

const EMOJIS = ['👍', '😂', '🔥', '❤️', '👀'];

const reactionLabel = (count) => `${count} reaction${count === 1 ? '' : 's'}`;
const commentLabel = (count) => `${count} comment${count === 1 ? '' : 's'}`;

const EngagementPanel = ({ targetType, targetId, reactions = [], commentCount = 0, onChange }) => {
  const [comments, setComments] = useState([]);
  const [content, setContent] = useState('');
  const [isOpen, setIsOpen] = useState(commentCount > 0);
  const [error, setError] = useState(null);
  const [modal, setModal] = useState(null);
  const [pickerOpen, setPickerOpen] = useState(false);

  const totalReactions = reactions.reduce((sum, reaction) => sum + (reaction.count || 0), 0);

  const loadComments = () => {
    fetchComments(targetType, targetId)
      .then((data) => {
        setComments(data.comments || []);
        setError(null);
      })
      .catch((err) => setError(err.message));
  };

  useEffect(() => {
    if (isOpen) loadComments();
  }, [isOpen, targetType, targetId]);

  const handleReact = async (emoji) => {
    try {
      await toggleReaction(targetType, targetId, emoji);
      setPickerOpen(false);
      onChange?.();
    } catch (err) {
      setError(err.message);
    }
  };

  const handleCommentReact = async (commentId, emoji) => {
    try {
      await toggleReaction('comment', commentId, emoji);
      loadComments();
    } catch (err) {
      setError(err.message);
    }
  };

  const handleComment = async (event) => {
    event.preventDefault();
    if (!content.trim()) return;
    try {
      await createComment(targetType, targetId, content);
      setContent('');
      setIsOpen(true);
      loadComments();
      onChange?.();
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <div className="engagement-panel">
      <div className="reaction-row">
        <div className="react-menu">
          <button type="button" onClick={() => setPickerOpen((value) => !value)}>
            <span aria-hidden="true">＋</span>
            <span>React</span>
          </button>
          {pickerOpen && (
            <div className="react-menu-popover">
              {EMOJIS.map((emoji) => (
                <button key={emoji} type="button" onClick={() => handleReact(emoji)}>
                  {emoji}
                </button>
              ))}
            </div>
          )}
        </div>
        <button type="button" disabled={totalReactions === 0} onClick={() => totalReactions > 0 && setModal({ targetType, targetId })}>
          <span aria-hidden="true">♥</span>
          <span>{reactionLabel(totalReactions)}</span>
        </button>
        <button type="button" onClick={() => setIsOpen((value) => !value)}>
          <span aria-hidden="true">◌</span>
          <span>{commentLabel(commentCount || comments.length)}</span>
        </button>
      </div>
      {error && <div className="inline-error">{error}</div>}
      {isOpen && (
        <div className="comments-panel">
          {comments.map((comment) => (
            <article key={comment.id} className="comment-row">
              <UserAvatar
                nickname={comment.creator?.nickname || 'Friend'}
                size={26}
                avatarUrl={comment.creator?.avatar_url}
              />
              <div className="comment-body">
                <strong>{comment.creator?.nickname || 'Friend'}</strong>
                <p>{comment.content}</p>
                <CommentReactions
                  reactions={comment.reactions || []}
                  onReact={(emoji) => handleCommentReact(comment.id, emoji)}
                  onOpen={() => setModal({ targetType: 'comment', targetId: comment.id })}
                />
              </div>
            </article>
          ))}
          <form className="comment-form" onSubmit={handleComment}>
            <input
              value={content}
              onChange={(event) => setContent(event.target.value)}
              placeholder="Add a comment"
            />
            <button type="submit">Send</button>
          </form>
        </div>
      )}

      {modal && (
        <ReactionModal
          targetType={modal.targetType || targetType}
          targetId={modal.targetId || targetId}
          initialEmoji={modal.emoji || null}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
};

const CommentReactions = ({ reactions = [], onReact, onOpen }) => {
  const [pickerOpen, setPickerOpen] = useState(false);
  const total = reactions.reduce((sum, reaction) => sum + (reaction.count || 0), 0);

  return (
    <div className="comment-reactions">
      <div className="react-menu">
        <button type="button" onClick={() => setPickerOpen((value) => !value)}>
          <span aria-hidden="true">＋</span>
          <span>React</span>
        </button>
        {pickerOpen && (
          <div className="react-menu-popover">
            {EMOJIS.map((emoji) => (
              <button
                key={emoji}
                type="button"
                onClick={() => {
                  onReact(emoji);
                  setPickerOpen(false);
                }}
              >
                {emoji}
              </button>
            ))}
          </div>
        )}
      </div>
      {total > 0 && (
        <button type="button" onClick={onOpen}>
          <span aria-hidden="true">♥</span>
          <span>{reactionLabel(total)}</span>
        </button>
      )}
    </div>
  );
};

export default EngagementPanel;
