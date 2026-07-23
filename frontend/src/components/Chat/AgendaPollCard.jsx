import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { fetchPollCard, votePoll } from '../../services/api.js';
import { useAuth } from '../../auth/AuthProvider.jsx';
import './AgendaPollCard.css';

const STATUS_LABELS = {
  scheduled: 'Scheduled',
  live: 'Live',
  closed: 'Closed',
  cancelled: 'Cancelled',
};

const formatShort = (iso) => {
  if (!iso) return '';
  try {
    return new Date(iso).toLocaleString([], {
      weekday: 'short',
      day: '2-digit',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return iso;
  }
};

const formatCountdown = (msRemaining) => {
  if (msRemaining <= 0) return 'Closed';
  const totalSeconds = Math.floor(msRemaining / 1000);
  const days = Math.floor(totalSeconds / 86400);
  const hours = Math.floor((totalSeconds % 86400) / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (days > 0) return `${days}d ${hours}h left`;
  if (hours > 0) return `${hours}h ${minutes}m left`;
  if (minutes > 0) return `${minutes}m ${seconds}s left`;
  return `${seconds}s left`;
};

const AgendaPollCard = ({
  pollId,
  initialCard = null,
  compact = false,
  onNavigate,
  onStateChange,
}) => {
  const { user } = useAuth();
  const [card, setCard] = useState(initialCard);
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [now, setNow] = useState(() => Date.now());

  const refresh = useCallback(async () => {
    if (!pollId) return;
    try {
      const next = await fetchPollCard(pollId);
      setCard(next);
      setError(null);
      onStateChange?.(next);
    } catch (err) {
      setError(err.message || 'Failed to load motion');
    }
  }, [pollId, onStateChange]);

  useEffect(() => {
    if (!initialCard) refresh();
  }, [initialCard, refresh]);

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  // Light status auto-refresh: poll the card every 20s while live or scheduled
  // so transitions (scheduled→live, live→closed) reflect without a manual reload.
  useEffect(() => {
    if (!card) return undefined;
    if (card.status === 'closed' || card.status === 'cancelled') return undefined;
    const id = setInterval(() => { refresh(); }, 20000);
    return () => clearInterval(id);
  }, [card, refresh]);

  const closesAtMs = useMemo(() => (card?.voting_closes_at ? Date.parse(card.voting_closes_at) : null), [card?.voting_closes_at]);
  const opensAtMs  = useMemo(() => (card?.voting_opens_at  ? Date.parse(card.voting_opens_at)  : null), [card?.voting_opens_at]);

  const remainingMs = closesAtMs ? closesAtMs - now : null;
  const opensInMs   = opensAtMs  ? opensAtMs - now : null;

  // Auto-flip status client-side if backend hasn't caught up yet.
  const effectiveStatus = useMemo(() => {
    if (!card) return null;
    if (card.status === 'cancelled' || card.status === 'closed') return card.status;
    if (closesAtMs && closesAtMs <= now) return 'closed';
    if (opensAtMs && opensAtMs > now) return 'scheduled';
    return 'live';
  }, [card, closesAtMs, opensAtMs, now]);

  const handleVote = async (optionId, checkedHint) => {
    if (!card || submitting) return;
    if (effectiveStatus !== 'live') return;
    const isSingle = card.vote_mode === 'single';
    const currentVote = new Set(card.current_user_vote || []);
    let nextSet;
    if (isSingle) {
      nextSet = new Set([optionId]);
    } else {
      nextSet = new Set(currentVote);
      if (checkedHint === false || nextSet.has(optionId)) nextSet.delete(optionId);
      else nextSet.add(optionId);
      if (nextSet.size === 0) {
        // Backend requires at least one. Treat empty as cancel; do nothing.
        return;
      }
    }
    setSubmitting(true);
    setError(null);
    try {
      const result = await votePoll(pollId, Array.from(nextSet));
      if (result?.card) {
        setCard(result.card);
        onStateChange?.(result.card);
      } else {
        await refresh();
      }
    } catch (err) {
      setError(err.message || 'Failed to vote');
    } finally {
      setSubmitting(false);
    }
  };

  if (!card) {
    return (
      <div className={`agenda-poll-card${compact ? ' compact' : ''} loading`}>
        {error ? <span className="agenda-poll-card-error">{error}</span> : <span>Loading motion…</span>}
      </div>
    );
  }

  const status = effectiveStatus || card.status;
  const totalVotes = card.total_votes || 0;
  const selected = new Set(card.current_user_vote || []);
  const isLive = status === 'live';
  const isScheduled = status === 'scheduled';
  const isClosed = status === 'closed' || status === 'cancelled';
  const isAuthed = !!user;
  const cannotVoteReason = !isAuthed
    ? 'Sign in to vote.'
    : isScheduled
      ? 'Voting has not opened yet.'
      : isClosed
        ? 'Voting is closed.'
        : null;

  const eventLabel = card.event_type_label || (card.event_type ? 'Motion' : 'Poll');
  const winnerLabel = card.winner?.label;

  return (
    <div className={`agenda-poll-card status-${status}${compact ? ' compact' : ''}`}>
      <div className="agenda-poll-card-head">
        <span className="agenda-poll-card-eyebrow">{eventLabel}</span>
        <span className={`agenda-poll-card-badge badge-${status}`}>{STATUS_LABELS[status] || status}</span>
      </div>

      <h4 className="agenda-poll-card-title">{card.title || card.question}</h4>

      {card.target_user && (
        <div className="agenda-poll-card-target">
          Target: <strong>{card.target_user.nickname}</strong>
          {card.proposed_nickname ? <> → "{card.proposed_nickname}"</> : null}
          {card.proposed_role ? <> → "{card.proposed_role}"</> : null}
        </div>
      )}

      <div className="agenda-poll-card-timing">
        {isScheduled && opensAtMs && (
          <>
            <span>Opens {formatShort(card.voting_opens_at)}</span>
            <span className="dot">·</span>
            <span>Closes {formatShort(card.voting_closes_at)}</span>
          </>
        )}
        {isLive && remainingMs !== null && (
          <span className="agenda-poll-card-countdown">{formatCountdown(remainingMs)}</span>
        )}
        {isClosed && (
          <span>Closed {formatShort(card.voting_closes_at)}</span>
        )}
      </div>

      <div className="agenda-poll-card-options">
        {card.options.map((option) => {
          const pct = totalVotes ? Math.round(((option.vote_count || 0) / totalVotes) * 100) : 0;
          const isSelected = selected.has(option.id);
          const disabled = !isLive || submitting || !isAuthed;
          return (
            <button
              key={option.id}
              type="button"
              className={`agenda-poll-option${isSelected ? ' selected' : ''}${disabled ? ' disabled' : ''}`}
              disabled={disabled}
              onClick={() => handleVote(option.id, !isSelected)}
              title={disabled && cannotVoteReason ? cannotVoteReason : option.label}
            >
              <span className="agenda-poll-option-fill" style={{ width: `${pct}%` }} aria-hidden="true" />
              <span className="agenda-poll-option-label">{option.label}</span>
              <span className="agenda-poll-option-count">{option.vote_count || 0}</span>
            </button>
          );
        })}
      </div>

      {isClosed && winnerLabel && (
        <div className="agenda-poll-card-result">
          Winner: <strong>{winnerLabel}</strong> ({card.winner?.vote_count || 0} {card.winner?.vote_count === 1 ? 'vote' : 'votes'})
        </div>
      )}

      {error && <div className="agenda-poll-card-error">{error}</div>}
      {!error && cannotVoteReason && !isClosed && (
        <div className="agenda-poll-card-hint">{cannotVoteReason}</div>
      )}

      <div className="agenda-poll-card-actions">
        <button
          type="button"
          className="agenda-poll-card-link"
          onClick={() => onNavigate?.('/polls')}
        >
          {isClosed ? 'View result' : 'Open full poll'}
        </button>
      </div>
    </div>
  );
};

export default AgendaPollCard;
