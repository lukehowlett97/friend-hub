import React, { useCallback, useEffect, useState } from 'react';
import { fetchLiveAgendaMotions } from '../../services/api.js';
import AgendaPollCard from './AgendaPollCard.jsx';
import './PinnedLiveAgendaBanner.css';

const REFRESH_MS = 30000;

const formatCountdown = (msRemaining) => {
  if (msRemaining <= 0) return 'Closing';
  const totalSeconds = Math.floor(msRemaining / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) return `${hours}h ${minutes}m`;
  if (minutes > 0) return `${minutes}m ${seconds}s`;
  return `${seconds}s`;
};

const PinnedLiveAgendaBanner = ({ onNavigate, onOpenPinned }) => {
  const [motions, setMotions] = useState([]);
  const [expanded, setExpanded] = useState(false);
  const [now, setNow] = useState(() => Date.now());

  const refresh = useCallback(async () => {
    try {
      const data = await fetchLiveAgendaMotions();
      setMotions(data.motions || []);
    } catch {
      // Banner is best-effort; silent failures keep chat working.
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, REFRESH_MS);
    return () => clearInterval(id);
  }, [refresh]);

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  if (!motions.length) return null;

  const top = motions[0];
  const remaining = top.voting_closes_at ? Date.parse(top.voting_closes_at) - now : null;
  const remainingLabel = remaining !== null ? formatCountdown(remaining) : '';
  const extraCount = motions.length - 1;

  const handleStateChange = (next) => {
    if (!next) return;
    if (next.status !== 'live' && next.status !== 'scheduled') {
      // Closed motions disappear from the pinned banner.
      setMotions((prev) => prev.filter((m) => m.id !== next.id));
    } else {
      setMotions((prev) => prev.map((m) => (m.id === next.id ? next : m)));
    }
  };

  const openTopMotion = () => onNavigate?.('/polls');

  return (
    <div className="pinned-agenda-banner">
      <div
        className="pinned-agenda-banner-summary"
        aria-expanded={expanded}
      >
        <button
          type="button"
          className="pinned-agenda-banner-pin"
          onClick={onOpenPinned}
          aria-label="Open pinned items"
          title="Open pinned items"
        >
          <span aria-hidden="true">📌</span>
        </button>
        <button
          type="button"
          className="pinned-agenda-banner-main"
          onClick={openTopMotion}
        >
          <span className="pinned-agenda-banner-title">
          {top.event_type_label || 'Council motion'} live: <strong>{top.title || top.question}</strong>
          </span>
        </button>
        {remainingLabel && <span className="pinned-agenda-banner-countdown">{remainingLabel}</span>}
        {extraCount > 0 && (
          <span className="pinned-agenda-banner-count" title={`${motions.length} live motions`}>
            +{extraCount} live
          </span>
        )}
        <button
          type="button"
          className="pinned-agenda-banner-toggle"
          onClick={() => setExpanded((v) => !v)}
          aria-label={expanded ? 'Collapse pinned banner' : 'Expand pinned banner'}
          aria-expanded={expanded}
        >
          {expanded ? '▾' : '▸'}
        </button>
      </div>

      {!expanded && (
        <div className="pinned-agenda-banner-quick">
          <button
            type="button"
            className="pinned-agenda-banner-vote"
            onClick={() => setExpanded(true)}
          >
            Vote now
          </button>
        </div>
      )}

      {expanded && (
        <div className="pinned-agenda-banner-cards">
          <AgendaPollCard
            pollId={top.id}
            initialCard={top}
            compact
            onNavigate={onNavigate}
            onStateChange={handleStateChange}
          />
          {motions.length > 1 && (
            <div className="pinned-agenda-banner-more">
              <span>{motions.length - 1} more live {motions.length - 1 === 1 ? 'motion' : 'motions'}</span>
              <button
                type="button"
                className="pinned-agenda-banner-link"
                onClick={() => onNavigate?.('/polls')}
              >
                Open polls
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default PinnedLiveAgendaBanner;
