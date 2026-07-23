import React, { useEffect, useRef, useState } from 'react';
import { useDrag } from '@use-gesture/react';
import { formatTime, formatFullTimestamp } from '../../utils/helpers';
import { getColorForNickname } from '../../utils/colorUtils';
import { haptic } from '../../utils/haptics.js';
import ReactionPicker from '../Reactions/ReactionPicker.jsx';
import ReactionDisplay from '../Reactions/ReactionDisplay.jsx';
import MessageContextMenu from './MessageContextMenu.jsx';
import UserAvatar from './UserAvatar';
import HubItemPopup from './HubItemPopup.jsx';
import PersonPopup from './PersonPopup.jsx';
import AgendaPollCard from './AgendaPollCard.jsx';
import VoteActionCard from './VoteActionCard.jsx';
import MessageSources from './MessageSources.jsx';
import UserBadges from './UserBadges.jsx';
import { fetchDraftAction, fetchEventCard, fetchHubItemByRef } from '../../services/api.js';
import { extractMessageSources, stripMessageSources } from '../../utils/messageSources.js';
import { navigate as navigateTo } from '../../utils/navigate.js';

const AGENDA_MARKER_RE = /\[\[agenda-poll:(\d+)\]\]/i;
const VOTE_ACTION_MARKER_RE = /\[\[vote-action:(\d+)\]\]/i;
const AI_DRAFT_ACTION_MARKER_RE = /\[\[ai-draft-action:([0-9a-fA-F-]{36})\]\]/g;
const AI_IMAGE_MARKER_RE = /\[\[ai-image:((?:https?:\/\/|\/)[^\]]+)\]\]/i;
const HUB_ITEM_MARKER_RE = /\[\[hub-item:(#[A-Z]-\d+)\]\]/gi;
const HUB_ITEM_EVENT_MARKER_RE = /\[\[hub-item-event:(\d+)\]\]/gi;

const extractAiImage = (content = '') => {
  const match = content.match(AI_IMAGE_MARKER_RE);
  if (!match) return { imageUrl: null, stripped: content };
  return { imageUrl: match[1], stripped: content.replace(AI_IMAGE_MARKER_RE, '').trim() };
};

const extractAgendaPoll = (content = '') => {
  const match = content.match(AGENDA_MARKER_RE);
  if (!match) return { pollId: null, stripped: content };
  const pollId = Number(match[1]);
  const stripped = content.replace(AGENDA_MARKER_RE, '').trim();
  return { pollId: Number.isFinite(pollId) ? pollId : null, stripped };
};

const extractVoteAction = (content = '') => {
  const match = content.match(VOTE_ACTION_MARKER_RE);
  if (!match) return { voteActionId: null, stripped: content };
  const voteActionId = Number(match[1]);
  const stripped = content.replace(VOTE_ACTION_MARKER_RE, '').trim();
  return { voteActionId: Number.isFinite(voteActionId) ? voteActionId : null, stripped };
};

const extractDraftActions = (content = '') => {
  const draftActionIds = [];
  const stripped = content.replace(AI_DRAFT_ACTION_MARKER_RE, (_, id) => {
    draftActionIds.push(id);
    return '';
  }).trim();
  return { draftActionIds, stripped };
};

const extractHubItemMarkers = (content = '') => {
  const shortIds = [];
  const stripped = content.replace(HUB_ITEM_MARKER_RE, (_, shortId) => {
    shortIds.push(shortId);
    return '';
  }).trim();
  return { shortIds, stripped };
};

const extractHubItemEventMarkers = (content = '') => {
  const eventIds = [];
  const stripped = content.replace(HUB_ITEM_EVENT_MARKER_RE, (_, id) => {
    eventIds.push(Number(id));
    return '';
  }).trim();
  return { eventIds, stripped };
};

const DRAFT_ACTION_LINKS = {
  poll:     '/polls',
  event:    '/events',
  reminder: '/reminders',
};

function getMessageBadge(message) {
  if (message.display_role) return message.display_role;
  return 'Citizen';
}

// Style injected for the draft action link button used in chat.
const _DAC_LINK_STYLE_ID = 'dac-chat-link-styles';
if (typeof document !== 'undefined' && !document.getElementById(_DAC_LINK_STYLE_ID)) {
  const tag = document.createElement('style');
  tag.id = _DAC_LINK_STYLE_ID;
  tag.textContent = `
.dac-btn-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 8px 16px;
  border: none;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  background: #3b82f6;
  color: #fff;
  transition: background 0.15s, transform 0.1s;
  margin-top: 6px;
  text-decoration: none;
}
.dac-btn-link:hover { background: #2563eb; }
.dac-btn-link:active { transform: scale(0.97); }
`;
  document.head.appendChild(tag);
}

const _HUB_CARD_STYLE_ID = 'hub-chat-card-styles';
if (typeof document !== 'undefined' && !document.getElementById(_HUB_CARD_STYLE_ID)) {
  const tag = document.createElement('style');
  tag.id = _HUB_CARD_STYLE_ID;
  tag.textContent = `
.hub-chat-card {
  min-width: min(230px, 100%);
  max-width: 100%;
}
.hub-chat-card .dac-header {
  align-items: center;
  gap: 8px;
}
.hub-chat-ref {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  color: #6b7280;
  white-space: nowrap;
}
.hub-chat-title {
  margin: 8px 0 6px;
  font-size: 15px;
  line-height: 1.25;
  color: #111827;
  overflow-wrap: anywhere;
}
.hub-chat-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 0 0 8px;
}
.hub-chat-meta span {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  max-width: 100%;
  padding: 3px 7px;
  border-radius: 999px;
  background: #f3f4f6;
  color: #374151;
  font-size: 12px;
  line-height: 1.2;
}
.hub-chat-context {
  margin: 0 0 8px;
  color: #4b5563;
  font-size: 13px;
  line-height: 1.35;
  overflow-wrap: anywhere;
}
`;
  document.head.appendChild(tag);
}

function ChatDraftActionCard({ draftActionId }) {
  const [draftAction, setDraftAction] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    setDraftAction(null);

    fetchDraftAction(draftActionId)
      .then((draft) => {
        if (!cancelled) setDraftAction(draft);
      })
      .catch((err) => {
        if (!cancelled) setError(err.message || 'Failed to load draft action');
      });

    return () => {
      cancelled = true;
    };
  }, [draftActionId]);

  if (!draftAction) {
    return (
      <div className="dac-card">
        <div className="dac-title">{error || 'Loading draft...'}</div>
      </div>
    );
  }

  const { item_type, title, summary, payload_json = {} } = draftAction;
  const linkPath = DRAFT_ACTION_LINKS[item_type] || '/items';
  const typeMeta = { poll: { icon: '📊', label: 'Poll' }, event: { icon: '📅', label: 'Event' }, reminder: { icon: '🔔', label: 'Reminder' } };
  const meta = typeMeta[item_type] || { icon: '📌', label: item_type };

  return (
    <div className="dac-card" style={{ borderLeftColor: item_type === 'poll' ? '#3b82f6' : item_type === 'event' ? '#8b5cf6' : '#f59e0b' }}>
      <div className="dac-header">
        <span className="dac-type-badge" style={{ backgroundColor: item_type === 'poll' ? '#3b82f6' : item_type === 'event' ? '#8b5cf6' : '#f59e0b' }}>
          {meta.icon} {meta.label}
        </span>
      </div>
      <h4 className="dac-title">{title}</h4>
      {summary && <p className="dac-summary">{summary}</p>}
      <button
        type="button"
        className="dac-btn dac-btn-link"
        onClick={() => navigateTo(linkPath)}
      >
        Open in {meta.label.toLowerCase()}s →
      </button>
    </div>
  );
}

const HUB_ITEM_TYPE_META = {
  P: { icon: '📊', label: 'Poll',     color: '#3b82f6', route: '/polls' },
  E: { icon: '📅', label: 'Event',    color: '#8b5cf6', route: '/events' },
  R: { icon: '⏰', label: 'Reminder', color: '#f59e0b', route: '/reminders' },
  I: { icon: '💡', label: 'Idea',     color: '#10b981', route: '/ideas' },
  N: { icon: '📝', label: 'Note',     color: '#6b7280', route: '/items' },
};

function formatHubItemDateTime(iso) {
  if (!iso) return null;
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
}

function recurrenceLabel(item) {
  if (!item?.recurrence) return null;
  const until = item.recurrence_ends_at
    ? ` until ${new Date(item.recurrence_ends_at).toLocaleDateString([], { day: '2-digit', month: 'short' })}`
    : '';
  if (item.recurrence === 'daily') return `Repeats daily${until}`;
  if (item.recurrence === 'weekly') return `Repeats weekly${until}`;
  if (item.recurrence === 'every_N_days' && item.recurrence_days) {
    return `Repeats every ${item.recurrence_days} days${until}`;
  }
  return null;
}

function truncateText(value = '', max = 120) {
  const text = String(value || '').replace(/\s+/g, ' ').trim();
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

function HubItemCreatedCard({ shortId }) {
  // shortId format: #P-3, #E-12, etc.
  const [item, setItem] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setItem(null);
    setError(null);

    fetchHubItemByRef(shortId)
      .then((data) => {
        if (cancelled) return;
        if (data) setItem(data);
        else setError('Could not load item');
      })
      .catch((err) => {
        if (!cancelled) setError(err.message || 'Failed to load item');
      });

    return () => { cancelled = true; };
  }, [shortId]);

  const typeKey = shortId?.[1]?.toUpperCase();
  const meta = HUB_ITEM_TYPE_META[typeKey] || { icon: '📌', label: 'Item', color: '#6b7280', route: '/items' };
  const title = item?.title || (error ? 'Could not load item' : 'Loading item…');
  const body = item?.body && item.body !== item.title ? truncateText(item.body) : null;
  const dueAt = formatHubItemDateTime(item?.due_at);
  const repeat = recurrenceLabel(item);

  return (
    <div className="dac-card hub-chat-card" style={{ borderLeftColor: meta.color }}>
      <div className="dac-header">
        <span className="dac-type-badge" style={{ backgroundColor: meta.color }}>
          {meta.icon} {meta.label}
        </span>
        <span className="hub-chat-ref">{item?.short_id || shortId}</span>
      </div>

      <h4 className="hub-chat-title">{title}</h4>

      {(dueAt || repeat) && (
        <div className="hub-chat-meta">
          {dueAt && <span>Due {dueAt}</span>}
          {repeat && <span>{repeat}</span>}
        </div>
      )}

      {body && <p className="hub-chat-context">{body}</p>}

      <button
        type="button"
        className="dac-btn dac-btn-link"
        onClick={() => navigateTo(item?.type === 'event' && item?.source_id ? `/events/${item.source_id}` : meta.route)}
      >
        View in {meta.label.toLowerCase()}s →
      </button>
    </div>
  );
}

function EventCreatedCard({ eventId }) {
  const [event, setEvent] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    fetchEventCard(eventId)
      .then(data => { if (!cancelled) setEvent(data); })
      .catch(err => { if (!cancelled) setError(err.message || 'Failed to load event'); });
    return () => { cancelled = true; };
  }, [eventId]);

  const formatDt = (iso) => {
    if (!iso) return '';
    try {
      return new Date(iso).toLocaleString([], {
        weekday: 'short', day: '2-digit', month: 'short',
        hour: '2-digit', minute: '2-digit',
      });
    } catch { return iso; }
  };

  if (!event) {
    return (
      <div className="agenda-poll-card compact loading">
        <span>{error || 'Loading event…'}</span>
      </div>
    );
  }

  const total = (event.yes || 0) + (event.maybe || 0) + (event.no || 0);

  return (
    <div className="agenda-poll-card compact status-live">
      <div className="agenda-poll-card-head">
        <span className="agenda-poll-card-eyebrow">Event</span>
        {event.starts_at && (
          <span className="agenda-poll-card-badge badge-live" style={{ background: '#e9d5ff', color: '#5b21b6', animation: 'none' }}>
            {formatDt(event.starts_at)}
          </span>
        )}
      </div>

      <h4 className="agenda-poll-card-title">{event.title}</h4>

      {event.location && (
        <div className="agenda-poll-card-timing">
          <span>📍 {event.location}</span>
        </div>
      )}

      {total > 0 && (
        <div className="agenda-poll-card-timing">
          {event.yes > 0  && <span>✅ {event.yes} going</span>}
          {event.maybe > 0 && <><span className="dot">·</span><span>🤔 {event.maybe} maybe</span></>}
        </div>
      )}

      <div className="agenda-poll-card-actions">
        <button
          type="button"
          className="agenda-poll-card-link"
          onClick={() => navigateTo(`/events/${eventId}`)}
        >
          Open event →
        </button>
      </div>
    </div>
  );
}

const parsePhotoMessage = (content = '') => {
  if (!content || !content.includes('Photo: ')) return null;
  const lines = content.split('\n');
  if (lines.length < 2) return null;

  const title = lines[0].trim();
  const url = lines[1].trim();

  if (!title.startsWith('Photo: ') || !url.startsWith('/uploads/photos/')) {
    if (title.startsWith('Photo: ') || url.startsWith('/uploads/photos/')) {
      console.warn('Photo message parsing issue:', { title, url, content });
    }
    return null;
  }
  const label = title.replace('Photo: ', '').trim() || 'Shared photo';
  return {
    label,
    showLabel: !isBareFilename(label),
    url,
  };
};

// A bare filename (e.g. "image.png", "PXL_20240101.jpg") isn't a useful
// caption, so we don't show it under the image.
const isBareFilename = (text = '') => /^[^\s/]+\.[a-z0-9]{2,5}$/i.test(text.trim());

const parseGifMessage = (content = '') => {
  if (!content || !content.includes('GIF: ')) return null;
  const lines = content.split('\n');
  if (lines.length < 2) return null;

  const title = lines[0].trim();
  const url = lines[1].trim();
  if (!title.startsWith('GIF: ') || !/^https?:\/\//i.test(url)) return null;

  return {
    label: title.replace('GIF: ', '').trim() || 'GIF',
    url,
  };
};

const parseVideoMessage = (content = '') => {
  if (!content || !content.includes('Video: ')) return null;
  const lines = content.split('\n').map(l => l.trim()).filter(Boolean);
  if (lines.length < 2) return null;
  const title = lines[0];
  const url = lines[1];
  if (!title.startsWith('Video: ') || !url.startsWith('/uploads/videos/')) return null;
  return {
    label: title.replace('Video: ', '').trim() || 'Video',
    url,
    thumbnailUrl: lines[2]?.startsWith('/uploads/videos/') ? lines[2] : null,
  };
};

const parseAudioMessage = (content = '') => {
  if (!content || !content.includes('Audio: ')) return null;
  const lines = content.split('\n').map(l => l.trim()).filter(Boolean);
  if (lines.length < 2) return null;
  const title = lines[0];
  const url = lines[1];
  if (!title.startsWith('Audio: ') || !url.startsWith('/uploads/audio/')) return null;
  return {
    label: title.replace('Audio: ', '').trim() || 'Voice note',
    url,
  };
};

const IMAGE_URL_RE = /(https?:\/\/[^\s)>\]]+|\/uploads\/photos\/[^\s)>\]]+)/i;
const IMAGE_EXTENSION_RE = /\.(png|jpe?g|gif|webp|avif)(\?.*)?$/i;

function extractRawImageUrl(content = '') {
  const trimmed = String(content || '').trim();
  if (!trimmed) return null;

  const singleBracketAi = trimmed.match(/\[ai-image:((?:https?:\/\/|\/)[^\]]+)\]/i);
  if (singleBracketAi) return singleBracketAi[1];

  const match = trimmed.match(IMAGE_URL_RE);
  if (!match) return null;

  const url = match[1];
  if (
    url.startsWith('/uploads/photos/') ||
    /image\.pollinations\.ai\/prompt\//i.test(url) ||
    IMAGE_EXTENSION_RE.test(url)
  ) {
    return url;
  }

  return null;
}

const getReplyPreviewMedia = (content = '') => {
  const aiImage = extractAiImage(content);
  if (aiImage.imageUrl) {
    return { type: 'image', url: aiImage.imageUrl, label: aiImage.stripped || 'AI image' };
  }

  const photo = parsePhotoMessage(content);
  if (photo) return { type: 'image', url: photo.url, label: photo.label || 'Shared photo' };

  const gif = parseGifMessage(content);
  if (gif) return { type: 'image', url: gif.url, label: gif.label || 'GIF' };

  const video = parseVideoMessage(content);
  if (video) return { type: 'video', url: video.thumbnailUrl || null, label: video.label || 'Video' };

  const audio = parseAudioMessage(content);
  if (audio) return { type: 'audio', url: null, label: audio.label || 'Voice note' };

  const rawImageUrl = extractRawImageUrl(content);
  if (rawImageUrl) return { type: 'image', url: rawImageUrl, label: 'Image' };

  return null;
};

function ReplyQuotePreview({ content }) {
  const media = getReplyPreviewMedia(content);
  if (media) {
    return (
      <div className="reply-quote-media">
        {media.url ? (
          <img src={media.url} alt={media.label} loading="lazy" />
        ) : (
          <span className="reply-quote-media-placeholder">
            {media.type === 'video' ? '▶' : '🎙'}
          </span>
        )}
        <span>{media.label}</span>
      </div>
    );
  }

  return <p>{stripMessageSources(content)}</p>;
}

const renderMessageContent = (content = '', onRefClick, onPersonClick) => {
  // Matches:
  //  1. Default #X-N hub refs (X = I/P/R/E/N), optionally wrapped in **/__/` from AI replies
  //  2. Custom short_ids (e.g. #mike-rename): # + letter + 1-18 of letters/digits/hyphens/underscores
  //  3. @username person mentions
  const pattern = /(?:(\*\*|__|`)\s*)?(#(?:[IPRENipren][-\u2010\u2011\u2012\u2013\u2014\u2212]\d+|[A-Za-z][A-Za-z0-9_-]{1,18}))\b(?:\s*\1)?|@([a-z0-9_-]+)\b/g;
  const parts = [];
  let lastIndex = 0;
  for (const match of content.matchAll(pattern)) {
    if (match.index > lastIndex) parts.push(content.slice(lastIndex, match.index));
    if (match[2]) {
      // Hub item reference. For default-style #X-N, normalise letter case
      // (#p-1 and #P-1 resolve the same item); for custom tags, preserve case.
      const raw = match[2].slice(1); // drop leading '#'
      const isDefaultForm = /^[IPRENipren][-‐‑‒–—−]\d+$/.test(raw);
      const ref = isDefaultForm ? raw.toUpperCase() : raw;
      const label = `#${ref}`;
      parts.push(
        <button
          key={`hub-${match.index}`}
          type="button"
          className="hub-reference-link"
          onClick={(e) => { e.stopPropagation(); onRefClick(ref); }}
        >
          {label}
        </button>,
      );
    } else {
      // Person mention — clickable
      const uname = match[3];
      parts.push(
        <button
          key={`mention-${match.index}`}
          type="button"
          className="person-mention"
          onClick={(e) => { e.stopPropagation(); onPersonClick?.(uname); }}
        >
          {match[0]}
        </button>,
      );
    }
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < content.length) parts.push(content.slice(lastIndex));
  return parts.length ? parts : content;
};

// ── Bot reply rendering ─────────────────────────────────────────────────────
// Hub Bot replies arrive as plain text with light markdown (**bold**, `code`,
// "- " bullets). Render that as a scannable structure instead of a raw blob,
// while keeping #ref / @mention links working inside each segment.

const BOT_INLINE_RE = /\*\*([^*\n]+)\*\*|`([^`\n]+)`/g;
const BOT_LIST_LINE_RE = /^\s*(?:[-*•]|\d+[.)])\s+/;
const BOT_HEADING_LINE_RE = /^\*\*[^*\n]+\*\*:?\s*$/;

const renderBotInline = (text, onRefClick, onPersonClick, keyPrefix) => {
  const parts = [];
  let lastIndex = 0;
  for (const match of text.matchAll(BOT_INLINE_RE)) {
    if (match.index > lastIndex) {
      parts.push(
        <React.Fragment key={`${keyPrefix}-t${lastIndex}`}>
          {renderMessageContent(text.slice(lastIndex, match.index), onRefClick, onPersonClick)}
        </React.Fragment>,
      );
    }
    if (match[1] !== undefined) {
      parts.push(
        <strong key={`${keyPrefix}-b${match.index}`}>
          {renderMessageContent(match[1], onRefClick, onPersonClick)}
        </strong>,
      );
    } else {
      parts.push(
        <code key={`${keyPrefix}-c${match.index}`} className="bot-inline-code">{match[2]}</code>,
      );
    }
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < text.length) {
    parts.push(
      <React.Fragment key={`${keyPrefix}-t${lastIndex}`}>
        {renderMessageContent(text.slice(lastIndex), onRefClick, onPersonClick)}
      </React.Fragment>,
    );
  }
  return parts.length ? parts : renderMessageContent(text, onRefClick, onPersonClick);
};

function BotMessageBody({ content, onRefClick, onPersonClick }) {
  const blocks = [];
  const chunks = String(content || '').split(/\n{2,}/);

  chunks.forEach((chunk, chunkIdx) => {
    const lines = chunk.split('\n').map((line) => line.trim()).filter(Boolean);
    if (!lines.length) return;

    let paraLines = [];
    let listLines = [];

    const flushPara = () => {
      if (!paraLines.length) return;
      const key = `${chunkIdx}-p${blocks.length}`;
      blocks.push(
        <p key={key} className="bot-para">
          {paraLines.map((line, i) => (
            <React.Fragment key={i}>
              {i > 0 && <br />}
              {renderBotInline(line, onRefClick, onPersonClick, `${key}-l${i}`)}
            </React.Fragment>
          ))}
        </p>,
      );
      paraLines = [];
    };

    const flushList = () => {
      if (!listLines.length) return;
      const key = `${chunkIdx}-ul${blocks.length}`;
      blocks.push(
        <ul key={key} className="bot-list">
          {listLines.map((line, i) => (
            <li key={i}>{renderBotInline(line, onRefClick, onPersonClick, `${key}-l${i}`)}</li>
          ))}
        </ul>,
      );
      listLines = [];
    };

    lines.forEach((line) => {
      if (BOT_LIST_LINE_RE.test(line)) {
        flushPara();
        listLines.push(line.replace(BOT_LIST_LINE_RE, ''));
      } else if (BOT_HEADING_LINE_RE.test(line)) {
        flushPara();
        flushList();
        const key = `${chunkIdx}-h${blocks.length}`;
        blocks.push(
          <div key={key} className="bot-heading bot-h3">
            {line.replace(/^\*\*|\*\*:?\s*$/g, '')}
          </div>,
        );
      } else {
        flushList();
        paraLines.push(line);
      }
    });
    flushPara();
    flushList();
  });

  return <div className="bot-markdown">{blocks}</div>;
}

const Message = ({
  message,
  isMe,
  currentSessionId,
  showActions,   // controlled by MessageList — true when this message is tapped
  onTap,         // notify MessageList that this message was tapped
  onReply,
  onToggleReaction,
  onDeleteMessage,
  onEditMessage,
  onPinMessage,
  canPin = false,
  onOpenPhoto,
  onQuoteClick,
  quickEmojis,
}) => {
  const [showReactionPicker, setShowReactionPicker] = useState(false);
  const reactionPickerRef = useRef(null);
  const [activeHubRef, setActiveHubRef]     = useState(null);
  const [activePersonRef, setActivePersonRef] = useState(null);
  const [activePersonSession, setActivePersonSession] = useState(null);
  const [contextMenuOpen, setContextMenuOpen] = useState(false);
  const isBot = message.is_bot === true;
  const [swipeX, setSwipeX] = useState(0);
  const [isSpringing, setIsSpringing] = useState(false);
  const longPressTimerRef = useRef(null);
  const longPressHapticRef = useRef(null);
  const swipeFiredRef = useRef(false);
  const prefersReducedMotion = typeof window !== 'undefined'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // Close the reaction picker when clicking outside it or pressing Escape.
  useEffect(() => {
    if (!showReactionPicker) return;
    const handlePointer = (e) => {
      if (reactionPickerRef.current && !reactionPickerRef.current.contains(e.target)) {
        setShowReactionPicker(false);
      }
    };
    const handleKey = (e) => {
      if (e.key === 'Escape') setShowReactionPicker(false);
    };
    document.addEventListener('mousedown', handlePointer);
    document.addEventListener('touchstart', handlePointer);
    document.addEventListener('keydown', handleKey);
    return () => {
      document.removeEventListener('mousedown', handlePointer);
      document.removeEventListener('touchstart', handlePointer);
      document.removeEventListener('keydown', handleKey);
    };
  }, [showReactionPicker]);

  // Swipe-to-reply via @use-gesture/react
  const bindDrag = useDrag(({ movement: [mx], direction: [dx], down, cancel, first }) => {
    if (first) { swipeFiredRef.current = false; }
    // Only allow swipe in the correct direction. Outgoing messages keep their
    // existing rightward swipe; incoming messages now reply on the opposite drag.
    const correctDir = mx > 0;
    if (!correctDir) { cancel(); return; }
    const capped = Math.min(Math.abs(mx), 72);
    if (down) {
      setSwipeX(capped);
    } else {
      if (Math.abs(mx) > 60 && !swipeFiredRef.current) {
        swipeFiredRef.current = true;
        haptic(30);
        onReply(message.id, message.content, message.nickname);
      }
      if (!prefersReducedMotion) setIsSpringing(true);
      setSwipeX(0);
    }
  }, {
    axis: 'x',
    filterTaps: true,
    pointer: { touch: true },
  });

  const handleSpringEnd = () => setIsSpringing(false);

  // Long-press to open context menu
  const startLongPress = (e) => {
    // Ignore if already on a button/link
    if (e.target.closest('button, a, input')) return;
    longPressHapticRef.current = setTimeout(() => haptic([10, 50, 10]), 350);
    longPressTimerRef.current = setTimeout(() => {
      setContextMenuOpen(true);
    }, 500);
  };
  const cancelLongPress = () => {
    clearTimeout(longPressTimerRef.current);
    clearTimeout(longPressHapticRef.current);
  };

  // ── System messages ──────────────────────────────────────────────────────
  if (message.type === 'system' || message.type === 'error') {
    return (
      <div className="message system">
        <div className="system-message">
          <span className="timestamp">{formatTime(message.timestamp)}</span>
          <span className="content">{message.content}</span>
        </div>
      </div>
    );
  }

  // ── Chat messages ────────────────────────────────────────────────────────
  const senderColor = getColorForNickname(message.nickname || '');
  const senderName = message.nickname || message.sender || 'Unknown';
  const messageBadge = getMessageBadge(message);
  const isDeleted   = message.isDeleted || message.is_deleted;
  const isEdited    = !isDeleted && (message.isEdited || !!message.edited_at);
  const photoMessage = !isDeleted ? parsePhotoMessage(message.content) : null;
  const gifMessage = !isDeleted ? parseGifMessage(message.content) : null;
  const videoMessage = !isDeleted ? parseVideoMessage(message.content) : null;
  const audioMessage = !isDeleted ? parseAudioMessage(message.content) : null;
  const aiImage = !isDeleted ? extractAiImage(message.content || '') : { imageUrl: null, stripped: message.content };
  const agenda = !isDeleted ? extractAgendaPoll(aiImage.stripped || '') : { pollId: null, stripped: message.content };
  const voteAction = !isDeleted ? extractVoteAction(agenda.stripped || '') : { voteActionId: null, stripped: message.content };
  const draftActions = !isDeleted ? extractDraftActions(voteAction.stripped || '') : { draftActionIds: [], stripped: message.content };
  const hubItemMarkers = !isDeleted ? extractHubItemMarkers(draftActions.stripped || '') : { shortIds: [], stripped: message.content };
  const hubItemEventMarkers = !isDeleted ? extractHubItemEventMarkers(hubItemMarkers.stripped || '') : { eventIds: [], stripped: message.content };
  // Bot replies may end with a "Sources: [1] /chat?message=… " block; pull it
  // out so it renders as chips instead of raw URLs in the answer text.
  const sourcesParsed = isBot && !isDeleted
    ? extractMessageSources(hubItemEventMarkers.stripped || '')
    : { sources: [], stripped: hubItemEventMarkers.stripped };
  const botSources = sourcesParsed.sources;
  const hasAiImage = !!aiImage.imageUrl;
  const hasAgendaCard = !!agenda.pollId;
  const hasVoteActionCard = !!voteAction.voteActionId;
  const hasDraftActionCards = draftActions.draftActionIds.length > 0;
  const hasHubItemCards = hubItemMarkers.shortIds.length > 0;
  const hasEventCards = hubItemEventMarkers.eventIds.length > 0;
  const renderableContent = hasAiImage || hasAgendaCard || hasVoteActionCard || hasDraftActionCards || hasHubItemCards || hasEventCards || botSources.length > 0
    ? sourcesParsed.stripped
    : message.content;
  const openSenderProfile = () => {
    if (message.session_id) setActivePersonSession(message.session_id);
    else if (message.username) setActivePersonRef(message.username);
  };

  // Clicking the bubble toggles actions (desktop hover still works via CSS).
  // Clicks originating inside the action row or picker are ignored so that
  // button presses don't immediately close the panel.
  const handleBubbleClick = (e) => {
    if (
      e.target.closest('.message-actions') ||
      e.target.closest('.reaction-picker') ||
      e.target.closest('.reply-quote') ||
      e.target.closest('.photo-message-button') ||
      e.target.closest('.gif-message-content') ||
      e.target.closest('.video-message-content') ||
      e.target.closest('.audio-message-content')
    ) return;
    onTap?.();
  };

  return (
    <div
      className={`message chat ${isMe ? 'me' : 'other'}${isBot ? ' bot' : ''}${showActions ? ' show-actions' : ''}${message.is_new_outgoing ? ' message--send-fly' : ''}`}
      onClick={handleBubbleClick}
      onPointerDown={startLongPress}
      onPointerUp={cancelLongPress}
      onPointerMove={cancelLongPress}
      onPointerCancel={cancelLongPress}
    >
      <div
        className="message-row"
        {...bindDrag()}
        style={{
          transform: swipeX !== 0 ? `translateX(${swipeX}px)` : undefined,
          transition: isSpringing ? 'transform 0.25s cubic-bezier(0.34,1.56,0.64,1)' : 'none',
        }}
        onTransitionEnd={handleSpringEnd}
      >
        {/* Swipe reply arrow indicator */}
        <div
          className={`swipe-reply-arrow${isMe ? ' swipe-reply-arrow--me' : ''}`}
          style={{ opacity: Math.min(Math.abs(swipeX) / 60, 1) }}
          aria-hidden="true"
        >
          ↩
        </div>
        <button
          type="button"
          className="message-avatar-btn"
          onClick={(e) => {
            e.stopPropagation();
            openSenderProfile();
          }}
          disabled={!message.session_id && !message.username}
          aria-label={`Open ${message.nickname || 'member'} profile`}
        >
          <UserAvatar
            nickname={message.nickname}
            size={32}
            avatarUrl={message.avatar_url}
            avatarEmoji={message.avatar_emoji || (isBot ? '🤖' : null)}
          />
        </button>

        <div className="message-body">

        {/* Reply-to quote */}
        {message.reply_to && (
          <button
            type="button"
            className="reply-quote"
            onClick={(e) => {
              e.stopPropagation();
              onQuoteClick?.(message.reply_to.id);
            }}
            disabled={!message.reply_to.id}
            aria-label={`Jump to ${message.reply_to.nickname || 'the original message'}'s message`}
            title="Jump to original message"
          >
            <span className="reply-quote-indicator" aria-hidden="true">↳</span>
            <div className="reply-quote-content">
              <strong>{message.reply_to.nickname}</strong>
              <ReplyQuotePreview content={message.reply_to.content || ''} />
            </div>
          </button>
        )}

        {/* Bubble */}
        <div className="chat-message">
          <div className="message-header">
            <span className="sender" style={{ color: isMe ? undefined : senderColor }}>
              {isMe ? (
                <span className="sender-name-current">You</span>
              ) : (
                <button
                  type="button"
                  className="sender-name-btn"
                  onClick={(e) => { e.stopPropagation(); openSenderProfile(); }}
                  disabled={!message.session_id && !message.username}
                  title={message.session_id || message.username ? 'View profile' : undefined}
                >
                  {senderName}
                </button>
              )}
              {isBot && <span className="bot-badge">BOT</span>}
              {!isBot && messageBadge && (
                <span
                  className={`role-badge role-badge--${message.display_role ? 'custom' : 'default'}`}
                  title={messageBadge}
                >
                  {messageBadge}
                </span>
              )}
            </span>
            {message.is_pinned && (
              <span className="pinned-tag" title="Pinned to noticeboard" aria-label="Pinned">📌</span>
            )}
            <span className="timestamp" title={formatFullTimestamp(message.timestamp)}>
              {formatTime(message.timestamp)}
            </span>
          </div>
          {isDeleted ? (
            <div className="message-content deleted-message">[message deleted]</div>
          ) : photoMessage ? (
            <button
              type="button"
              className="message-content photo-message-content photo-message-button"
              onClick={() => onOpenPhoto?.(photoMessage)}
            >
              <img src={photoMessage.url} alt={photoMessage.label} />
              {photoMessage.showLabel && <span>{photoMessage.label}</span>}
            </button>
          ) : gifMessage ? (
            <div className="message-content gif-message-content">
              <img src={gifMessage.url} alt={gifMessage.label} loading="lazy" />
              <span>{gifMessage.label}</span>
            </div>
          ) : videoMessage ? (
            <div className="message-content video-message-content">
              <video
                controls
                preload="metadata"
                poster={videoMessage.thumbnailUrl || undefined}
                style={{ maxWidth: '100%', maxHeight: '320px', borderRadius: '8px', display: 'block' }}
              >
                <source src={videoMessage.url} />
                Your browser does not support video.
              </video>
              <span className="media-label">{videoMessage.label}</span>
            </div>
          ) : audioMessage ? (
            <div className="message-content audio-message-content">
              <audio controls preload="metadata" style={{ width: '100%', maxWidth: '320px' }}>
                <source src={audioMessage.url} />
                Your browser does not support audio.
              </audio>
              <span className="media-label">{audioMessage.label}</span>
            </div>
          ) : (
            <>
              {renderableContent && (
                <div className="message-content">
                  {isBot ? (
                    <BotMessageBody
                      content={renderableContent}
                      onRefClick={setActiveHubRef}
                      onPersonClick={setActivePersonRef}
                    />
                  ) : (
                    renderMessageContent(renderableContent, setActiveHubRef, setActivePersonRef)
                  )}
                </div>
              )}
              {hasAiImage && (
                <button
                  type="button"
                  className="ai-generated-image-button"
                  onClick={() => onOpenPhoto?.({
                    url: aiImage.imageUrl,
                    label: aiImage.stripped?.trim() || 'AI generated image',
                    caption: aiImage.stripped?.trim() || null,
                    showSeeInPhotos: true,
                  })}
                  aria-label="Open AI generated image"
                >
                  <img
                    src={aiImage.imageUrl}
                    alt={aiImage.stripped?.trim() || 'AI generated'}
                    className="ai-generated-image"
                    style={{ maxWidth: '100%', borderRadius: '8px', marginTop: '6px' }}
                  />
                </button>
              )}
              {hasAgendaCard && (
                <AgendaPollCard
                  pollId={agenda.pollId}
                  compact
                  onNavigate={(path) => navigateTo(path)}
                />
              )}
              {hasVoteActionCard && (
                <VoteActionCard
                  voteActionId={voteAction.voteActionId}
                  compact
                />
              )}
              {hasDraftActionCards && draftActions.draftActionIds.map((draftActionId) => (
                <ChatDraftActionCard
                  key={draftActionId}
                  draftActionId={draftActionId}
                />
              ))}
              {hasHubItemCards && hubItemMarkers.shortIds.map((shortId) => (
                <HubItemCreatedCard key={shortId} shortId={shortId} />
              ))}
              {hasEventCards && hubItemEventMarkers.eventIds.map((eventId) => (
                <EventCreatedCard key={eventId} eventId={eventId} />
              ))}
            </>
          )}

          {isEdited && <span className="edited-tag">(edited)</span>}
        </div>

        {/* Reactions */}
        {!isDeleted && message.reactions?.length > 0 && (
          <ReactionDisplay
            reactions={message.reactions}
            currentSessionId={currentSessionId}
            targetType="message"
            targetId={message.id}
          />
        )}

        {/* Actions — revealed by CSS hover on desktop, by .show-actions on mobile */}
        {!isDeleted && (
          <div className={`message-actions${showReactionPicker ? ' picker-open' : ''}`}>

            <div className="reaction-picker-wrapper" ref={reactionPickerRef}>
              <button
                className="action-btn"
                onClick={() => setShowReactionPicker(p => !p)}
                title="Add reaction"
              >
                😊
              </button>
              <ReactionPicker
                isOpen={showReactionPicker}
                quickEmojis={quickEmojis}
                onSelect={(emoji) => {
                  onToggleReaction(message.id, emoji);
                  setShowReactionPicker(false);
                }}
              />
            </div>

            <button
              className="action-btn"
              onClick={() => onReply(message.id, message.content, message.nickname)}
              title="Reply"
            >
              ↩
            </button>

            {canPin && (
              <button
                className={`action-btn${message.is_pinned ? ' action-btn-active' : ''}`}
                onClick={() => onPinMessage?.(message.id, !message.is_pinned)}
                title={message.is_pinned ? 'Unpin message' : 'Pin to noticeboard'}
                aria-pressed={!!message.is_pinned}
              >
                📌
              </button>
            )}

            {isMe && (
              <button
                className="action-btn"
                onClick={() => onEditMessage({ id: message.id, content: message.content })}
                title="Edit"
              >
                ✏️
              </button>
            )}

            {isMe && (
              <button
                className="action-btn action-btn-danger"
                onClick={() => onDeleteMessage(message.id)}
                title="Delete"
              >
                🗑️
              </button>
            )}

          </div>
        )}

        </div>
      </div>

      {activeHubRef && (
        <HubItemPopup shortRef={activeHubRef} onClose={() => setActiveHubRef(null)} />
      )}
      {activePersonRef && (
        <PersonPopup username={activePersonRef} onClose={() => setActivePersonRef(null)} />
      )}
      {activePersonSession && (
        <PersonPopup sessionId={activePersonSession} onClose={() => setActivePersonSession(null)} />
      )}
      {contextMenuOpen && (
        <MessageContextMenu
          message={message}
          isMe={isMe}
          quickEmojis={quickEmojis}
          onReaction={(emoji) => { onToggleReaction(message.id, emoji); setContextMenuOpen(false); }}
          onReply={() => { onReply(message.id, message.content, message.nickname); setContextMenuOpen(false); }}
          onEdit={() => { onEditMessage({ id: message.id, content: message.content }); setContextMenuOpen(false); }}
          onDelete={() => { onDeleteMessage(message.id); setContextMenuOpen(false); }}
          onClose={() => setContextMenuOpen(false)}
        />
      )}
    </div>
  );
};

export default Message;
