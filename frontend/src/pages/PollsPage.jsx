import React, { useEffect, useMemo, useState } from 'react';
import CreatorCard from '../components/Planning/CreatorCard.jsx';
import EngagementPanel from '../components/Planning/EngagementPanel.jsx';
import PollEditModal from '../components/Planning/PollEditModal.jsx';
import { createPoll, deletePoll, fetchMembers, fetchPolls, pinHubItem, sendHubItemToChat, votePoll } from '../services/api.js';
import { useAuth } from '../auth/AuthProvider.jsx';
import './FeaturePages.css';

const POLL_STATUS_LABELS = {
  scheduled: 'Scheduled',
  live: 'Live',
  closed: 'Closed',
  cancelled: 'Cancelled',
};

const pollStatus = (poll) => {
  if (poll.status) return poll.status;
  if (poll.is_closed) return 'closed';
  if (poll.deadline_at && new Date(poll.deadline_at) <= new Date()) return 'closed';
  if (poll.voting_opens_at && new Date(poll.voting_opens_at) > new Date()) return 'scheduled';
  return 'live';
};

const isPollClosed = (poll) => {
  const status = pollStatus(poll);
  return status === 'closed' || status === 'cancelled';
};

const isPollScheduled = (poll) => pollStatus(poll) === 'scheduled';

const statusPillLabel = (status) => POLL_STATUS_LABELS[status] || 'Open';

const selectedForUser = (poll, user) => new Set(
  (poll.votes || []).filter((vote) => String(vote.user_id) === String(user?.id)).map((vote) => vote.option_id),
);

const pollTotalVotes = (poll) => poll.options.reduce((sum, option) => sum + (option.vote_count || 0), 0);

const eventTypeLabel = (poll) => {
  if (poll.event_type_label) return poll.event_type_label;
  if (!poll.event_type) return null;
  if (poll.event_type === 'nickname_vote') return 'Nickname motion';
  if (poll.event_type === 'role_vote') return 'Role motion';
  if (poll.event_type === 'general_vote') return 'Council motion';
  return poll.event_type.replaceAll('_', ' ');
};

const pollTypeLabel = (poll) => eventTypeLabel(poll) || (poll.vote_mode === 'single' ? 'Single choice' : 'Multiple choice');

const formatDateTime = (iso) => iso ? new Date(iso).toLocaleString([], {
  weekday: 'short',
  day: '2-digit',
  month: 'short',
  hour: '2-digit',
  minute: '2-digit',
}) : null;

const formatPollDeadline = (poll) => {
  const status = pollStatus(poll);
  if (status === 'scheduled' && poll.voting_opens_at) return `Opens ${formatDateTime(poll.voting_opens_at)}`;
  if (!poll.deadline_at) return 'No vote-by time';
  return `${status === 'closed' || status === 'cancelled' ? 'Closed' : 'Vote by'} ${formatDateTime(poll.deadline_at)}`;
};

const pollCreatedDate = (poll) => poll.created_at ? `Created ${formatDateTime(poll.created_at)}` : null;

const optionVoters = (poll, optionId, memberById) => (
  (poll.votes || [])
    .filter((vote) => vote.option_id === optionId)
    .map((vote) => memberById.get(String(vote.user_id)) || { id: vote.user_id, nickname: 'Friend' })
);

const PollVoterSheet = ({ poll, option, memberById, onClose }) => {
  if (!poll || !option) return null;
  const voters = optionVoters(poll, option.id, memberById);

  return (
    <div className="poll-voter-sheet-backdrop" role="presentation" onClick={onClose}>
      <section
        className="poll-voter-sheet"
        role="dialog"
        aria-modal="true"
        aria-labelledby="poll-voter-sheet-title"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="poll-voter-sheet__header">
          <div>
            <h3 id="poll-voter-sheet-title">{option.label}</h3>
            <p>{voters.length ? `${voters.length} vote${voters.length === 1 ? '' : 's'}` : 'No votes yet'}</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close voter list">×</button>
        </div>
        {voters.length > 0 ? (
          <div className="poll-voter-list">
            {voters.map((member) => (
              <span key={member.id || member.user_id || member.nickname} className="poll-voter">
                {member.avatar_url ? <img src={member.avatar_url} alt="" /> : <span>{(member.nickname || '?')[0].toUpperCase()}</span>}
                <em>{member.nickname || 'Friend'}</em>
              </span>
            ))}
          </div>
        ) : (
          <div className="poll-empty-state">No votes yet</div>
        )}
      </section>
    </div>
  );
};

const PollQuickActions = ({ poll, canEdit, canDelete, onPin, onSendToChat, onPrepareChatMessage, onEdit, onDelete }) => {
  const [open, setOpen] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [justSent, setJustSent] = useState(false);
  const item = poll.hub_item;

  const sendToChat = async () => {
    if (!item || isSending) return;
    if (onPrepareChatMessage) {
      onPrepareChatMessage(item);
      return;
    }
    setIsSending(true);
    try {
      await onSendToChat?.(item);
      setJustSent(true);
      window.setTimeout(() => setJustSent(false), 2200);
    } finally {
      setIsSending(false);
    }
  };

  return (
    <div className="poll-quick-actions">
      {item && (
        <>
          <button
            type="button"
            className={`poll-icon-btn${item.pinned_to_home ? ' active' : ''}`}
            onClick={() => onPin?.(item)}
            aria-label={`${item.pinned_to_home ? 'Unpin' : 'Pin'} poll`}
            aria-pressed={!!item.pinned_to_home}
            title={item.pinned_to_home ? 'Unpin' : 'Pin'}
          >
            <span aria-hidden="true">📌</span>
          </button>
          <button
            type="button"
            className={`poll-icon-btn${justSent ? ' active' : ''}`}
            onClick={sendToChat}
            disabled={isSending || justSent}
            aria-label="Send poll to chat"
            title={justSent ? 'Sent' : 'Send to chat'}
          >
            <span aria-hidden="true">{justSent ? '✓' : '↗'}</span>
          </button>
        </>
      )}
      <div className="poll-overflow">
        <button
          type="button"
          className="poll-icon-btn"
          onClick={() => setOpen((value) => !value)}
          aria-label="More poll actions"
          aria-expanded={open}
        >
          <span aria-hidden="true">⋯</span>
        </button>
        {open && (
          <div className="poll-overflow-menu">
            {canEdit && <button type="button" onClick={() => { setOpen(false); onEdit(); }}>Edit poll</button>}
            {canDelete && <button type="button" className="danger" onClick={() => { setOpen(false); onDelete(); }}>Delete poll</button>}
            {!canEdit && !canDelete && <span>No extra actions</span>}
          </div>
        )}
      </div>
    </div>
  );
};

const PollVoteControl = ({ poll, selected, disabled, onVote }) => (
  <div className="poll-choice-control" role="group" aria-label="Cast your vote">
    {poll.options.map((option) => (
      <button
        key={option.id}
        type="button"
        className={selected.has(option.id) ? 'active' : ''}
        onClick={() => !disabled && onVote(option.id, !selected.has(option.id))}
        disabled={disabled}
        aria-pressed={selected.has(option.id)}
      >
        <span>{option.label}</span>
        {selected.has(option.id) && <em>Selected</em>}
      </button>
    ))}
  </div>
);

const PollResultRow = ({ poll, option, selected, onOpenVoters }) => {
  const totalVotes = pollTotalVotes(poll);
  const pct = totalVotes ? Math.round(((option.vote_count || 0) / totalVotes) * 100) : 0;
  const width = option.vote_count ? Math.max(7, pct) : 0;

  return (
    <button
      type="button"
      className={`poll-result-row${selected ? ' selected' : ''}`}
      onClick={() => onOpenVoters(option)}
      aria-label={`Show voters for ${option.label}: ${option.vote_count || 0} vote${option.vote_count === 1 ? '' : 's'}, ${pct} percent`}
    >
      <span className="poll-result-row__label">
        {selected && <span className="poll-selected-mark" aria-hidden="true">✓</span>}
        {option.label}
      </span>
      <span className="poll-result-row__track" aria-hidden="true">
        <span style={{ width: `${width}%` }} />
      </span>
      <strong>{option.vote_count || 0}</strong>
      <em>{pct}%</em>
    </button>
  );
};

const PollResults = ({ poll, selected, onOpenVoters }) => (
  <div className="poll-result-list">
    {poll.options.map((option) => (
      <PollResultRow
        key={option.id}
        poll={poll}
        option={option}
        selected={selected.has(option.id)}
        onOpenVoters={onOpenVoters}
      />
    ))}
  </div>
);

const PollsPage = ({ onNavigate }) => {
  const { user } = useAuth();
  const [polls, setPolls] = useState([]);
  const [members, setMembers] = useState([]);
  const [error, setError] = useState(null);
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [voterSheet, setVoterSheet] = useState(null);
  const [form, setForm] = useState({
    question: '',
    options: 'Option one\nOption two',
    vote_mode: 'single',
    deadline_at: '',
  });

  const loadPolls = () => {
    fetchPolls()
      .then((data) => {
        setPolls(data.polls || []);
        setError(null);
      })
      .catch((err) => setError(err.message));
  };

  useEffect(() => {
    loadPolls();
    fetchMembers().then((data) => setMembers(data.members || [])).catch(() => setMembers([]));
  }, []);

  const memberById = useMemo(() => new Map(
    members
      .flatMap((member) => [
        [String(member.id), member],
        [String(member.user_id), member],
        [String(member.session_id), member],
      ])
      .filter(([key]) => key && key !== 'undefined' && key !== 'null'),
  ), [members]);

  const livePolls = useMemo(() => polls.filter((poll) => pollStatus(poll) === 'live'), [polls]);
  const openPolls = useMemo(() => polls.filter((poll) => pollStatus(poll) === 'scheduled'), [polls]);
  const closedPolls = useMemo(() => polls.filter((poll) => isPollClosed(poll)), [polls]);

  const submitPoll = async (event) => {
    event.preventDefault();
    const options = form.options.split('\n').map((option) => option.trim()).filter(Boolean);
    try {
      await createPoll({
        question: form.question,
        options,
        vote_mode: form.vote_mode,
        deadline_at: form.deadline_at ? new Date(form.deadline_at).toISOString() : null,
      });
      setForm({ question: '', options: 'Option one\nOption two', vote_mode: 'single', deadline_at: '' });
      setIsCreateOpen(false);
      loadPolls();
    } catch (err) {
      setError(err.message);
    }
  };

  const canDeletePoll = (poll) => {
    const role = user?.role;
    return role === 'owner' || role === 'admin' || poll.creator?.id === user?.id;
  };

  const canEditPoll = canDeletePoll;
  const [editingPoll, setEditingPoll] = useState(null);

  const handleVote = async (poll, optionId, checked) => {
    if (isPollClosed(poll) || isPollScheduled(poll)) return;
    const selected = selectedForUser(poll, user);
    if (poll.vote_mode === 'single') {
      selected.clear();
      selected.add(optionId);
    } else if (checked) {
      selected.add(optionId);
    } else {
      selected.delete(optionId);
    }
    try {
      await votePoll(poll.id, Array.from(selected));
      loadPolls();
    } catch (err) {
      setError(err.message);
    }
  };

  const removePoll = async (poll) => {
    const confirmed = window.confirm(
      `Delete "${poll.question}"?\n\nThis will move the poll to the archive instead of permanently deleting it.`,
    );
    if (!confirmed) return;
    try {
      await deletePoll(poll.id);
      loadPolls();
    } catch (err) {
      setError(err.message);
    }
  };

  const togglePin = async (item) => {
    try {
      await pinHubItem(item.id, !item.pinned_to_home);
      loadPolls();
    } catch (err) {
      setError(err.message);
    }
  };

  const sendToChat = async (item) => {
    await sendHubItemToChat(item.id);
    loadPolls();
  };

  const prepareChatMessage = (item) => {
    onNavigate?.(`/chat?draft=${encodeURIComponent(item.short_id || '')}`);
  };

  const renderPoll = (poll, variant = 'live') => {
    const selected = selectedForUser(poll, user);
    const status = pollStatus(poll);
    const closed = status === 'closed' || status === 'cancelled';
    const scheduled = status === 'scheduled';
    const disabled = closed || scheduled;
    const totalVotes = pollTotalVotes(poll);
    const motionLabel = eventTypeLabel(poll);
    const tags = poll.hub_item?.tags || [];

    return (
      <article key={poll.id} className={`poll-feed-card poll-feed-card--${variant} status-${status}`}>
        <div className="poll-feed-card__top">
          <div className="poll-feed-card__badges">
            <span className="poll-ref">{poll.hub_item?.short_id || `P-${poll.id}`}</span>
            <span className={`poll-status-chip status-${status}`}>{statusPillLabel(status)}</span>
            {poll.source === 'chat_agenda' && <span className="poll-subtle-chip">Agenda</span>}
            {motionLabel && <span className="poll-subtle-chip">{motionLabel}</span>}
          </div>
          <PollQuickActions
            poll={poll}
            canEdit={canEditPoll(poll)}
            canDelete={canDeletePoll(poll)}
            onPin={togglePin}
            onSendToChat={sendToChat}
            onPrepareChatMessage={prepareChatMessage}
            onEdit={() => setEditingPoll(poll)}
            onDelete={() => removePoll(poll)}
          />
        </div>

        <div className="poll-feed-card__body">
          <h2>{poll.question}</h2>
          {poll.target_user && (
            <p className="poll-target-row">
              Target: <strong>{poll.target_user.nickname}</strong>
              {poll.proposed_nickname && <> → "{poll.proposed_nickname}"</>}
              {poll.proposed_role && <> → "{poll.proposed_role}"</>}
            </p>
          )}
          <div className="poll-meta-line">
            <CreatorCard creator={poll.creator} onNavigate={onNavigate} />
            <span>{pollCreatedDate(poll)}</span>
            <span>{formatPollDeadline(poll)}</span>
            <span>{pollTypeLabel(poll)}</span>
            {tags.slice(0, 2).map((tag) => <span key={tag}>#{tag}</span>)}
          </div>
        </div>

        <div className="poll-voting-card">
          <div className="poll-results-header">
            <h3>Cast your vote</h3>
            <span>{selected.size > 0 ? 'Vote saved' : `${totalVotes} vote${totalVotes === 1 ? '' : 's'}`}</span>
          </div>
          <PollVoteControl
            poll={poll}
            selected={selected}
            disabled={disabled}
            onVote={(optionId, checked) => handleVote(poll, optionId, checked)}
          />
          {disabled && <p className="poll-vote-hint">Voting is closed. Results are below.</p>}
          {!disabled && <p className="poll-vote-hint">{poll.vote_mode === 'single' ? 'Choose one option.' : 'Choose one or more options.'}</p>}
        </div>

        <div className="poll-results-card">
          <div className="poll-results-header">
            <h3>Group response</h3>
            <span>{totalVotes} vote{totalVotes === 1 ? '' : 's'}</span>
          </div>
          <PollResults
            poll={poll}
            selected={selected}
            onOpenVoters={(option) => setVoterSheet({ poll, option })}
          />
        </div>

        <EngagementPanel targetType="poll" targetId={poll.id} reactions={poll.reactions} commentCount={poll.comment_count} onChange={loadPolls} />
      </article>
    );
  };

  return (
    <section className="page feature-page polls-page">
      <header className="page-header">
        <h1>Polls</h1>
        <p className="page-subtitle">Make quick group decisions without losing them in chat.</p>
      </header>

      <section className="poll-create-panel">
        <button
          type="button"
          className="poll-create-toggle"
          onClick={() => setIsCreateOpen((value) => !value)}
          aria-expanded={isCreateOpen}
        >
          <span>{isCreateOpen ? 'Close' : 'Create poll'}</span>
          <strong>{isCreateOpen ? '×' : '+'}</strong>
        </button>

        {isCreateOpen && (
          <form className="feature-form stacked-form poll-create-form" onSubmit={submitPoll}>
            <input value={form.question} onChange={(event) => setForm({ ...form, question: event.target.value })} placeholder="Question" required />
            <select value={form.vote_mode} onChange={(event) => setForm({ ...form, vote_mode: event.target.value })}>
              <option value="single">Single choice</option>
              <option value="multiple">Multiple choice</option>
            </select>
            <input type="datetime-local" value={form.deadline_at} onChange={(event) => setForm({ ...form, deadline_at: event.target.value })} required />
            <textarea value={form.options} onChange={(event) => setForm({ ...form, options: event.target.value })} rows="4" />
            <button type="submit">Create Poll</button>
          </form>
        )}
      </section>

      {error && <div className="inline-error">{error}</div>}

      <section className="poll-section">
        <div className="section-heading">
          <h2>Live Polls</h2>
          <span>{livePolls.length} live</span>
        </div>
        <div className="feature-list poll-feed-list">
          {livePolls.length > 0
            ? livePolls.map((poll) => renderPoll(poll, 'live'))
            : <div className="placeholder-panel compact">No live polls right now</div>}
        </div>
      </section>

      {openPolls.length > 0 && (
        <section className="poll-section">
          <div className="section-heading">
            <h2>Open Soon</h2>
            <span>{openPolls.length} scheduled</span>
          </div>
          <div className="feature-list poll-feed-list">
            {openPolls.map((poll) => renderPoll(poll, 'scheduled'))}
          </div>
        </section>
      )}

      {closedPolls.length > 0 && (
        <section className="poll-section poll-section--closed">
          <div className="section-heading">
            <h2>Closed Polls</h2>
            <span>{closedPolls.length} resolved</span>
          </div>
          <div className="feature-list poll-feed-list">
            {closedPolls.map((poll) => renderPoll(poll, 'closed'))}
          </div>
        </section>
      )}

      <PollVoterSheet
        poll={voterSheet?.poll || null}
        option={voterSheet?.option || null}
        memberById={memberById}
        onClose={() => setVoterSheet(null)}
      />

      {editingPoll && (
        <PollEditModal
          poll={editingPoll}
          onClose={() => setEditingPoll(null)}
          onSaved={() => { setEditingPoll(null); loadPolls(); }}
        />
      )}
    </section>
  );
};

export default PollsPage;
