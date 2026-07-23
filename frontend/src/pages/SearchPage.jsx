import React, { useEffect, useMemo, useRef, useState } from 'react';
import { search, searchPhotos, acceptDraftAction, rejectDraftAction, pinHubItem, sendHubItemToChat } from '../services/api.js';
import { apiFetch } from '../api/client.js';
import DraftActionCard from '../components/AI/DraftActionCard';
import UserAvatar from '../components/Chat/UserAvatar.jsx';
import { buildChatMessageHref } from '../utils/chatLinks.js';
import './SearchPage.css';

const TYPE_META = {
  references: { label: 'References', icon: '#', route: null, typeParam: null },
  messages:   { label: 'Messages',   icon: 'M', route: '/chat',      typeParam: 'messages' },
  polls:      { label: 'Polls',      icon: 'P', route: '/polls',     typeParam: 'polls' },
  events:     { label: 'Events',     icon: 'E', route: '/events',    typeParam: 'events' },
  photos:     { label: 'Photos',     icon: 'Ph', route: '/photos',   typeParam: 'photos' },
  people:     { label: 'People',     icon: '@', route: '/members',   typeParam: null },
  ideas:      { label: 'Ideas',      icon: 'I', route: '/ideas',     typeParam: 'ideas' },
  reminders:  { label: 'Reminders',  icon: 'R', route: '/reminders', typeParam: 'reminders' },
  notes:      { label: 'Notes',      icon: 'N', route: '/notes',     typeParam: 'notes' },
  comments:   { label: 'Comments',   icon: 'C', route: null,         typeParam: 'comments' },
};

const FILTERS = [
  { id: 'all', label: 'All', types: null },
  { id: 'messages', label: 'Messages', types: ['messages'] },
  { id: 'polls', label: 'Polls', types: ['polls'] },
  { id: 'events', label: 'Events', types: ['events'] },
  { id: 'photos', label: 'Photos', types: ['photos'] },
  { id: 'notes', label: 'Notes', types: ['notes'] },
  { id: 'people', label: 'People', types: ['people'] },
];

const DEFAULT_TYPES = 'people,ideas,polls,events,reminders,notes,comments,messages';
const SEARCH_MODES = [
  { id: 'search', label: 'Search', description: 'Fast keyword search' },
  { id: 'ai', label: 'Hub Bot', description: 'Ask or create' },
  { id: 'photo', label: 'Photos', description: 'Describe a photo' },
];
const CREATE_ACTIONS = [
  { id: 'image', label: '+ Image', command: '/image ', icon: 'I' },
  { id: 'event', label: '+ Event', command: '/event ', icon: 'E' },
  { id: 'poll', label: '+ Poll', command: '/poll ', icon: 'P' },
  { id: 'reminder', label: '+ Reminder', command: '/remind ', icon: 'R' },
];
const DEFAULT_MODE_QUERIES = { search: '', ai: '', photo: '' };
const PHOTO_SOURCE_TYPES = [
  { value: '', label: 'All sources' },
  { value: 'messenger_import', label: 'Messenger imports' },
  { value: 'chat_upload', label: 'Chat uploads' },
  { value: 'event_upload', label: 'Event uploads' },
  { value: 'manual_upload', label: 'Manual uploads' },
];
const TYPE_ALIASES = {
  message: 'messages',
  messages: 'messages',
  chat: 'messages',
  poll: 'polls',
  polls: 'polls',
  event: 'events',
  events: 'events',
  photo: 'photos',
  photos: 'photos',
  person: 'people',
  people: 'people',
  member: 'people',
  members: 'people',
  idea: 'ideas',
  ideas: 'ideas',
  reminder: 'reminders',
  reminders: 'reminders',
  note: 'notes',
  notes: 'notes',
  comment: 'comments',
  comments: 'comments',
};
const TYPE_ORDER = ['references', 'messages', 'polls', 'events', 'photos', 'people', 'ideas', 'reminders', 'notes', 'comments'];

function highlight(text, query) {
  if (!text || !query) return text;
  const terms = query
    .replace(/\b(type|from|tag):\S+/gi, '')
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  if (!terms.length) return text;
  const escaped = terms.map(term => term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|');
  const parts = String(text).split(new RegExp(`(${escaped})`, 'gi'));
  return parts.map((part, i) =>
    terms.some(term => part.toLowerCase() === term.toLowerCase())
      ? <mark key={i} className="search-mark">{part}</mark>
      : part
  );
}

function timeAgo(isoString) {
  if (!isoString) return '';
  const diff = (Date.now() - new Date(isoString)) / 1000;
  if (diff < 3600) return `${Math.floor(diff / 60) || 1}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

function formatDate(isoString) {
  if (!isoString) return '';
  const date = new Date(isoString);
  if (Number.isNaN(date.getTime())) return '';
  return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }).format(date);
}

function parseQuery(rawQuery) {
  const operators = {};
  const cleaned = rawQuery.replace(/\b(type|from|tag):([^\s]+)/gi, (_, key, value) => {
    operators[key.toLowerCase()] = value;
    return '';
  }).replace(/\s+/g, ' ').trim();
  const type = operators.type ? TYPE_ALIASES[operators.type.toLowerCase()] : null;
  return { cleaned, operators, type };
}

function referenceResult(query) {
  const match = query.trim().match(/^#?\s*([PERN])\s*-\s*(\d+)$/i);
  if (!match) return null;
  const prefix = match[1].toUpperCase();
  const id = match[2];
  const meta = {
    P: { type: 'polls', label: 'Poll', title: `Poll #P-${id}`, route: '/polls' },
    E: { type: 'events', label: 'Event', title: `Event #E-${id}`, route: `/events/${id}` },
    R: { type: 'reminders', label: 'Reminder', title: `Reminder #R-${id}`, route: '/reminders' },
    N: { type: 'notes', label: 'Note', title: `Note #N-${id}`, route: '/notes' },
  }[prefix];
  return {
    id: `${prefix}-${id}`,
    type: 'reference',
    title: meta.title,
    snippet: `Open the matching ${meta.label.toLowerCase()} reference.`,
    author: 'Reference',
    reference: `#${prefix}-${id}`,
    route: meta.route,
    created_at: null,
  };
}

function getTypeParam(activeFilter, parsedType) {
  if (parsedType) return parsedType;
  const filter = FILTERS.find(item => item.id === activeFilter);
  if (!filter || !filter.types) return DEFAULT_TYPES;
  return filter.types.join(',');
}

function countsFor(results, reference) {
  const counts = {};
  Object.entries(results || {}).forEach(([type, items]) => {
    counts[type] = items?.length || 0;
  });
  if (reference) counts.references = 1;
  return counts;
}

function resultTitle(type, item) {
  if (type === 'messages') return item.title || item.author || 'Message';
  if (type === 'polls') return item.title || item.question || 'Untitled poll';
  if (type === 'events') return item.title || 'Untitled event';
  if (type === 'photos') return item.title || item.caption || item.original_filename || 'Photo';
  return item.title || TYPE_META[type]?.label || 'Result';
}

function resultSnippet(type, item) {
  if (type === 'polls') return item.snippet || 'Poll question match';
  if (type === 'events') return item.snippet || item.location || 'Event match';
  if (type === 'photos') return item.snippet || item.caption || 'Photo match';
  return item.snippet || '';
}

function metaParts(type, item) {
  const parts = [];
  if (item.author && type !== 'references') parts.push(item.author);
  if (type === 'events' && item.created_at) parts.push(formatDate(item.created_at));
  else if (item.created_at) parts.push(timeAgo(item.created_at));
  if (item.status) parts.push(String(item.status).toUpperCase());
  if (item.reference) parts.push(item.reference);
  if (item.id && (type === 'polls' || type === 'events' || type === 'reminders' || type === 'notes')) {
    const prefix = { polls: 'P', events: 'E', reminders: 'R', notes: 'N' }[type];
    parts.push(`#${prefix}-${item.id}`);
  }
  return parts.filter(Boolean);
}

function getSearchHubItem(item) {
  return item?.hub_item || (item?.hub_item_id ? item : null);
}

function getSearchHubItemId(item) {
  const hubItem = getSearchHubItem(item);
  return hubItem?.id || item?.hub_item_id || null;
}

function SearchIcon() {
  return (
    <svg className="search-input-icon" viewBox="0 0 24 24" aria-hidden="true">
      <path d="M10.8 18.1a7.3 7.3 0 1 1 5.2-2.1l4 4a1.1 1.1 0 0 1-1.6 1.6l-4-4a7.2 7.2 0 0 1-3.6.5Zm0-2.2a5.1 5.1 0 1 0 0-10.2 5.1 5.1 0 0 0 0 10.2Z" />
    </svg>
  );
}

function SubmitArrowIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" width="18" height="18" fill="currentColor">
      <path d="M5 12h14M13 6l6 6-6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" fill="none" />
    </svg>
  );
}

function SearchModeSelector({ activeMode, onChange }) {
  return (
    <div className="search-mode-selector" role="tablist" aria-label="Search mode">
      {SEARCH_MODES.map(mode => (
        <button
          key={mode.id}
          type="button"
          role="tab"
          aria-selected={activeMode === mode.id}
          className={`search-mode-option${activeMode === mode.id ? ' is-active' : ''}`}
          onClick={() => onChange(mode.id)}
        >
          <span>{mode.label}</span>
          <small>{mode.description}</small>
        </button>
      ))}
    </div>
  );
}

function SearchInput({ value, mode, onChange, onClear, onSubmit, inputRef }) {
  const isAi = mode === 'ai';
  const placeholder = {
    search: 'Search messages, polls, people...',
    ai: 'Ask Hub Bot anything...',
    photo: 'Describe a photo...',
  }[mode] || 'Search...';
  const label = {
    search: 'Search Friend Hub',
    ai: 'Ask Hub Bot',
    photo: 'Search photos by description',
  }[mode] || 'Search';
  return (
    <div className="search-input-shell">
      <SearchIcon />
      <label className="sr-only" htmlFor="universal-search">Search Friend Hub</label>
      <input
        id="universal-search"
        ref={inputRef}
        className="search-input"
        type="search"
        value={value}
        onChange={e => onChange(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); onSubmit?.(); } }}
        placeholder={placeholder}
        autoComplete="off"
        aria-label={label}
      />
      {value && (
        <button type="button" className="search-clear-btn search-clear-btn--inline" onClick={onClear} aria-label="Clear search">
          ✕
        </button>
      )}
      <button
        type="button"
        className={`search-submit-btn${isAi ? ' search-submit-btn--ai' : ''}`}
        onClick={onSubmit}
        disabled={!value.trim()}
        aria-label={isAi ? 'Ask Hub Bot' : mode === 'photo' ? 'Search photos' : 'Search'}
      >
        <SubmitArrowIcon />
      </button>
    </div>
  );
}

function CreateActions({ onCreate }) {
  return (
    <section className="search-create-actions" aria-labelledby="search-create-title">
      <div className="search-create-actions__header">
        <h2 id="search-create-title">Create with Hub Bot</h2>
      </div>
      <div className="search-create-actions__grid">
        {CREATE_ACTIONS.map(action => (
          <button key={action.id} type="button" onClick={() => onCreate(action.command)}>
            <span aria-hidden="true">{action.icon}</span>
            {action.label}
          </button>
        ))}
      </div>
    </section>
  );
}

function FilterToggle({ label, activeCount, expanded, onClick }) {
  return (
    <button
      type="button"
      className={`search-filter-toggle${expanded ? ' is-open' : ''}`}
      onClick={onClick}
      aria-expanded={expanded}
    >
      <span>{activeCount > 0 ? `${label} ${activeCount} active` : label}</span>
      <strong aria-hidden="true">{expanded ? '−' : '+'}</strong>
    </button>
  );
}

function SearchFilterPanel({ activeFilter, counts, filters, onFilterChange, onFiltersChange, onClose }) {
  return (
    <div className="search-filter-panel" aria-label="Search filters">
      <div className="search-filter-panel__header">
        <h2>Filters</h2>
        <button type="button" onClick={onClose} aria-label="Close filters">x</button>
      </div>
      <div className="search-filter-grid" role="group" aria-label="Content type filters">
        {FILTERS.map(filter => {
          const count = filter.id === 'all'
            ? Object.values(counts).reduce((sum, value) => sum + value, 0)
            : counts[filter.id] || 0;
          return (
            <button
              key={filter.id}
              type="button"
              className={`search-filter-chip${activeFilter === filter.id ? ' is-active' : ''}`}
              onClick={() => onFilterChange(filter.id)}
              aria-pressed={activeFilter === filter.id}
            >
              <span>{filter.label}</span>
              {count > 0 && <strong>{count}</strong>}
            </button>
          );
        })}
      </div>
      <label className="search-filter-field">
        <span>Sender</span>
        <input
          type="text"
          value={filters.sender}
          onChange={event => onFiltersChange({ ...filters, sender: event.target.value })}
          placeholder="Any person"
        />
      </label>
    </div>
  );
}

function SearchEmptyState({ variant, query, onRetry, message }) {
  const content = {
    idle: {
      eyebrow: 'Universal finder',
      title: 'Search, ask, or create.',
      body: 'Find anything in Friend Hub, or ask Hub Bot to create events, polls, reminders, and images.',
    },
    loading: {
      eyebrow: 'Searching',
      title: 'Looking across Friend Hub...',
      body: '',
    },
    none: {
      eyebrow: 'No matches',
      title: `No results for "${query}"`,
      body: 'Try fewer words, a person name, a tag, or a reference like #E-8.',
    },
    error: {
      eyebrow: 'Search paused',
      title: 'Something went wrong.',
      body: 'The search service did not respond. Try again in a moment.',
    },
  }[variant];

  if (variant === 'loading') {
    return (
      <div className="search-skeletons" aria-live="polite" aria-label="Searching">
        {[0, 1, 2].map(index => <div key={index} className="search-skeleton-card" />)}
      </div>
    );
  }

  return (
    <div className={`search-state-card search-state-card--${variant}`}>
      <span>{content.eyebrow}</span>
      <h2>{content.title}</h2>
      <p>{message || content.body}</p>
      {variant === 'idle' && (
        <div className="search-hints" aria-label="Search examples">
          <code>type:poll agenda</code>
          <code>#E-8</code>
          <code>create a poll</code>
          <code>remind us tomorrow</code>
        </div>
      )}
      {variant === 'error' && (
        <button type="button" className="search-retry-btn" onClick={onRetry}>Retry</button>
      )}
    </div>
  );
}

function isPhotoSearchMode(activeFilter, parsedType) {
  return activeFilter === 'photos' || parsedType === 'photos';
}

function photoTitle(photo) {
  return photo.caption || photo.original_filename || 'Photo';
}

function formatPhotoDate(isoString) {
  if (!isoString) return '';
  const date = new Date(isoString);
  if (Number.isNaN(date.getTime())) return '';
  return new Intl.DateTimeFormat(undefined, {
    day: 'numeric', month: 'short', year: '2-digit', hour: 'numeric', minute: '2-digit',
  }).format(date);
}

function photoDate(photo) {
  return formatPhotoDate(photo.created_at) || timeAgo(photo.created_at);
}

function sourceRoute(photo) {
  if (photo.message_id) return buildChatMessageHref(photo.message_id);
  if (photo.conversation_id) return `/chat?conversation=${encodeURIComponent(photo.conversation_id)}`;
  return null;
}

function PhotoSearchFilters({ filters, onChange, onClose }) {
  return (
    <div className="search-filter-panel photo-search-filters" aria-label="Photo search filters">
      <div className="search-filter-panel__header">
        <h2>Photo filters</h2>
        <button type="button" onClick={onClose} aria-label="Close photo filters">x</button>
      </div>
      <label>
        <span>From</span>
        <input
          type="date"
          value={filters.dateFrom}
          onChange={event => onChange({ ...filters, dateFrom: event.target.value })}
        />
      </label>
      <label>
        <span>To</span>
        <input
          type="date"
          value={filters.dateTo}
          onChange={event => onChange({ ...filters, dateTo: event.target.value })}
        />
      </label>
      <label>
        <span>Source</span>
        <select
          value={filters.sourceType}
          onChange={event => onChange({ ...filters, sourceType: event.target.value })}
        >
          {PHOTO_SOURCE_TYPES.map(option => (
            <option key={option.value || 'all'} value={option.value}>{option.label}</option>
          ))}
        </select>
      </label>
    </div>
  );
}

function PhotoSearchGrid({ photos, query, onOpen, onNavigate }) {
  return (
    <section className="photo-search-section" aria-labelledby="photo-search-results-title">
      <div className="photo-search-section__header">
        <h2 id="photo-search-results-title">Photos</h2>
        <span>{photos.length} result{photos.length === 1 ? '' : 's'}</span>
      </div>
      <div className="photo-search-grid">
        {photos.map(photo => {
          const route = sourceRoute(photo);
          const title = photoTitle(photo);
          return (
            <article key={photo.photo_id} className="photo-search-card">
              <button type="button" className="photo-search-card__image" onClick={() => onOpen(photo)} aria-label={`Open ${title}`}>
                <img src={photo.image_url} alt={title} loading="lazy" />
              </button>
              <div className="photo-search-card__body">
                <h3>{highlight(title, query)}</h3>
                <div className="photo-search-card__meta">
                  {photoDate(photo) && <span>{photoDate(photo)}</span>}
                  {typeof photo.score === 'number' && <span>{Math.round(photo.score * 100)}% match</span>}
                </div>
                {photo.tags?.length > 0 && (
                  <div className="photo-search-tags" aria-label="Photo tags">
                    {photo.tags.slice(0, 4).map(tag => <span key={tag}>#{tag}</span>)}
                  </div>
                )}
                {route && (
                  <button type="button" className="photo-search-source" onClick={() => onNavigate?.(route)}>
                    {photo.message_id ? 'Source message' : 'Source chat'}
                  </button>
                )}
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}

function PhotoSearchModal({ photo, onClose, onNavigate }) {
  useEffect(() => {
    if (!photo) return undefined;
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [photo, onClose]);

  if (!photo) return null;
  const route = sourceRoute(photo);
  const title = photoTitle(photo);

  return (
    <div className="photo-search-modal" role="dialog" aria-modal="true" aria-label={title}>
      <button className="photo-search-modal__backdrop" type="button" aria-label="Close photo preview" onClick={onClose} />
      <div className="photo-search-modal__sheet">
        <button className="photo-search-modal__close" type="button" aria-label="Close photo preview" onClick={onClose}>x</button>
        <img src={photo.image_url} alt={title} />
        <div className="photo-search-modal__meta">
          <h2>{title}</h2>
          <div className="photo-search-card__meta">
            {photoDate(photo) && <span>{photoDate(photo)}</span>}
            {photo.conversation_id && <span>{photo.conversation_id}</span>}
            {photo.import_batch_id && <span>Batch {photo.import_batch_id}</span>}
          </div>
          {photo.tags?.length > 0 && (
            <div className="photo-search-tags">
              {photo.tags.map(tag => <span key={tag}>#{tag}</span>)}
            </div>
          )}
          {route && (
            <button
              type="button"
              className="photo-search-modal__action"
              onClick={() => {
                onClose();
                onNavigate?.(route);
              }}
            >
              {photo.message_id ? 'Open source message' : 'Open source chat'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function SearchResultCard({ type, item, query, onNavigate, actionState, onPin, onSendToChat }) {
  const meta = TYPE_META[type] || TYPE_META[item.type] || TYPE_META.messages;
  const route = type === 'messages' && item.id ? buildChatMessageHref(item.id) : (item.route || meta.route);
  const title = resultTitle(type, item);
  const snippet = resultSnippet(type, item);
  const parts = metaParts(type, item);
  const className = `search-result-card search-result-card--${type}`;
  const hubItem = getSearchHubItem(item);
  const hubItemId = getSearchHubItemId(item);
  const isPinned = !!(actionState?.pinned_to_home ?? hubItem?.pinned_to_home);
  const isPinning = actionState?.pinning;
  const isSending = actionState?.sending;
  const justSent = actionState?.sent;
  const actionDisabled = !hubItemId;
  const content = (
    <>
      {type === 'photos' && (item.thumbnail_url || item.url) && (
        <img className="search-result-thumb" src={item.thumbnail_url || item.url} alt="" loading="lazy" />
      )}
      {type === 'people' && (
        <span className="search-result-avatar">
          <UserAvatar
            nickname={item.title || 'Member'}
            size={40}
            avatarUrl={item.avatar_url}
            avatarEmoji={item.avatar_emoji}
          />
        </span>
      )}
      <div className="search-result-content">
        <div className="search-result-topline">
          <span className="search-result-badge">{meta.label}</span>
          {item.status && <span className={`search-status-chip status-${item.status}`}>{item.status}</span>}
        </div>
        <h3>{highlight(title, query)}</h3>
        {snippet && <p>{highlight(snippet, query)}</p>}
        {parts.length > 0 && (
          <div className="search-result-meta">
            {parts.map(part => <span key={part}>{part}</span>)}
          </div>
        )}
      </div>
    </>
  );

  return (
    <article className={`${className}${!route ? ' is-static' : ''}`}>
      {route ? (
        <button type="button" className="search-result-main" onClick={() => onNavigate?.(route)}>
          {content}
          <span className="search-result-arrow" aria-hidden="true">›</span>
        </button>
      ) : (
        <div className="search-result-main">{content}</div>
      )}
      <div className="search-result-actions" aria-label={`${title} quick actions`}>
        <button
          type="button"
          className={`search-result-action-btn${isPinned ? ' active' : ''}`}
          onClick={() => onPin?.(item)}
          disabled={actionDisabled || isPinning}
          aria-label={`${isPinned ? 'Unpin from' : 'Pin to'} homepage`}
          aria-pressed={isPinned}
          title={actionDisabled ? 'No linked hub item' : isPinned ? 'Unpin from homepage' : 'Pin to homepage'}
        >
          <span aria-hidden="true">📌</span>
        </button>
        <button
          type="button"
          className={`search-result-action-btn${justSent ? ' active' : ''}`}
          onClick={() => onSendToChat?.(item)}
          disabled={actionDisabled || isSending || justSent}
          aria-label="Send to chat"
          title={actionDisabled ? 'No linked hub item' : justSent ? 'Sent to chat' : 'Send to chat'}
        >
          <span aria-hidden="true">{justSent ? '✓' : '↗'}</span>
        </button>
      </div>
      {actionState?.error && <span className="search-result-action-error">{actionState.error}</span>}
    </article>
  );
}

function SearchResultSection({ type, items, query, onNavigate, actionStates = {}, onPin, onSendToChat }) {
  const meta = TYPE_META[type] || { label: type, icon: '?' };
  return (
    <section className="search-section" aria-labelledby={`search-section-${type}`}>
      <h2 id={`search-section-${type}`} className="search-section-title">
        <span className="search-section-icon" aria-hidden="true">{meta.icon}</span>
        <span>{meta.label}</span>
        <strong>{items.length}</strong>
      </h2>
      <div className="search-result-list">
        {items.map(item => (
          <SearchResultCard
            key={`${type}-${item.id}`}
            type={type}
            item={item}
            query={query}
            onNavigate={onNavigate}
            actionState={actionStates[getSearchHubItemId(item)] || null}
            onPin={onPin}
            onSendToChat={onSendToChat}
          />
        ))}
      </div>
    </section>
  );
}

function SearchBotChat({ messages, inputValue, onInputChange, onSubmit, isLoading, error, onRetry, onActionClick, draftStates, onAcceptDraft, onRejectDraft, hideInput = false }) {
  const bottomRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isLoading]);

  useEffect(() => {
    if (hideInput) return undefined;
    // Small delay so the keyboard doesn't fight layout on mobile
    const t = setTimeout(() => inputRef.current?.focus(), 80);
    return () => clearTimeout(t);
  }, [hideInput]);

  return (
    <div className="search-bot-chat">
      <div className="search-bot-chat__messages" aria-live="polite" aria-label="Hub Bot conversation">
        {messages.length === 0 && !isLoading && !error && (
          <div className="search-bot-chat__empty">
            Ask a question and Hub Bot will answer here.
          </div>
        )}
        {messages.map(msg => {
          const aiImageMatch = msg.role === 'bot' && msg.content?.match(/\[\[ai-image:((?:https?:\/\/|\/)[^\]]+)\]\]/i);
          const aiImageUrl = aiImageMatch ? aiImageMatch[1] : null;
          const msgText = aiImageUrl ? msg.content.replace(/\[\[ai-image:[^\]]+\]\]/i, '').trim() : msg.content;
          return (
          <div key={msg.id} className={`search-bot-msg-group search-bot-msg-group--${msg.role}`}>
            <div className={`search-bot-msg search-bot-msg--${msg.role}`}>
              {msg.role === 'bot' && <span className="search-bot-msg__avatar" aria-hidden="true">🤖</span>}
              <div className="search-bot-msg__bubble">
                {msgText && <p>{msgText}</p>}
                {aiImageUrl && <img src={aiImageUrl} alt="AI generated" style={{ maxWidth: '100%', borderRadius: '8px', marginTop: msgText ? '8px' : '0' }} />}
                {msg.suggestedActions?.length > 0 && (
                  <div className="search-bot-msg__actions">
                    {msg.suggestedActions.map(action => (
                      <button key={action} type="button" onClick={() => onActionClick(action)}>{action}</button>
                    ))}
                  </div>
                )}
              </div>
            </div>
            {msg.draftActions?.length > 0 && (
              <div className="search-bot-drafts">
                {msg.draftActions.map(draft => {
                  const st = draftStates?.[draft.id] || {};
                  const latestDraft = st.draft ? { ...draft, ...st.draft } : draft;
                  return (
                    <DraftActionCard
                      key={draft.id}
                      draftAction={latestDraft}
                      onAccept={onAcceptDraft}
                      onReject={onRejectDraft}
                      loading={!!st.loading}
                      error={st.error || null}
                    />
                  );
                })}
              </div>
            )}
            {msg.createdItems?.length > 0 && (
              <div className="search-bot-created-items">
                {msg.createdItems.map((item, i) => (
                  <a key={i} href={item.route} className="search-bot-created-item">
                    <span className="search-bot-created-item__badge">{item.item_type}</span>
                    <span className="search-bot-created-item__title">{item.title}</span>
                    <span className="search-bot-created-item__ref">{item.short_id}</span>
                    <span className="search-bot-created-item__arrow">→</span>
                  </a>
                ))}
              </div>
            )}
          </div>
        ); })}
        {isLoading && (
          <div className="search-bot-msg search-bot-msg--bot">
            <span className="search-bot-msg__avatar" aria-hidden="true">🤖</span>
            <div className="search-bot-msg__bubble search-bot-msg__bubble--thinking">
              <span /><span /><span />
            </div>
          </div>
        )}
        {error && (
          <div className="search-bot-chat__error" role="alert">
            <span>{error}</span>
            <button type="button" onClick={onRetry} disabled={isLoading}>Retry</button>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {!hideInput && (
      <form className="search-bot-chat__input-row" onSubmit={onSubmit}>
        <div className="search-bot-chat__input-shell">
          <label className="sr-only" htmlFor="search-bot-input">Message Hub Bot</label>
          <input
            ref={inputRef}
            id="search-bot-input"
            type="text"
            value={inputValue}
            onChange={e => onInputChange(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); onSubmit(e); } }}
            placeholder="Ask Hub Bot… /event /poll /image /idea /remind"
            aria-label="Message Hub Bot"
            disabled={isLoading}
          />
          <button type="submit" disabled={isLoading || !inputValue.trim()} aria-label="Send">
            <svg viewBox="0 0 24 24" aria-hidden="true" width="18" height="18" fill="currentColor">
              <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/>
            </svg>
          </button>
        </div>
      </form>
      )}
    </div>
  );
}

function resultRoute(type, item) {
  const meta = TYPE_META[type] || TYPE_META[item.type] || TYPE_META.messages;
  return type === 'messages' && item.id ? buildChatMessageHref(item.id) : (item.route || meta.route);
}

function buildVisibleResultHints(groupedResults, visibleTypes) {
  return visibleTypes.flatMap(type => (groupedResults[type] || []).map(item => ({
    type,
    id: item.id,
    title: resultTitle(type, item),
    snippet: resultSnippet(type, item),
    author: item.author || '',
    created_at: item.created_at || null,
    route: resultRoute(type, item),
    reference: item.reference || (item.id && (type === 'polls' || type === 'events' || type === 'reminders')
      ? _referenceForType(type, item.id)
      : null),
  }))).slice(0, 12);
}

function _referenceForType(type, id) {
  const prefix = { polls: 'P', events: 'E', reminders: 'R' }[type];
  return prefix ? `#${prefix}-${id}` : null;
}

export default function SearchPage({ query: initialQuery, onNavigate }) {
  const [activeMode, setActiveMode] = useState('search');
  const [modeQueries, setModeQueries] = useState({ ...DEFAULT_MODE_QUERIES, search: initialQuery || '' });
  const [results, setResults] = useState(null);
  const [photoResults, setPhotoResults] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);
  const [activeFilter, setActiveFilter] = useState('all');
  const [searchFilters, setSearchFilters] = useState({ sender: '' });
  const [photoFilters, setPhotoFilters] = useState({ dateFrom: '', dateTo: '', sourceType: '' });
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [openPhoto, setOpenPhoto] = useState(null);
  const [hasSearched, setHasSearched] = useState(false);
  const [hasSubmitted, setHasSubmitted] = useState(false);
  const [askMessages, setAskMessages] = useState([]);
  const [askError, setAskError] = useState(null);
  const [isAskLoading, setIsAskLoading] = useState(false);
  const [draftStates, setDraftStates] = useState({});
  const [resultActionStates, setResultActionStates] = useState({});
  const lastAskQuestion = useRef('');
  const inputRef = useRef(null);
  const lastRequest = useRef('');
  const toolbarRef = useRef(null);
  const [toolbarHeight, setToolbarHeight] = useState(0);

  useEffect(() => {
    setModeQueries(prev => ({ ...prev, search: initialQuery || '' }));
    if (initialQuery) setActiveMode('search');
  }, [initialQuery]);

  const query = modeQueries[activeMode] || '';
  const searchQuery = modeQueries.search || '';
  const photoQuery = modeQueries.photo || '';
  const aiQuery = modeQueries.ai || '';
  const searchParsedQuery = useMemo(() => parseQuery(searchQuery), [searchQuery]);
  const reference = useMemo(() => referenceResult(searchQuery), [searchQuery]);
  const searchableQuery = searchParsedQuery.cleaned || searchQuery.trim();
  const photoSearchQuery = photoQuery.trim();
  const activeFilterCount = (activeFilter !== 'all' ? 1 : 0) + (searchFilters.sender.trim() ? 1 : 0);
  const photoFilterCount = [photoFilters.dateFrom, photoFilters.dateTo, photoFilters.sourceType].filter(Boolean).length;

  const updateModeQuery = (mode, value) => {
    setModeQueries(prev => ({ ...prev, [mode]: value }));
  };

  const runSearch = async ({ force = false, full = false } = {}) => {
    const q = searchableQuery.trim();
    if (q.length < 2) {
      setResults(null);
      setPhotoResults([]);
      setError(null);
      setHasSearched(false);
      setHasSubmitted(false);
      return;
    }
    const typeParam = getTypeParam(activeFilter, searchParsedQuery.type);
    const requestKey = `${q}|${typeParam}|${full ? 'full' : 'instant'}`;
    if (!force && requestKey === lastRequest.current) return;
    lastRequest.current = requestKey;
    setIsLoading(true);
    setError(null);
    try {
      const data = await search(q, typeParam, full ? null : 6);
      setResults(data.results || {});
      setPhotoResults([]);
      setHasSearched(true);
      setHasSubmitted(full);
    } catch (err) {
      setError(err.message || 'Search failed');
    } finally {
      setIsLoading(false);
    }
  };

  const runPhotoSearch = async ({ force = false } = {}) => {
    const q = photoSearchQuery.trim();
    if (q.length < 2) {
      setPhotoResults([]);
      setError(null);
      setHasSearched(false);
      setHasSubmitted(false);
      return;
    }
    const requestKey = `${q}|photos|${photoFilters.dateFrom}|${photoFilters.dateTo}|${photoFilters.sourceType}`;
    if (!force && requestKey === lastRequest.current) return;
    lastRequest.current = requestKey;
    setIsLoading(true);
    setError(null);
    try {
      const data = await searchPhotos(q, {
        limit: force ? 30 : 8,
        dateFrom: photoFilters.dateFrom,
        dateTo: photoFilters.dateTo,
        sourceType: photoFilters.sourceType,
      });
      setResults({});
      setPhotoResults((data.results || []).filter(photo => photo.image_url));
      setHasSearched(true);
      setHasSubmitted(force);
    } catch (err) {
      setPhotoResults([]);
      setError(err.message || 'Photo search failed');
      setHasSearched(true);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    if (activeMode !== 'search') return undefined;
    const q = searchableQuery.trim();
    if (q.length < 2) {
      setResults(null);
      setPhotoResults([]);
      setError(null);
      setHasSearched(false);
      setHasSubmitted(false);
      return undefined;
    }
    const timer = setTimeout(() => {
      runSearch({ full: false });
    }, 320);

    return () => clearTimeout(timer);
  }, [activeMode, searchableQuery, activeFilter, searchParsedQuery.type]);

  useEffect(() => {
    if (activeMode !== 'photo') return undefined;
    const q = photoSearchQuery.trim();
    if (q.length < 2) {
      setPhotoResults([]);
      setError(null);
      setHasSearched(false);
      setHasSubmitted(false);
      return undefined;
    }
    const timer = setTimeout(() => {
      runPhotoSearch({ force: false });
    }, 360);

    return () => clearTimeout(timer);
  }, [activeMode, photoSearchQuery, photoFilters]);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  // The toolbar is fixed to the bottom of the viewport on mobile and its height
  // varies by mode (the Create panel only shows in search mode, the filter panel
  // expands, etc.). Measure it so results can reserve exactly enough room to
  // never hide behind the buttons.
  useEffect(() => {
    const el = toolbarRef.current;
    if (!el || typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(([entry]) => {
      setToolbarHeight(entry.target.offsetHeight);
    });
    observer.observe(el);
    setToolbarHeight(el.offsetHeight);
    return () => observer.disconnect();
  }, [activeMode, filtersOpen]);

  const groupedResults = useMemo(() => {
    const next = { ...(results || {}) };
    if (activeMode === 'photo' && photoResults.length > 0) {
      next.photos = photoResults;
    }
    if (activeMode === 'search' && reference && (activeFilter === 'all' || activeFilter === reference.type || searchParsedQuery.type === reference.type)) {
      next.references = [reference];
    }
    const senderFilter = searchFilters.sender.trim() || searchParsedQuery.operators.from;
    if (activeMode === 'search' && senderFilter) {
      const from = senderFilter.toLowerCase();
      Object.keys(next).forEach(type => {
        next[type] = (next[type] || []).filter(item => String(item.author || item.title || '').toLowerCase().includes(from));
      });
    }
    return next;
  }, [results, reference, activeFilter, searchParsedQuery, activeMode, photoResults, searchFilters.sender]);

  const counts = countsFor(groupedResults, null);
  const visibleTypes = TYPE_ORDER.filter(type => groupedResults[type]?.length);
  const visibleTotal = visibleTypes.reduce((sum, type) => sum + groupedResults[type].length, 0);
  const hasTyped = query.trim().length > 0;
  const canShowNoResults = hasSearched && !isLoading && hasTyped && !error && query.trim().length >= 2 && visibleTotal === 0;

  const sendAskQuestion = async (questionText) => {
    const question = (questionText || aiQuery).trim();
    if (!question || isAskLoading) return;
    lastAskQuestion.current = question;
    updateModeQuery('ai', '');
    setAskError(null);
    setIsAskLoading(true);
    setAskMessages(prev => [...prev, { id: `user-${Date.now()}`, role: 'user', content: question }]);
    try {
      const response = await apiFetch('/api/v1/ai/hub-bot-chat', {
        method: 'POST',
        body: JSON.stringify({ message: question }),
      });
      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || 'Hub Bot could not answer right now.');
      }
      const data = await response.json();
      setAskMessages(prev => [...prev, {
        id: `bot-${Date.now()}`,
        role: 'bot',
        content: data.reply,
        suggestedActions: data.suggested_actions || [],
        draftActions: data.draft_actions || [],
        createdItems: data.created_items || [],
      }]);
    } catch (err) {
      setAskError(err.message || 'Hub Bot could not answer right now.');
    } finally {
      setIsAskLoading(false);
    }
  };

  const retryAskQuestion = () => {
    if (lastAskQuestion.current) sendAskQuestion(lastAskQuestion.current);
  };

  const handleAcceptDraft = async (draftId) => {
    setDraftStates(prev => ({ ...prev, [draftId]: { ...prev[draftId], loading: true, error: null } }));
    try {
      const data = await acceptDraftAction(draftId);
      setDraftStates(prev => ({ ...prev, [draftId]: { loading: false, error: null, draft: data.draft_action } }));
      setAskMessages(prev => prev.map(msg => {
        if (!msg.draftActions) return msg;
        return { ...msg, draftActions: msg.draftActions.map(d => d.id === draftId ? { ...d, ...data.draft_action } : d) };
      }));
    } catch (err) {
      setDraftStates(prev => ({ ...prev, [draftId]: { ...prev[draftId], loading: false, error: err.message } }));
    }
  };

  const handleRejectDraft = async (draftId) => {
    setDraftStates(prev => ({ ...prev, [draftId]: { ...prev[draftId], loading: true, error: null } }));
    try {
      const data = await rejectDraftAction(draftId);
      setDraftStates(prev => ({ ...prev, [draftId]: { loading: false, error: null, draft: data.draft_action } }));
      setAskMessages(prev => prev.map(msg => {
        if (!msg.draftActions) return msg;
        return { ...msg, draftActions: msg.draftActions.map(d => d.id === draftId ? { ...d, ...data.draft_action } : d) };
      }));
    } catch (err) {
      setDraftStates(prev => ({ ...prev, [draftId]: { ...prev[draftId], loading: false, error: err.message } }));
    }
  };

  const applyHubItemToResults = (hubItem) => {
    if (!hubItem?.id) return;
    setResults(prev => {
      if (!prev) return prev;
      const next = {};
      Object.entries(prev).forEach(([type, items]) => {
        next[type] = (items || []).map(item => (
          getSearchHubItemId(item) === hubItem.id
            ? { ...item, hub_item: { ...(item.hub_item || {}), ...hubItem }, hub_item_id: hubItem.id, pinned_to_home: hubItem.pinned_to_home }
            : item
        ));
      });
      return next;
    });
  };

  const setResultActionState = (hubItemId, patch) => {
    setResultActionStates(prev => ({
      ...prev,
      [hubItemId]: { ...(prev[hubItemId] || {}), ...patch },
    }));
  };

  const handlePinResult = async (item) => {
    const hubItemId = getSearchHubItemId(item);
    if (!hubItemId) return;
    const current = resultActionStates[hubItemId]?.pinned_to_home ?? getSearchHubItem(item)?.pinned_to_home;
    setResultActionState(hubItemId, { pinning: true, error: null });
    try {
      const data = await pinHubItem(hubItemId, !current);
      applyHubItemToResults(data.item);
      setResultActionState(hubItemId, { pinning: false, pinned_to_home: data.item?.pinned_to_home, error: null });
    } catch (err) {
      setResultActionState(hubItemId, { pinning: false, error: err.message || 'Pin failed' });
    }
  };

  const handleSendResultToChat = async (item) => {
    const hubItemId = getSearchHubItemId(item);
    if (!hubItemId) return;
    setResultActionState(hubItemId, { sending: true, sent: false, error: null });
    try {
      const data = await sendHubItemToChat(hubItemId);
      applyHubItemToResults(data.item);
      setResultActionState(hubItemId, { sending: false, sent: true, error: null });
      window.setTimeout(() => setResultActionState(hubItemId, { sent: false }), 3000);
    } catch (err) {
      setResultActionState(hubItemId, { sending: false, sent: false, error: err.message || 'Send failed' });
    }
  };

  return (
    <section
      className={`page search-page search-page--${activeMode}`}
      style={toolbarHeight ? { '--search-toolbar-height': `${toolbarHeight}px` } : undefined}
    >
      <header className="search-hero">
        <p>Friend Hub Search</p>
        <h1>Find anything fast.</h1>
      </header>

      <div className="search-toolbar" ref={toolbarRef}>
        <SearchModeSelector
          activeMode={activeMode}
          onChange={(mode) => {
            setActiveMode(mode);
            setFiltersOpen(false);
            setError(null);
            lastRequest.current = '';
            window.setTimeout(() => inputRef.current?.focus(), 0);
          }}
        />
        <SearchInput
          value={query}
          mode={activeMode}
          onChange={(value) => updateModeQuery(activeMode, value)}
          onClear={() => {
            updateModeQuery(activeMode, '');
            if (activeMode === 'search') setActiveFilter('all');
            if (activeMode === 'photo') setPhotoResults([]);
            if (activeMode === 'search') setResults(null);
            setOpenPhoto(null);
            setHasSearched(false);
            setHasSubmitted(false);
            lastRequest.current = '';
            inputRef.current?.focus();
          }}
          onSubmit={() => {
            const q = query.trim();
            if (!q) return;
            if (activeMode === 'ai') sendAskQuestion(q);
            else if (activeMode === 'photo') runPhotoSearch({ force: true });
            else runSearch({ force: true, full: true });
          }}
          inputRef={inputRef}
        />

        {activeMode === 'search' && (
          <div className="search-context-row">
            <FilterToggle
              label="Filters"
              activeCount={activeFilterCount}
              expanded={filtersOpen}
              onClick={() => setFiltersOpen(open => !open)}
            />
          </div>
        )}
        {activeMode === 'photo' && (
          <div className="search-context-row">
            <FilterToggle
              label="Photo filters"
              activeCount={photoFilterCount}
              expanded={filtersOpen}
              onClick={() => setFiltersOpen(open => !open)}
            />
          </div>
        )}
        {activeMode === 'ai' && (
          <div className="search-ai-helper" aria-label="AI search examples">
            <span>Ask Hub Bot</span>
            <button type="button" onClick={() => updateModeQuery('ai', 'What happened this week?')}>What happened this week?</button>
            <button type="button" onClick={() => updateModeQuery('ai', 'Find decisions about the next plan')}>Find decisions</button>
          </div>
        )}

        {activeMode === 'search' && filtersOpen && (
          <SearchFilterPanel
            activeFilter={activeFilter}
            counts={counts}
            filters={searchFilters}
            onFilterChange={(filter) => {
              setActiveFilter(filter);
              lastRequest.current = '';
            }}
            onFiltersChange={(next) => {
              setSearchFilters(next);
              lastRequest.current = '';
            }}
            onClose={() => setFiltersOpen(false)}
          />
        )}
        {activeMode === 'photo' && filtersOpen && (
          <PhotoSearchFilters
            filters={photoFilters}
            onChange={(next) => {
              setPhotoFilters(next);
              lastRequest.current = '';
            }}
            onClose={() => setFiltersOpen(false)}
          />
        )}

        {activeMode === 'search' && (
          <CreateActions
            onCreate={(command) => {
              setActiveMode('ai');
              updateModeQuery('ai', command);
              setFiltersOpen(false);
              window.setTimeout(() => inputRef.current?.focus(), 0);
            }}
          />
        )}
      </div>

      {activeMode === 'ai' && (
        <div className="search-ai-results">
          <div className="search-results-summary">
            <span>AI answer</span>
            <strong>Hub Bot</strong>
          </div>
          <SearchBotChat
            messages={askMessages}
            inputValue={aiQuery}
            onInputChange={(value) => updateModeQuery('ai', value)}
            onSubmit={(e) => { e.preventDefault(); sendAskQuestion(); }}
            isLoading={isAskLoading}
            error={askError}
            onRetry={retryAskQuestion}
            onActionClick={sendAskQuestion}
            draftStates={draftStates}
            onAcceptDraft={handleAcceptDraft}
            onRejectDraft={handleRejectDraft}
            hideInput
          />
        </div>
      )}

      {activeMode !== 'ai' && isLoading && <SearchEmptyState variant="loading" query={query} />}
      {activeMode !== 'ai' && error && !isLoading && (
        <SearchEmptyState
          variant="error"
          query={query}
          message={error}
          onRetry={() => activeMode === 'photo' ? runPhotoSearch({ force: true }) : runSearch({ force: true, full: true })}
        />
      )}
      {activeMode !== 'ai' && canShowNoResults && <SearchEmptyState variant="none" query={query.trim()} />}
      {activeMode === 'search' && !hasTyped && !isLoading && !error && (
        <SearchEmptyState variant="idle" query="" />
      )}
      {activeMode === 'photo' && !hasTyped && !isLoading && !error && (
        <div className="search-state-card search-state-card--idle">
          <span>Photo matches</span>
          <h2>Describe what you remember.</h2>
          <p>Try “fish”, “group selfie”, “beach sunset”, or “food on a table”.</p>
        </div>
      )}

      {activeMode !== 'ai' && !isLoading && !error && visibleTotal > 0 && (
        <div className="search-results">
          <div className="search-results-summary">
            <span>
              {activeMode === 'photo'
                ? 'Photo matches'
                : hasSubmitted
                  ? `${visibleTotal} result${visibleTotal === 1 ? '' : 's'}`
                  : 'Suggestions'}
            </span>
            {activeMode === 'search' && searchParsedQuery.type && <strong>Filtered by {TYPE_META[searchParsedQuery.type]?.label}</strong>}
            {activeMode === 'search' && (searchParsedQuery.operators.from || searchFilters.sender) && <strong>From {searchParsedQuery.operators.from || searchFilters.sender}</strong>}
          </div>
          {visibleTypes.map(type => (
            activeMode === 'photo' && type === 'photos' ? (
              <PhotoSearchGrid
                key="photos"
                photos={groupedResults.photos}
                query={photoQuery.trim()}
                onOpen={setOpenPhoto}
                onNavigate={onNavigate}
              />
            ) : (
              <SearchResultSection
                key={type}
                type={type}
                items={groupedResults[type]}
                query={query.trim()}
                onNavigate={onNavigate}
                actionStates={resultActionStates}
                onPin={handlePinResult}
                onSendToChat={handleSendResultToChat}
              />
            )
          ))}
        </div>
      )}
      <PhotoSearchModal photo={openPhoto} onClose={() => setOpenPhoto(null)} onNavigate={onNavigate} />
    </section>
  );
}
