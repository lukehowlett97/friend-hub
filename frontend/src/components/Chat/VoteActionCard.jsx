import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { castGovernanceVote, fetchGovernanceVote } from '../../services/api.js';
import { useAuth } from '../../auth/AuthProvider.jsx';
import './VoteActionCard.css';

const STATUS_LABELS = {
  open: 'Open',
  passed: 'Passed',
  failed: 'Failed',
  expired: 'Expired',
  cancelled: 'Cancelled',
};

const ACTION_LABELS = {
  nickname_change: 'Nickname vote',
  display_role_change: 'Chat role vote',
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
  if (msRemaining <= 0) return 'Expired';
  const totalSeconds = Math.floor(msRemaining / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) return `${hours}h ${minutes}m left`;
  if (minutes > 0) return `${minutes}m ${seconds}s left`;
  return `${seconds}s left`;
};

const VoteActionCard = ({ voteActionId, initialVote = null, compact = false }) => {
  const { user } = useAuth();
  const [voteAction, setVoteAction] = useState(initialVote);
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [now, setNow] = useState(() => Date.now());

  const refresh = useCallback(async () => {
    if (!voteActionId) return;
    try {
      const next = await fetchGovernanceVote(voteActionId);
      setVoteAction(next);
      setError(null);
    } catch (err) {
      setError(err.message || 'Failed to load vote');
    }
  }, [voteActionId]);

  useEffect(() => {
    if (!initialVote) refresh();
  }, [initialVote, refresh]);

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    if (!voteAction) return undefined;
    if (voteAction.status !== 'open') return undefined;
    const id = setInterval(() => { refresh(); }, 20000);
    return () => clearInterval(id);
  }, [voteAction, refresh]);

  const expiresAtMs = useMemo(() => (
    voteAction?.expires_at ? Date.parse(voteAction.expires_at) : null
  ), [voteAction?.expires_at]);

  const effectiveStatus = useMemo(() => {
    if (!voteAction) return null;
    if (voteAction.status !== 'open') return voteAction.status;
    if (expiresAtMs && expiresAtMs <= now) return 'expired';
    return 'open';
  }, [voteAction, expiresAtMs, now]);

  const handleVote = async (vote) => {
    if (!voteAction || submitting || effectiveStatus !== 'open') return;
    setSubmitting(true);
    setError(null);
    try {
      const result = await castGovernanceVote(voteActionId, vote);
      if (result?.vote_action) setVoteAction(result.vote_action);
      else await refresh();
    } catch (err) {
      setError(err.message || 'Failed to vote');
      await refresh();
    } finally {
      setSubmitting(false);
    }
  };

  if (!voteAction) {
    return (
      <div className={`vote-action-card${compact ? ' compact' : ''} loading`}>
        {error ? <span className="vote-action-card-error">{error}</span> : <span>Loading vote...</span>}
      </div>
    );
  }

  const payload = voteAction.payload || {};
  const status = effectiveStatus || voteAction.status;
  const isOpen = status === 'open';
  const isClosed = status !== 'open';
  const yesCount = voteAction.yes_count || 0;
  const noCount = voteAction.no_count || 0;
  const totalVotes = yesCount + noCount;
  const yesPct = totalVotes ? Math.round((yesCount / totalVotes) * 100) : 0;
  const noPct = totalVotes ? Math.round((noCount / totalVotes) * 100) : 0;
  const currentVote = voteAction.current_user_vote;
  const isDisplayRoleChange = voteAction.action_type === 'display_role_change';
  const proposedValue = isDisplayRoleChange ? payload.proposed_display_role : payload.proposed_nickname;
  const currentValue = isDisplayRoleChange
    ? (payload.current_display_role || voteAction.target_user?.display_role || 'Citizen')
    : (payload.current_nickname || voteAction.target_user?.nickname);
  const resultLabel = isDisplayRoleChange ? 'chat role' : 'nickname';
  const remainingMs = expiresAtMs ? expiresAtMs - now : null;
  const disabled = !user || !isOpen || submitting;
  const cannotVoteReason = !user
    ? 'Sign in to vote.'
    : isClosed
      ? 'Voting is closed.'
      : null;

  return (
    <div className={`vote-action-card status-${status}${compact ? ' compact' : ''}`}>
      <div className="vote-action-card-head">
        <span className="vote-action-card-eyebrow">
          {ACTION_LABELS[voteAction.action_type] || 'Governance vote'}
        </span>
        <span className={`vote-action-card-badge badge-${status}`}>
          {STATUS_LABELS[status] || status}
        </span>
      </div>

      <h4 className="vote-action-card-title">{voteAction.title}</h4>

      <div className="vote-action-card-meta">
        {voteAction.created_by?.nickname && (
          <span>Proposed by <strong>{voteAction.created_by.nickname}</strong></span>
        )}
        {voteAction.target_user?.nickname && (
          <span>Target: <strong>{voteAction.target_user.nickname}</strong></span>
        )}
      </div>

      <div className="vote-action-card-change">
        <span>{currentValue || (isDisplayRoleChange ? 'Current chat role' : 'Current nickname')}</span>
        <strong>{proposedValue || (isDisplayRoleChange ? 'Proposed chat role' : 'Proposed nickname')}</strong>
      </div>

      {payload.reason && (
        <p className="vote-action-card-reason">{payload.reason}</p>
      )}

      <div className="vote-action-card-timing">
        {isOpen && remainingMs !== null && (
          <span className="vote-action-card-countdown">{formatCountdown(remainingMs)}</span>
        )}
        {isClosed && voteAction.resolved_at && (
          <span>Resolved {formatShort(voteAction.resolved_at)}</span>
        )}
        {status === 'expired' && !voteAction.resolved_at && voteAction.expires_at && (
          <span>Expired {formatShort(voteAction.expires_at)}</span>
        )}
        {isOpen && voteAction.threshold_value && (
          <span>{voteAction.threshold_value} yes votes needed</span>
        )}
      </div>

      <div className="vote-action-options">
        <button
          type="button"
          className={`vote-action-option yes${currentVote === 'yes' ? ' selected' : ''}${disabled ? ' disabled' : ''}`}
          disabled={disabled}
          title={disabled && cannotVoteReason ? cannotVoteReason : 'Vote yes'}
          onClick={() => handleVote('yes')}
        >
          <span className="vote-action-option-fill" style={{ width: `${yesPct}%` }} aria-hidden="true" />
          <span className="vote-action-option-label">Yes</span>
          <strong>{yesCount}</strong>
        </button>
        <button
          type="button"
          className={`vote-action-option no${currentVote === 'no' ? ' selected' : ''}${disabled ? ' disabled' : ''}`}
          disabled={disabled}
          title={disabled && cannotVoteReason ? cannotVoteReason : 'Vote no'}
          onClick={() => handleVote('no')}
        >
          <span className="vote-action-option-fill" style={{ width: `${noPct}%` }} aria-hidden="true" />
          <span className="vote-action-option-label">No</span>
          <strong>{noCount}</strong>
        </button>
      </div>

      {status === 'passed' && (
        <div className="vote-action-card-result">Passed. {resultLabel === 'chat role' ? 'Chat role' : 'Nickname'} changed to <strong>{proposedValue}</strong>.</div>
      )}
      {status === 'expired' && (
        <div className="vote-action-card-result neutral">Expired. No {resultLabel} change was made.</div>
      )}
      {status === 'cancelled' && (
        <div className="vote-action-card-result neutral">Cancelled. No {resultLabel} change was made.</div>
      )}

      {error && <div className="vote-action-card-error">{error}</div>}
      {!error && cannotVoteReason && isOpen && (
        <div className="vote-action-card-hint">{cannotVoteReason}</div>
      )}
    </div>
  );
};

export default VoteActionCard;
