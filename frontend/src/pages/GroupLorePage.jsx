import React, { useEffect, useMemo, useRef, useState } from 'react';
import UserAvatar from '../components/Chat/UserAvatar.jsx';
import { searchGroupLore, fetchGroupLoreStats } from '../services/api.js';
import { buildChatMessageHref } from '../utils/chatLinks.js';
import './GroupLorePage.css';

const TABS = [
  { id: 'messages', label: 'Messages' },
  { id: 'people',   label: 'People'   },
];

const DATE_PRESETS = [
  { id: 'all',  label: 'All time', days: null },
  { id: '7d',   label: '7d',       days: 7    },
  { id: '30d',  label: '30d',      days: 30   },
  { id: '90d',  label: '90d',      days: 90   },
  { id: 'year', label: 'Year',     days: 365  },
];

// Convert a YYYY-MM-DD string from <input type="date"> to a UTC ISO string.
// The `from` boundary is midnight start of day; the `to` boundary is midnight
// of the *next* day — exclusive, matching the backend contract.
function dateInputToBoundary(value, kind) {
  if (!value) return null;
  const d = new Date(`${value}T00:00:00Z`);
  if (!Number.isFinite(d.getTime())) return null;
  if (kind === 'to') d.setUTCDate(d.getUTCDate() + 1);
  return d.toISOString();
}

function presetToRange(preset) {
  if (!preset || preset.days == null) return { dateFrom: null, dateTo: null };
  const to = new Date();
  const from = new Date(to.getTime() - preset.days * 86400 * 1000);
  return { dateFrom: from.toISOString(), dateTo: null };
}

// ── helpers ────────────────────────────────────────────────────────────────

function escapeRegex(str) {
  return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// Splits text into React nodes with <mark> around case-insensitive matches.
// Never uses dangerouslySetInnerHTML.
export function highlightMatch(text, query) {
  if (!text) return text;
  const q = (query || '').trim();
  if (!q) return text;
  const parts = text.split(new RegExp(`(${escapeRegex(q)})`, 'gi'));
  return parts.map((part, i) =>
    part && part.toLowerCase() === q.toLowerCase()
      ? <mark key={i} className="lore-mark">{part}</mark>
      : <React.Fragment key={i}>{part}</React.Fragment>
  );
}

// Formats a chat-message date robustly. Returns "Unknown date" for anything
// that doesn't parse, has a wildly out-of-range year (e.g. imported 1111),
// or is missing. Today's chat times → "3:14 PM". Last week → "Tue".
// Older → "5 Jun 2026".
export function formatLoreDate(iso) {
  if (!iso) return 'Unknown date';
  const d = new Date(iso);
  const t = d.getTime();
  if (!Number.isFinite(t)) return 'Unknown date';
  const year = d.getFullYear();
  if (year < 1990 || year > 2100) return 'Unknown date';

  const diffMs = Date.now() - t;
  const sec = Math.floor(diffMs / 1000);
  const day = 86400;

  if (sec < 60) return 'just now';
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  if (sec < day) return `${Math.floor(sec / 3600)}h ago`;
  if (sec < 7 * day) return `${Math.floor(sec / day)}d ago`;

  const sameYear = d.getFullYear() === new Date().getFullYear();
  return d.toLocaleDateString(undefined, sameYear
    ? { day: 'numeric', month: 'short' }
    : { day: 'numeric', month: 'short', year: 'numeric' });
}

export function formatPercentage(count, total) {
  if (!total || total <= 0) return '0%';
  const pct = (count / total) * 100;
  if (pct > 0 && pct < 1) return '<1%';
  return `${Math.round(pct)}%`;
}

// ── state components ──────────────────────────────────────────────────────

function EmptyBefore() {
  return (
    <div className="lore-state">
      <p className="lore-state-title">Search the group memory.</p>
      <p className="lore-state-sub">Find old jokes, forgotten plans, receipts, and legendary messages.</p>
    </div>
  );
}

function EmptyAfter() {
  return (
    <div className="lore-state">
      <p className="lore-state-title">No lore found for this one.</p>
      <p className="lore-state-sub">Try a shorter phrase, another spelling, or search by person.</p>
    </div>
  );
}

function LoadingState() {
  return (
    <div className="lore-state">
      <p className="lore-state-title">Searching the archive…</p>
      <p className="lore-state-sub">Sifting through the group history.</p>
    </div>
  );
}

function ErrorState({ message }) {
  return (
    <div className="lore-state is-error">
      <p className="lore-state-title">Something went wrong</p>
      <p className="lore-state-sub">{message}</p>
    </div>
  );
}

// ── cards ─────────────────────────────────────────────────────────────────

function MessageCard({ result, query, onOpen }) {
  const handleKey = (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      onOpen(result);
    }
  };
  return (
    <div
      className="lore-card"
      role="button"
      tabIndex={0}
      onClick={() => onOpen(result)}
      onKeyDown={handleKey}
      aria-label={`Open message from ${result.sender_nickname} in chat`}
    >
      <UserAvatar nickname={result.sender_nickname} avatarUrl={result.sender_avatar_url} size={36} />
      <div className="lore-card-body">
        <div className="lore-card-head">
          <span className="lore-card-name">{result.sender_nickname}</span>
          <span className="lore-card-time">{formatLoreDate(result.created_at)}</span>
        </div>
        <p className="lore-card-snippet">{highlightMatch(result.snippet || result.content, query)}</p>
        <div className="lore-card-foot">
          <span className="lore-card-action">Open in chat</span>
          <span className="lore-card-chev" aria-hidden>›</span>
        </div>
      </div>
    </div>
  );
}

function ChampionCard({ champion }) {
  if (!champion) return null;
  return (
    <div className="lore-champion">
      <div className="lore-champion-badge"><span aria-hidden>🏆</span> Lore champion</div>
      <div className="lore-champion-body">
        <UserAvatar nickname={champion.sender_nickname} avatarUrl={champion.sender_avatar_url} size={44} />
        <div>
          <div className="lore-champion-name">{champion.sender_nickname}</div>
          <div className="lore-champion-count">{champion.count} mentions</div>
        </div>
      </div>
    </div>
  );
}

function PersonRow({ person, max, total }) {
  const pct = max > 0 ? Math.max(6, Math.round((person.count / max) * 100)) : 0;
  return (
    <div className="lore-person-row">
      <UserAvatar nickname={person.sender_nickname} avatarUrl={person.sender_avatar_url} size={36} />
      <div className="lore-person-info">
        <div className="lore-person-name">
          <span className="lore-person-label">{person.sender_nickname}</span>
          <span className="lore-person-stats">
            <span className="lore-person-count">{person.count}</span>
            <span className="lore-person-dot">·</span>
            <span className="lore-person-pct">{formatPercentage(person.count, total)}</span>
          </span>
        </div>
        <div className="lore-bar"><div className="lore-bar-fill" style={{ width: `${pct}%` }} /></div>
      </div>
    </div>
  );
}

function PeopleSummaryLine({ stats, query }) {
  if (!stats || !stats.results.length) return null;
  const sorted = stats.results; // already sorted desc by backend
  const top = sorted[0];
  const runnerUp = sorted[1];
  const phrase = query ? `“${query}”` : 'that';

  let line;
  if (sorted.length === 1) {
    line = `${top.sender_nickname} is the only one who said ${phrase}.`;
  } else if (runnerUp && runnerUp.count === top.count) {
    line = `${sorted.length} people have said ${phrase} — it's a tie at the top.`;
  } else {
    line = `${top.sender_nickname} says ${phrase} the most.`;
  }
  return <p className="lore-summary-line">{line}</p>;
}

// ── page ──────────────────────────────────────────────────────────────────

export default function GroupLorePage({ onNavigate }) {
  const [query, setQuery] = useState('');
  const [activeTab, setActiveTab] = useState('messages');

  const [presetId, setPresetId] = useState('all');
  const [customOpen, setCustomOpen] = useState(false);
  const [customFrom, setCustomFrom] = useState(''); // YYYY-MM-DD
  const [customTo, setCustomTo] = useState('');

  const [messages, setMessages] = useState(null);
  const [stats, setStats] = useState(null);

  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);
  const inputRef = useRef(null);
  const lastFetched = useRef({ q: '', tab: '', from: '', to: '' });

  useEffect(() => { inputRef.current?.focus(); }, []);

  // Active range: custom range wins when either field is set, else preset.
  const { dateFrom, dateTo } = useMemo(() => {
    const customFromIso = dateInputToBoundary(customFrom, 'from');
    const customToIso = dateInputToBoundary(customTo, 'to');
    if (customFromIso || customToIso) return { dateFrom: customFromIso, dateTo: customToIso };
    return presetToRange(DATE_PRESETS.find(p => p.id === presetId));
  }, [presetId, customFrom, customTo]);

  // Messages tab can run with an empty query when a date filter is active —
  // that's "browse the archive" mode. People tab still needs a phrase to
  // count, so it gates on q.length >= 2.
  const hasDateFilter = Boolean(dateFrom || dateTo);
  const canRun = activeTab === 'messages'
    ? (query.trim().length >= 2 || hasDateFilter)
    : query.trim().length >= 2;

  useEffect(() => {
    const q = query.trim();
    if (!canRun) {
      setMessages(null);
      setStats(null);
      setError(null);
      setIsLoading(false);
      lastFetched.current = { q: '', tab: '', from: '', to: '' };
      return;
    }
    const key = { q, tab: activeTab, from: dateFrom || '', to: dateTo || '' };
    const last = lastFetched.current;
    if (key.q === last.q && key.tab === last.tab && key.from === last.from && key.to === last.to) return;

    const timer = setTimeout(async () => {
      setIsLoading(true);
      setError(null);
      try {
        if (activeTab === 'messages') {
          const data = await searchGroupLore(q, { limit: 30, dateFrom, dateTo });
          setMessages(data);
        } else {
          const data = await fetchGroupLoreStats(q, { dateFrom, dateTo });
          setStats(data);
        }
        lastFetched.current = key;
      } catch (err) {
        setError(err.message || 'Search failed');
      } finally {
        setIsLoading(false);
      }
    }, 300);

    return () => clearTimeout(timer);
  }, [query, activeTab, dateFrom, dateTo, canRun]);

  const handlePresetClick = (id) => {
    setPresetId(id);
    // Picking a preset clears any custom range to avoid two competing filters.
    setCustomFrom('');
    setCustomTo('');
  };

  const handleClearCustom = () => {
    setCustomFrom('');
    setCustomTo('');
  };

  const customActive = Boolean(customFrom || customTo);

  // Opens the native calendar on any tap inside the field. `showPicker()`
  // throws if the input isn't user-activated or isn't supported — we just
  // swallow that and fall back to the default focus behaviour.
  const openCalendar = (e) => {
    const input = e.currentTarget.querySelector('input[type="date"]');
    if (!input) return;
    try {
      if (typeof input.showPicker === 'function') input.showPicker();
      else input.focus();
    } catch {
      input.focus();
    }
  };

  const openInChat = (result) => {
    onNavigate?.(buildChatMessageHref(result.message_id, {
      params: { lore: query.trim() },
    }));
  };

  const maxCount = useMemo(() => stats?.results?.[0]?.count ?? 0, [stats]);
  const champion = useMemo(() => stats?.results?.[0] ?? null, [stats]);

  const trimmedQ = query.trim();
  const hasQuery = trimmedQ.length >= 2;
  const hasSearched = canRun;

  return (
    <section className="page group-lore-page">
      <header className="lore-header">
        <h1>Group Lore</h1>
        <p className="lore-subtitle">Find old jokes, receipts, and forgotten plans.</p>
      </header>

      <div className="lore-search-bar">
        <span className="lore-search-icon" aria-hidden>🔎</span>
        <input
          ref={inputRef}
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search messages…"
          autoComplete="off"
          aria-label="Search group memory"
        />
      </div>

      <div className="lore-filters">
        <div className="lore-chip-row" role="group" aria-label="Date range presets">
          {DATE_PRESETS.map(p => {
            const isActive = !customActive && presetId === p.id;
            return (
              <button
                key={p.id}
                type="button"
                className={`lore-chip ${isActive ? 'is-active' : ''}`}
                onClick={() => handlePresetClick(p.id)}
                aria-pressed={isActive}
              >
                {p.label}
              </button>
            );
          })}
          <button
            type="button"
            className={`lore-chip lore-chip-custom ${customActive ? 'is-active' : ''}`}
            onClick={() => setCustomOpen(v => !v)}
            aria-expanded={customOpen}
          >
            {customActive ? 'Custom ✓' : 'Custom…'}
          </button>
        </div>

        {customOpen && (
          <div className="lore-custom-range">
            <label className="lore-custom-field" onClick={openCalendar}>
              <span>From</span>
              <div className="lore-date-input">
                <input
                  type="date"
                  value={customFrom}
                  onChange={(e) => setCustomFrom(e.target.value)}
                  max={customTo || undefined}
                  aria-label="From date"
                />
                <span className="lore-date-icon" aria-hidden>📅</span>
              </div>
            </label>
            <label className="lore-custom-field" onClick={openCalendar}>
              <span>To</span>
              <div className="lore-date-input">
                <input
                  type="date"
                  value={customTo}
                  onChange={(e) => setCustomTo(e.target.value)}
                  min={customFrom || undefined}
                  aria-label="To date"
                />
                <span className="lore-date-icon" aria-hidden>📅</span>
              </div>
            </label>
            {customActive && (
              <button type="button" className="lore-custom-clear" onClick={handleClearCustom}>
                Clear
              </button>
            )}
          </div>
        )}
      </div>

      <div className="lore-tabs" role="tablist" aria-label="Group lore view">
        {TABS.map(tab => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={activeTab === tab.id}
            className={`lore-tab ${activeTab === tab.id ? 'is-active' : ''}`}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {!hasSearched && activeTab === 'messages' && <EmptyBefore />}
      {!hasSearched && activeTab === 'people' && (
        <div className="lore-state">
          <p className="lore-state-title">Type a phrase to see who said it most.</p>
          <p className="lore-state-sub">People stats need a word or phrase to count.</p>
        </div>
      )}

      {hasSearched && isLoading && <LoadingState />}
      {hasSearched && error && !isLoading && <ErrorState message={error} />}

      {hasSearched && !isLoading && !error && activeTab === 'messages' && messages && (
        messages.results.length === 0
          ? <EmptyAfter />
          : (
            <div className="lore-results">
              {messages.results.map(r => (
                <MessageCard key={r.message_id} result={r} query={trimmedQ} onOpen={openInChat} />
              ))}
            </div>
          )
      )}

      {hasSearched && !isLoading && !error && activeTab === 'people' && stats && (
        stats.results.length === 0
          ? <EmptyAfter />
          : (
            <>
              <PeopleSummaryLine stats={stats} query={trimmedQ} />
              <ChampionCard champion={champion} />
              <div className="lore-people-summary">
                <div><span className="stat-value">{stats.total_occurrences}</span><span className="stat-label">Mentions</span></div>
                <div><span className="stat-value">{stats.people}</span><span className="stat-label">People</span></div>
                <div><span className="stat-value">{stats.matching_messages}</span><span className="stat-label">Messages</span></div>
                {onNavigate && trimmedQ && (
                  <button
                    type="button"
                    className="lore-stats-link"
                    onClick={() => onNavigate(`/stats?range=all`)}
                    title="Open full stats explorer"
                  >
                    View full stats →
                  </button>
                )}
              </div>
              <div className="lore-people-list">
                {stats.results.map(p => (
                  <PersonRow
                    key={p.sender_session_id}
                    person={p}
                    max={maxCount}
                    total={stats.total_occurrences}
                  />
                ))}
              </div>
            </>
          )
      )}
    </section>
  );
}
