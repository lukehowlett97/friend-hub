import React, { useState, useRef, useEffect, useCallback } from 'react';
import { fetchHubItems, fetchMembers } from '../../services/api.js';

const STOP_TYPING_DELAY = 2000;
const UPLOAD_MAX_PX = 1920;
const UPLOAD_JPEG_QUALITY = 0.82;
const UPLOAD_MAX_BYTES = 4 * 1024 * 1024; // only resize if over 4 MB

function fileExtensionForMime(type) {
  if (type === 'image/png') return 'png';
  if (type === 'image/gif') return 'gif';
  if (type === 'image/webp') return 'webp';
  if (type === 'image/heic') return 'heic';
  if (type === 'image/heif') return 'heif';
  return 'jpg';
}

function normaliseImageFile(file, prefix = 'image') {
  if (!file || !file.type?.startsWith('image/')) return null;
  if (file.name) return file;
  const ext = fileExtensionForMime(file.type);
  return new File([file], `${prefix}-${Date.now()}.${ext}`, { type: file.type });
}

function resizeImageFile(file) {
  return new Promise((resolve) => {
    if (file.size <= UPLOAD_MAX_BYTES) { resolve(file); return; }
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      const scale = Math.min(1, UPLOAD_MAX_PX / Math.max(img.width, img.height));
      const canvas = document.createElement('canvas');
      canvas.width  = Math.round(img.width  * scale);
      canvas.height = Math.round(img.height * scale);
      canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height);
      canvas.toBlob(
        (blob) => resolve(blob ? new File([blob], file.name, { type: 'image/jpeg' }) : file),
        'image/jpeg',
        UPLOAD_JPEG_QUALITY,
      );
    };
    img.onerror = () => { URL.revokeObjectURL(url); resolve(file); };
    img.src = url;
  });
}
const DRAFT_KEY = 'friendHub.messageDraft';
const GIPHY_API_KEY = import.meta.env.VITE_GIPHY_API_KEY || '';
const GIF_FALLBACKS = [
  { id: 'excited', title: 'Excited', url: 'https://media.giphy.com/media/ICOgUNjpvO0PC/giphy.gif', preview: 'https://media.giphy.com/media/ICOgUNjpvO0PC/200.gif' },
  { id: 'yes', title: 'Yes', url: 'https://media.giphy.com/media/3o6UB3VhArvomJHtdK/giphy.gif', preview: 'https://media.giphy.com/media/3o6UB3VhArvomJHtdK/200.gif' },
  { id: 'dance', title: 'Dance', url: 'https://media.giphy.com/media/l0MYt5jPR6QX5pnqM/giphy.gif', preview: 'https://media.giphy.com/media/l0MYt5jPR6QX5pnqM/200.gif' },
  { id: 'clap', title: 'Clap', url: 'https://media.giphy.com/media/nbvFVPiEiJH6JOGIok/giphy.gif', preview: 'https://media.giphy.com/media/nbvFVPiEiJH6JOGIok/200.gif' },
  { id: 'laugh', title: 'Laughing', url: 'https://media.giphy.com/media/10JhviFuU2gWD6/giphy.gif', preview: 'https://media.giphy.com/media/10JhviFuU2gWD6/200.gif' },
  { id: 'wow', title: 'Wow', url: 'https://media.giphy.com/media/5VKbvrjxpVJCM/giphy.gif', preview: 'https://media.giphy.com/media/5VKbvrjxpVJCM/200.gif' },
];

function readDraft() {
  try { return sessionStorage.getItem(DRAFT_KEY) || ''; } catch { return ''; }
}
function saveDraft(text) {
  try { sessionStorage.setItem(DRAFT_KEY, text); } catch { /* quota */ }
}
function clearDraft() {
  try { sessionStorage.removeItem(DRAFT_KEY); } catch { /* quota */ }
}

function normaliseGifUrl(value) {
  const url = value.trim();
  if (!/^https?:\/\//i.test(url)) return '';
  return url;
}

// Detect the active #, @, or / trigger at the cursor.
// Returns { type: 'hub'|'person'|'slash', query, start } or null.
function getMentionAt(text, cursor) {
  const before = text.slice(0, cursor);
  const hub = before.match(/#(\S*)$/);
  if (hub) return { type: 'hub', query: hub[1], start: before.length - hub[0].length };
  const person = before.match(/@([^\s@]*)$/);
  if (person) return { type: 'person', query: person[1], start: before.length - person[0].length };
  // Only trigger slash menu when / is at the very start of the input (or after whitespace)
  const slash = before.match(/(^|\s)(\/[^\s]*)$/);
  if (slash) return { type: 'slash', query: slash[2].slice(1), start: before.length - slash[2].length };
  return null;
}

// Slash commands available for autocomplete
const SLASH_COMMANDS = [
  { cmd: '/event',     description: 'Create an event',    icon: '📅' },
  { cmd: '/poll',      description: 'Create a poll',      icon: '📊' },
  { cmd: '/image',     description: 'Generate an image',  icon: '🖼' },
  { cmd: '/idea',      description: 'Log an idea',        icon: '💡' },
  { cmd: '/remind',    description: 'Set a reminder',     icon: '⏰' },
  { cmd: '/summarise', description: 'Summarise chat',     icon: '📝' },
  { cmd: '/search',    description: 'Search chat history', icon: '🔍' },
];

// Hub item type badge colours
const HUB_BG    = { idea: '#fef9c3', poll: '#dbeafe', reminder: '#fce7f3', event: '#d1fae5', note: '#f3f4f6' };
const HUB_COLOR = { idea: '#854d0e', poll: '#1e40af', reminder: '#9d174d', event: '#065f46', note: '#374151' };
const HUB_BOT_SUGGESTION = {
  id: 'hub-bot',
  username: 'hub',
  nickname: 'Hub Bot',
  is_bot: true,
  is_online: true,
};

// Initials avatar for member suggestions
const MemberAvatar = ({ nickname }) => {
  const colors = ['#667eea','#f59e0b','#10b981','#f43f5e','#8b5cf6','#06b6d4'];
  let h = 0;
  for (const c of nickname || '') h = (h << 5) - h + c.charCodeAt(0);
  const bg = colors[Math.abs(h) % colors.length];
  return (
    <span className="mention-avatar" style={{ background: bg }}>
      {(nickname || '?')[0].toUpperCase()}
    </span>
  );
};

const MessageInput = ({
  onSendMessage,
  onEditMessage,
  initialDraft = '',
  disabled,
  placeholder = 'Message… /event /poll /image /idea /remind /summarise /search',
  onTyping,
  onStopTyping,
  onUploadPhoto,
  onSendGif,
  onSummarise,
  replyTo,
  onClearReply,
  editingMessage,
  onCancelEdit,
}) => {
  const [message, setMessage]         = useState(readDraft);
  const [hubItems, setHubItems]       = useState(null);
  const [members, setMembers]         = useState(null);
  const [mention, setMention]         = useState(null);
  const [suggIdx, setSuggIdx]         = useState(0);
  const [summarising, setSummarising] = useState(false);
  const [plusOpen, setPlusOpen] = useState(false);
  const [gifOpen, setGifOpen] = useState(false);
  const [gifQuery, setGifQuery] = useState('');
  const [gifResults, setGifResults] = useState(GIF_FALLBACKS);
  const [gifLoading, setGifLoading] = useState(false);
  const [gifError, setGifError] = useState('');
  const [gifUrl, setGifUrl] = useState('');
  const [imageUploading, setImageUploading] = useState(false);
  const isTypingRef             = useRef(false);
  const stopTypingTimerRef      = useRef(null);
  const inputRef                = useRef(null);
  const fileInputRef            = useRef(null);
  const cameraInputRef          = useRef(null);

  // ── Suggestion computation ────────────────────────────────────────────────

  const suggestions = (() => {
    if (!mention) return [];
    const q = mention.query.toLowerCase();

    if (mention.type === 'slash') {
      if (!q) return SLASH_COMMANDS;
      return SLASH_COMMANDS.filter(c => c.cmd.slice(1).startsWith(q) || c.description.toLowerCase().includes(q));
    }

    if (mention.type === 'hub') {
      if (!hubItems) return [];
      if (!q) return hubItems.slice(0, 8);
      return hubItems.filter(item => {
        const ref = item.short_id.toLowerCase().slice(1);
        return (
          ref.startsWith(q) ||
          item.title.toLowerCase().includes(q) ||
          item.type.toLowerCase().startsWith(q) ||
          item.tags?.some(t => t.toLowerCase().includes(q))
        );
      }).slice(0, 8);
    }

    if (mention.type === 'person') {
      const people = [HUB_BOT_SUGGESTION, ...(members || [])];
      if (!members) {
        if (!q || 'hub'.startsWith(q) || 'hub bot'.includes(q)) return [HUB_BOT_SUGGESTION];
        return [];
      }
      if (!q) return people.slice(0, 8);
      return people.filter(m =>
        m.username?.toLowerCase().startsWith(q) ||
        m.nickname?.toLowerCase().includes(q)
      ).slice(0, 8);
    }

    return [];
  })();

  // ── Lazy data fetching ────────────────────────────────────────────────────

  const loadHubItems = useCallback(() => {
    if (hubItems !== null) return;
    fetchHubItems({ limit: 100 })
      .then(data => setHubItems(data.items || []))
      .catch(() => setHubItems([]));
  }, [hubItems]);

  const loadMembers = useCallback(() => {
    if (members !== null) return;
    fetchMembers()
      .then(data => setMembers(data.members || []))
      .catch(() => setMembers([]));
  }, [members]);

  // ── Insert selected suggestion ────────────────────────────────────────────

  const insertSuggestion = useCallback((item) => {
    if (!mention) return;
    const before = message.slice(0, mention.start);
    const after  = message.slice(mention.start + 1 + mention.query.length);
    let token;
    if (mention.type === 'slash') {
      token = item.cmd + ' ';
    } else if (mention.type === 'hub') {
      token = item.short_id + ' ';
    } else {
      token = `@${item.username || item.nickname} `;
    }
    const next = `${before}${token}${after}`;
    setMessage(next);
    if (!editingMessage) saveDraft(next);
    setMention(null);
    setSuggIdx(0);
    requestAnimationFrame(() => {
      if (!inputRef.current) return;
      const pos = before.length + token.length;
      inputRef.current.focus();
      inputRef.current.setSelectionRange(pos, pos);
    });
  }, [mention, message, editingMessage]);

  const dismissMention = useCallback(() => {
    setMention(null);
    setSuggIdx(0);
  }, []);

  // ── Edit-mode pre-fill ────────────────────────────────────────────────────

  useEffect(() => {
    if (editingMessage) {
      setMessage(editingMessage.content);
      inputRef.current?.focus();
    } else {
      setMessage(readDraft());
    }
    dismissMention();
  }, [editingMessage?.id]);

  useEffect(() => {
    if (!initialDraft || editingMessage) return;
    setMessage(initialDraft);
    saveDraft(initialDraft);
    dismissMention();
    requestAnimationFrame(() => {
      if (!inputRef.current) return;
      const pos = initialDraft.length;
      inputRef.current.focus();
      inputRef.current.setSelectionRange(pos, pos);
    });
  }, [initialDraft, editingMessage, dismissMention]);

  useEffect(() => () => clearTimeout(stopTypingTimerRef.current), []);

  useEffect(() => {
    if (!gifOpen) return undefined;
    if (!GIPHY_API_KEY) {
      setGifResults(GIF_FALLBACKS);
      setGifLoading(false);
      setGifError('');
      return undefined;
    }

    let cancelled = false;
    const timer = setTimeout(async () => {
      setGifLoading(true);
      setGifError('');
      try {
        const params = new URLSearchParams({
          api_key: GIPHY_API_KEY,
          limit: '16',
          rating: 'pg-13',
        });
        const endpoint = gifQuery.trim() ? 'search' : 'trending';
        if (gifQuery.trim()) params.set('q', gifQuery.trim());
        const response = await fetch(`https://api.giphy.com/v1/gifs/${endpoint}?${params.toString()}`);
        if (!response.ok) throw new Error('Failed to load GIFs');
        const data = await response.json();
        const gifs = (data.data || []).map((gif) => ({
          id: gif.id,
          title: gif.title || 'GIF',
          url: gif.images?.original?.url || gif.images?.downsized?.url,
          preview: gif.images?.fixed_width_small?.url || gif.images?.downsized_still?.url,
        })).filter((gif) => gif.url && gif.preview);
        if (!cancelled) setGifResults(gifs.length ? gifs : GIF_FALLBACKS);
      } catch (err) {
        if (!cancelled) {
          setGifResults(GIF_FALLBACKS);
          setGifError(err.message || 'Failed to load GIFs');
        }
      } finally {
        if (!cancelled) setGifLoading(false);
      }
    }, 250);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [gifOpen, gifQuery]);

  useEffect(() => {
    const input = inputRef.current;
    if (!input) return undefined;

    const markKeyboardOpen = () => document.body.classList.add('chat-keyboard-open');
    const markKeyboardClosed = () => document.body.classList.remove('chat-keyboard-open');

    input.addEventListener('focus', markKeyboardOpen);
    input.addEventListener('blur', markKeyboardClosed);

    return () => {
      input.removeEventListener('focus', markKeyboardOpen);
      input.removeEventListener('blur', markKeyboardClosed);
      markKeyboardClosed();
    };
  }, []);

  // ── Typing indicators ─────────────────────────────────────────────────────

  const fireStopTyping = () => {
    if (isTypingRef.current) {
      isTypingRef.current = false;
      onStopTyping?.();
    }
  };

  // ── Input handlers ────────────────────────────────────────────────────────

  const handleChange = (e) => {
    const value  = e.target.value;
    const cursor = e.target.selectionStart ?? value.length;
    setMessage(value);
    if (!editingMessage) saveDraft(value);

    const m = getMentionAt(value, cursor);
    if (m) {
      setMention(m);
      setSuggIdx(0);
      if (m.type === 'hub')    loadHubItems();
      if (m.type === 'person') loadMembers();
    } else {
      setMention(null);
    }

    if (!disabled && !editingMessage) {
      if (value.trim() && !isTypingRef.current) {
        isTypingRef.current = true;
        onTyping?.();
      } else if (!value.trim() && isTypingRef.current) {
        clearTimeout(stopTypingTimerRef.current);
        fireStopTyping();
        return;
      }
      clearTimeout(stopTypingTimerRef.current);
      stopTypingTimerRef.current = setTimeout(fireStopTyping, STOP_TYPING_DELAY);
    }
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!message.trim() || disabled || imageUploading) return;
    clearTimeout(stopTypingTimerRef.current);
    fireStopTyping();
    dismissMention();
    if (editingMessage) {
      onEditMessage(editingMessage.id, message.trim());
      onCancelEdit?.();
    } else {
      onSendMessage(message, replyTo?.id);
      onClearReply?.();
      clearDraft();
    }
    setMessage('');
  };

  const handleSubmitPointerDown = (e) => {
    if (e.pointerType === 'mouse') return;
    e.preventDefault();
    handleSubmit(e);
  };

  const handleKeyDown = (e) => {
    if (mention && suggestions.length > 0) {
      if (e.key === 'ArrowDown') { e.preventDefault(); setSuggIdx(i => Math.min(i + 1, suggestions.length - 1)); return; }
      if (e.key === 'ArrowUp')   { e.preventDefault(); setSuggIdx(i => Math.max(i - 1, 0)); return; }
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); insertSuggestion(suggestions[suggIdx]); return; }
      if (e.key === 'Escape')    { e.preventDefault(); dismissMention(); return; }
    }
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    } else if (e.key === 'Escape' && editingMessage) {
      e.preventDefault();
      setMessage('');
      onCancelEdit?.();
    }
  };

  const uploadImageFiles = async (files) => {
    const imageFiles = files
      .map((file, index) => normaliseImageFile(file, `pasted-image-${index + 1}`))
      .filter(Boolean);
    if (!imageFiles.length || disabled || editingMessage || imageUploading) return;

    setImageUploading(true);
    try {
      for (const file of imageFiles) {
        const ready = await resizeImageFile(file);
        await onUploadPhoto?.(ready);
      }
    } finally {
      setImageUploading(false);
    }
  };

  const handlePhotoChange = async (event) => {
    const file = normaliseImageFile(event.target.files?.[0]);
    if (!file || disabled || editingMessage) return;
    await uploadImageFiles([file]);
    event.target.value = '';
  };

  const handlePaste = async (event) => {
    if (disabled || editingMessage || imageUploading) return;
    const items = Array.from(event.clipboardData?.items || []);
    const files = items
      .filter((item) => item.kind === 'file' && item.type.startsWith('image/'))
      .map((item) => item.getAsFile())
      .filter(Boolean);
    if (!files.length) return;

    event.preventDefault();
    dismissMention();
    setPlusOpen(false);
    setGifOpen(false);
    await uploadImageFiles(files);
  };

  const handleGifSelect = (gif) => {
    if (!gif?.url || disabled || editingMessage) return;
    onSendGif?.(gif);
    setGifOpen(false);
    setPlusOpen(false);
  };

  const handleGifUrlSubmit = (event) => {
    event.preventDefault();
    const url = normaliseGifUrl(gifUrl);
    if (!url || disabled || editingMessage) return;
    handleGifSelect({ title: 'GIF', url, preview: url });
    setGifUrl('');
  };

  const isEditMode  = !!editingMessage;
  const isReplyMode = !isEditMode && !!replyTo;

  return (
    <div className="message-input-container">

      {/* ── Mention / slash dropdown (above input) ── */}
      {mention && suggestions.length > 0 && (
        <div className="mention-dropdown">
          <p className="mention-dropdown-hint">
            {mention.type === 'slash' ? 'Commands' : mention.type === 'hub' ? 'Hub items' : 'Members'} — ↑↓ navigate · Enter select · Esc dismiss
          </p>
          {suggestions.map((item, idx) => (
            <button
              key={mention.type === 'slash' ? item.cmd : (item.id || item.username)}
              type="button"
              className={`mention-item${idx === suggIdx ? ' mention-item--active' : ''}`}
              onMouseDown={(e) => { e.preventDefault(); insertSuggestion(item); }}
            >
              {mention.type === 'slash' ? (
                <>
                  <span className="mention-item-slash-icon">{item.icon}</span>
                  <span className="mention-item-ref">{item.cmd}</span>
                  <span className="mention-item-title">{item.description}</span>
                </>
              ) : mention.type === 'hub' ? (
                <>
                  <span
                    className="mention-item-badge"
                    style={{ background: HUB_BG[item.type], color: HUB_COLOR[item.type] }}
                  >
                    {item.type}
                  </span>
                  <span className="mention-item-ref">{item.short_id}</span>
                  <span className="mention-item-title">{item.title}</span>
                  {item.status !== 'open' && <span className="mention-item-status">{item.status}</span>}
                </>
              ) : (
                <>
                  <MemberAvatar nickname={item.nickname} />
                  <span className="mention-item-name">{item.nickname}</span>
                  {item.username && <span className="mention-item-username">@{item.username}</span>}
                  {item.is_online && <span className="mention-item-online" />}
                </>
              )}
            </button>
          ))}
        </div>
      )}

      {/* Edit context banner */}
      {isEditMode && (
        <div className="edit-mode-badge">
          <span>✏️ Editing message</span>
          <button type="button" className="clear-reply-btn" onClick={onCancelEdit}>✕</button>
        </div>
      )}

      {/* Reply context banner */}
      {isReplyMode && (
        <div className="reply-to-badge">
          <span>↳ Replying to <strong>{replyTo.nickname}</strong></span>
          <button type="button" className="clear-reply-btn" onClick={onClearReply}>✕</button>
        </div>
      )}

      {/* ── Mobile + tray ── */}
      {plusOpen && !isEditMode && (
        <div className="plus-tray">
          <button
            type="button"
            className="plus-tray-pill"
            onClick={() => { cameraInputRef.current?.click(); setPlusOpen(false); }}
            disabled={disabled || imageUploading}
          >
            📷 Camera
          </button>
          <button
            type="button"
            className="plus-tray-pill"
            onClick={() => { fileInputRef.current?.click(); setPlusOpen(false); }}
            disabled={disabled || imageUploading}
          >
            🖼 Photos
          </button>
          <button
            type="button"
            className="plus-tray-pill"
            onClick={() => setGifOpen(open => !open)}
            disabled={disabled || imageUploading}
          >
            🎞 GIF
          </button>
          <button
            type="button"
            className="plus-tray-pill"
            disabled={disabled || imageUploading}
            onClick={() => {
              setPlusOpen(false);
              if (!message) {
                setMessage('/');
                setMention({ type: 'slash', query: '', start: 0 });
                setSuggIdx(0);
              }
              requestAnimationFrame(() => inputRef.current?.focus());
            }}
          >
            ⌨️ Commands
          </button>
        </div>
      )}

      {gifOpen && !isEditMode && (
        <div className="gif-keyboard" role="dialog" aria-label="GIF keyboard">
          <div className="gif-keyboard__bar">
            <input
              type="search"
              value={gifQuery}
              onChange={(event) => setGifQuery(event.target.value)}
              placeholder={GIPHY_API_KEY ? 'Search GIFs' : 'Search needs VITE_GIPHY_API_KEY'}
              disabled={disabled || !GIPHY_API_KEY}
              autoComplete="off"
            />
            <button type="button" onClick={() => setGifOpen(false)} aria-label="Close GIF keyboard">×</button>
          </div>
          {gifError && <div className="gif-keyboard__notice">{gifError}</div>}
          {!GIPHY_API_KEY && (
            <form className="gif-keyboard__url" onSubmit={handleGifUrlSubmit}>
              <input
                type="url"
                value={gifUrl}
                onChange={(event) => setGifUrl(event.target.value)}
                placeholder="Paste a GIF URL"
                disabled={disabled}
              />
              <button type="submit" disabled={disabled || !normaliseGifUrl(gifUrl)}>Send</button>
            </form>
          )}
          <div className="gif-keyboard__grid" aria-busy={gifLoading}>
            {gifResults.map((gif) => (
              <button
                key={gif.id || gif.url}
                type="button"
                className="gif-keyboard__item"
                onClick={() => handleGifSelect(gif)}
                disabled={disabled}
                title={gif.title}
              >
                <img src={gif.preview} alt={gif.title} loading="lazy" />
                <span>{gif.title}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      <form onSubmit={handleSubmit} className="message-input-form">
        <input
          ref={inputRef}
          type="text"
          value={message}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          onPaste={handlePaste}
          placeholder={isEditMode ? 'Edit message…' : placeholder}
          disabled={disabled || imageUploading}
          maxLength={1000}
          autoComplete="off"
        />
        {!isEditMode && (
          <>
            <input
              ref={fileInputRef}
              className="message-photo-input"
              type="file"
              accept="image/*"
              onChange={handlePhotoChange}
              disabled={disabled || imageUploading}
            />
            <input
              ref={cameraInputRef}
              className="message-photo-input"
              type="file"
              accept="image/*"
              capture="environment"
              onChange={handlePhotoChange}
              disabled={disabled || imageUploading}
            />
            {/* Desktop: inline buttons */}
            <button
              type="button"
              className="attach-photo-btn desktop-only"
              onClick={() => fileInputRef.current?.click()}
              disabled={disabled || imageUploading}
              title="Upload image"
            >
              {imageUploading ? 'Uploading…' : 'Image'}
            </button>
            <button
              type="button"
              className="attach-photo-btn desktop-only"
              onClick={() => setGifOpen(open => !open)}
              disabled={disabled || imageUploading}
              title="Open GIF keyboard"
            >
              GIF
            </button>
            {onSummarise && (
              <button
                type="button"
                className="attach-photo-btn desktop-only"
                disabled={disabled || summarising}
                title="Summarise last 24h of chat"
                onClick={async () => {
                  setSummarising(true);
                  try { await onSummarise(); } finally { setSummarising(false); }
                }}
              >
                {summarising ? '…' : 'Summary'}
              </button>
            )}
            {/* Mobile: + toggle */}
            <button
              type="button"
              className={`attach-photo-btn mobile-only plus-btn${plusOpen ? ' is-open' : ''}`}
              onClick={() => setPlusOpen(o => !o)}
              disabled={disabled || imageUploading}
              aria-label="More options"
            >
              +
            </button>
          </>
        )}
        <button
          type="submit"
          onPointerDown={handleSubmitPointerDown}
          disabled={disabled || imageUploading || !message.trim()}
        >
          {isEditMode ? 'Save' : 'Send'}
        </button>
      </form>
    </div>
  );
};

export default MessageInput;
