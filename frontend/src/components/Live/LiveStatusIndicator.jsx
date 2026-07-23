import React, { useCallback, useEffect, useState } from 'react';
import { fetchLiveAgendaMotions } from '../../services/api.js';
import './LiveStatusIndicator.css';

const REFRESH_MS = 30000;

/**
 * A compact LIVE pill for the chat header.
 *
 * Props:
 *   onToggle     – callback when the pill is clicked (toggle banner visibility)
 *   isExpanded   – whether the banner is currently visible
 *   onLiveChange – callback with true/false when live motions appear/disappear
 *   compact      – always true for header use; the component doesn't need a non-compact mode
 */
const LiveStatusIndicator = ({ onToggle, isExpanded, onLiveChange }) => {
  const [motions, setMotions] = useState([]);

  const refresh = useCallback(async () => {
    try {
      const data = await fetchLiveAgendaMotions();
      setMotions(data.motions || []);
    } catch {
      setMotions([]);
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, REFRESH_MS);
    return () => clearInterval(id);
  }, [refresh]);

  const isLive = motions.length > 0;
  const count = motions.length;

  useEffect(() => {
    onLiveChange?.(isLive);
  }, [isLive, onLiveChange]);

  if (!isLive) return null;

  return (
    <button
      type="button"
      className={`live-header-btn live-active${isExpanded ? ' live-expanded' : ''}`}
      onClick={onToggle}
      title={`${count} live motion${count !== 1 ? 's' : ''} — click to toggle`}
      aria-label={`Toggle live motions (${count} active)`}
      aria-expanded={isExpanded}
    >
      <span className="live-header-dot" aria-hidden="true" />
      <span>LIVE</span>
      <span className="live-header-count">{count}</span>
    </button>
  );
};

export default LiveStatusIndicator;
