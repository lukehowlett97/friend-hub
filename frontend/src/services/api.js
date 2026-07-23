import { apiFetch } from '../api/client.js';

const SESSION_KEY = 'friendHub.sessionId';
const NICKNAME_KEY = 'friendHub.nickname';

export function getStoredSessionId() {
  return window.localStorage.getItem(SESSION_KEY);
}

export function storeSession(sessionId, nickname) {
  window.localStorage.setItem(SESSION_KEY, sessionId);
  if (nickname) window.localStorage.setItem(NICKNAME_KEY, nickname);
}

export function clearStoredSession() {
  window.localStorage.removeItem(SESSION_KEY);
  window.localStorage.removeItem(NICKNAME_KEY);
}

function sessionHeaders() {
  const sessionId = getStoredSessionId();
  return sessionId ? { 'X-Session-Id': sessionId } : {};
}

export async function fetchMembers(options = {}) {
  const params = new URLSearchParams();
  if (options.includeBots) params.set('include_bots', 'true');
  const url = params.toString() ? `/api/v1/members?${params.toString()}` : '/api/v1/members';
  const response = await apiFetch(url);

  if (!response.ok) {
    throw new Error('Failed to fetch members');
  }

  return response.json();
}

export async function updateMemberRole(memberId, role) {
  const response = await apiFetch(`/api/v1/members/${memberId}/role`, {
    method: 'PATCH',
    body: JSON.stringify({ role }),
  });

  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || 'Failed to update role');
  }

  return response.json();
}

export async function fetchMessages(limit = 5, options = {}) {
  const params = new URLSearchParams({ limit: String(limit) });
  if (options.offset) params.set('offset', String(options.offset));
  if (options.start_at) params.set('start_at', options.start_at);
  if (options.end_at) params.set('end_at', options.end_at);
  const response = await apiFetch(`/api/v1/messages?${params.toString()}`);
  if (!response.ok) throw new Error('Failed to fetch messages');
  return response.json();
}

export async function fetchEvents() {
  const response = await apiFetch('/api/v1/events');
  if (!response.ok) throw new Error('Failed to fetch events');
  return response.json();
}

export async function fetchEventCard(eventId) {
  const response = await apiFetch(`/api/v1/events/${eventId}/card`);
  if (!response.ok) throw new Error('Failed to load event');
  return response.json();
}

export function getEventCalendarIcsUrl(eventId) {
  return `/api/v1/events/${encodeURIComponent(eventId)}/calendar.ics`;
}

export async function createEvent(event) {
  const response = await apiFetch('/api/v1/events', {
    method: 'POST',
    body: JSON.stringify(event),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    // Surface validation details (Pydantic returns an array under `detail`)
    let detail = data.detail;
    if (Array.isArray(detail)) detail = detail.map((d) => `${(d.loc || []).join('.')}: ${d.msg}`).join('; ');
    throw new Error(detail || `Failed to create event (HTTP ${response.status})`);
  }
  return response.json();
}

export async function updateEvent(eventId, event) {
  const response = await apiFetch(`/api/v1/events/${eventId}`, {
    method: 'PATCH',
    body: JSON.stringify(event),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || 'Failed to update event');
  }
  return response.json();
}

export async function updateReadState(messageId) {
  const response = await apiFetch('/api/v1/chat/read-state', {
    method: 'PUT',
    body: JSON.stringify({ message_id: messageId }),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || 'Failed to update read state');
  }
  return response.json();
}

export async function pinMessage(messageId, pinned) {
  const response = await apiFetch(`/api/v1/messages/${messageId}/pin`, {
    method: pinned ? 'POST' : 'DELETE',
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || 'Failed to update pin');
  }
  return response.json();
}

export async function updateEventInvites(eventId, userIds) {
  const response = await apiFetch(`/api/v1/events/${eventId}/invites`, {
    method: 'PUT',
    body: JSON.stringify({ user_ids: userIds }),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || 'Failed to update invites');
  }
  return response.json();
}

export async function rsvpEvent(eventId, responseValue) {
  const response = await apiFetch(`/api/v1/events/${eventId}/rsvp`, {
    method: 'POST',
    body: JSON.stringify({ response: responseValue }),
  });
  if (!response.ok) throw new Error('Failed to RSVP');
  return response.json();
}

export async function fetchEventPosts(eventId) {
  const response = await apiFetch(`/api/v1/events/${eventId}/posts`);
  if (!response.ok) throw new Error('Failed to fetch event posts');
  return response.json();
}

export async function createEventPost(eventId, content) {
  const response = await apiFetch(`/api/v1/events/${eventId}/posts`, {
    method: 'POST',
    body: JSON.stringify({ content }),
  });
  if (!response.ok) throw new Error('Failed to post');
  return response.json();
}

export async function fetchDashboard() {
  const response = await apiFetch('/api/v1/dashboard');
  if (!response.ok) throw new Error('Failed to fetch dashboard');
  return response.json();
}

export async function fetchGroupNotice() {
  const response = await apiFetch('/api/v1/group-notice');
  if (!response.ok) throw new Error('Failed to fetch group notice');
  return response.json();
}

export async function updateGroupNotice(notice) {
  const response = await apiFetch('/api/v1/group-notice', {
    method: 'PATCH',
    body: JSON.stringify({ notice }),
  });
  if (!response.ok) throw new Error('Failed to update group notice');
  return response.json();
}

export async function fetchHomeAppearance() {
  const response = await apiFetch('/api/v1/home-appearance');
  if (!response.ok) throw new Error('Failed to fetch homepage appearance');
  return (await response.json()).appearance;
}

export async function updateHomeAppearance(updates) {
  const response = await apiFetch('/api/v1/home-appearance', {
    method: 'PUT',
    body: JSON.stringify(updates),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || 'Failed to update homepage appearance');
  }
  return (await response.json()).appearance;
}

export async function setHomeCoverPhoto(photoId) {
  const response = await apiFetch('/api/v1/home-appearance/cover', {
    method: 'POST',
    body: JSON.stringify({ photo_id: photoId }),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || 'Failed to set Hub cover');
  }
  return (await response.json()).appearance;
}

export async function removeHomeCoverPhoto() {
  const response = await apiFetch('/api/v1/home-appearance/cover', {
    method: 'DELETE',
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || 'Failed to remove Hub cover');
  }
  return (await response.json()).appearance;
}

export async function uploadAvatar(dataUrl) {
  const response = await apiFetch('/api/v1/users/me/avatar', {
    method: 'POST',
    body: JSON.stringify({ data_url: dataUrl }),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || 'Failed to upload avatar');
  }
  return response.json();
}

export async function deleteAvatar() {
  const response = await apiFetch('/api/v1/users/me/avatar', { method: 'DELETE' });
  if (!response.ok) throw new Error('Failed to remove avatar');
  return response.json();
}

export async function fetchMemberByUsername(username) {
  const response = await apiFetch(`/api/v1/members/lookup?username=${encodeURIComponent(username)}`);
  if (!response.ok) return null;
  return (await response.json()).member;
}

export async function fetchMemberProfile(sessionId) {
  const response = await apiFetch(`/api/v1/members/${encodeURIComponent(sessionId)}/profile`);
  if (!response.ok) return null;
  return (await response.json()).profile;
}

export async function fetchMemberProfileSummary(username) {
  const response = await apiFetch(`/api/v1/members/${encodeURIComponent(username)}/profile-summary`);
  if (!response.ok) return null;
  return (await response.json()).summary;
}

export async function updateMemberProfile(sessionId, updates) {
  const response = await apiFetch(`/api/v1/members/${encodeURIComponent(sessionId)}/profile`, {
    method: 'PATCH',
    body: JSON.stringify(updates),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || 'Failed to update profile');
  }
  return (await response.json()).profile;
}

export async function fetchMemberActivity(username) {
  const response = await apiFetch(`/api/v1/members/${encodeURIComponent(username)}/activity`);
  if (!response.ok) return [];
  return (await response.json()).activity;
}

export async function fetchMemberMessages(username, limit = 20, offset = 0, source = 'all') {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
    source,
  });
  const response = await apiFetch(`/api/v1/members/${encodeURIComponent(username)}/messages?${params.toString()}`);
  if (!response.ok) return [];
  return (await response.json()).messages;
}

export async function fetchMemberPhotos(username, limit = 60) {
  const response = await apiFetch(`/api/v1/members/${encodeURIComponent(username)}/photos?limit=${encodeURIComponent(limit)}`);
  if (!response.ok) return [];
  return (await response.json()).photos;
}

export async function fetchHubItemByRef(ref) {
  const response = await apiFetch(`/api/v1/hub-items/by-short-id?ref=${encodeURIComponent(ref)}`);
  if (!response.ok) return null;
  return (await response.json()).item;
}

export async function fetchHubItems(options = {}) {
  const params = new URLSearchParams();
  if (options.type) params.set('type', options.type);
  if (options.pinned !== undefined) params.set('pinned', String(options.pinned));
  if (options.limit) params.set('limit', String(options.limit));
  const response = await apiFetch(`/api/v1/hub-items${params.toString() ? `?${params.toString()}` : ''}`);
  if (!response.ok) throw new Error('Failed to fetch hub items');
  return response.json();
}

export async function fetchNotes(options = {}) {
  const params = new URLSearchParams();
  if (options.q) params.set('q', options.q);
  if (options.note_type && options.note_type !== 'all') params.set('note_type', options.note_type);
  if (options.pinned !== undefined) params.set('pinned', String(options.pinned));
  if (options.sort) params.set('sort', options.sort);
  if (options.limit) params.set('limit', String(options.limit));
  if (options.offset) params.set('offset', String(options.offset));
  const response = await apiFetch(`/api/v1/notes${params.toString() ? `?${params.toString()}` : ''}`);
  if (!response.ok) throw new Error('Failed to fetch notes');
  return response.json();
}

export async function fetchNote(noteId) {
  const response = await apiFetch(`/api/v1/notes/${noteId}`);
  if (!response.ok) throw new Error('Failed to fetch note');
  return response.json();
}

export async function createNote(note) {
  const response = await apiFetch('/api/v1/notes', {
    method: 'POST',
    body: JSON.stringify(note),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || 'Failed to create note');
  }
  return response.json();
}

export async function updateNote(noteId, note) {
  const response = await apiFetch(`/api/v1/notes/${noteId}`, {
    method: 'PATCH',
    body: JSON.stringify(note),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || 'Failed to update note');
  }
  return response.json();
}

export async function deleteNote(noteId) {
  const response = await apiFetch(`/api/v1/notes/${noteId}`, { method: 'DELETE' });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || 'Failed to archive note');
  }
  return response.json();
}

export async function pinNote(noteId) {
  const response = await apiFetch(`/api/v1/notes/${noteId}/pin`, { method: 'POST' });
  if (!response.ok) throw new Error('Failed to pin note');
  return response.json();
}

export async function unpinNote(noteId) {
  const response = await apiFetch(`/api/v1/notes/${noteId}/pin`, { method: 'DELETE' });
  if (!response.ok) throw new Error('Failed to unpin note');
  return response.json();
}

export async function fetchNoteRevisions(noteId) {
  const response = await apiFetch(`/api/v1/notes/${noteId}/revisions`);
  if (!response.ok) throw new Error('Failed to fetch note history');
  return response.json();
}

export async function fetchNoteComments(noteId) {
  const response = await apiFetch(`/api/v1/notes/${noteId}/comments`);
  if (!response.ok) throw new Error('Failed to fetch comments');
  return response.json();
}

export async function createNoteComment(noteId, content) {
  const response = await apiFetch(`/api/v1/notes/${noteId}/comments`, {
    method: 'POST',
    body: JSON.stringify({ content }),
  });
  if (!response.ok) throw new Error('Failed to comment');
  return response.json();
}

export async function pinHubItem(itemId, pinned) {
  const response = await apiFetch(`/api/v1/hub-items/${itemId}/pin`, {
    method: 'POST',
    body: JSON.stringify({ pinned }),
  });
  if (!response.ok) throw new Error('Failed to update pin');
  return response.json();
}

export async function updateHubItem(itemId, item) {
  const response = await apiFetch(`/api/v1/hub-items/${itemId}`, {
    method: 'PATCH',
    body: JSON.stringify(item),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || 'Failed to update item');
  }
  return response.json();
}

export async function sendHubItemToChat(itemId) {
  const response = await apiFetch(`/api/v1/hub-items/${itemId}/send-to-chat`, { method: 'POST' });
  if (!response.ok) throw new Error('Failed to send to chat');
  return response.json();
}

export async function fetchIdeas() {
  const response = await apiFetch('/api/v1/ideas');
  if (!response.ok) throw new Error('Failed to fetch ideas');
  return response.json();
}

export async function createIdea(idea) {
  const response = await apiFetch('/api/v1/ideas', {
    method: 'POST',
    body: JSON.stringify(idea),
  });
  if (!response.ok) throw new Error('Failed to create idea');
  return response.json();
}

export async function updateIdea(id, idea) {
  const response = await apiFetch(`/api/v1/ideas/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(idea),
  });
  if (!response.ok) throw new Error('Failed to update idea');
  return response.json();
}

export async function deleteIdea(id) {
  const response = await apiFetch(`/api/v1/ideas/${id}`, { method: 'DELETE' });
  if (!response.ok) throw new Error('Failed to archive idea');
  return response.json();
}

export async function fetchPolls() {
  const response = await apiFetch('/api/v1/polls');
  if (!response.ok) throw new Error('Failed to fetch polls');
  return response.json();
}

export async function createPoll(poll) {
  const response = await apiFetch('/api/v1/polls', {
    method: 'POST',
    body: JSON.stringify(poll),
  });
  if (!response.ok) throw new Error('Failed to create poll');
  return response.json();
}

export async function updatePoll(id, poll) {
  const response = await apiFetch(`/api/v1/polls/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(poll),
  });
  if (!response.ok) throw new Error('Failed to update poll');
  return response.json();
}

export async function votePoll(id, optionIds) {
  const response = await apiFetch(`/api/v1/polls/${id}/vote`, {
    method: 'POST',
    body: JSON.stringify({ option_ids: optionIds }),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || 'Failed to vote');
  }
  return response.json();
}

export async function fetchGovernanceVote(id) {
  const response = await apiFetch(`/api/v1/governance/votes/${id}`);
  if (!response.ok) {
    if (response.status === 404) return null;
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || 'Failed to load vote action');
  }
  return (await response.json()).vote_action;
}

export async function castGovernanceVote(id, vote) {
  const response = await apiFetch(`/api/v1/governance/votes/${id}/ballot`, {
    method: 'POST',
    body: JSON.stringify({ vote }),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || 'Failed to vote');
  }
  return response.json();
}

export async function createDisplayRoleVote({ targetSessionId, proposedDisplayRole, reason }) {
  const response = await apiFetch('/api/v1/governance/votes/display-role', {
    method: 'POST',
    body: JSON.stringify({
      target_session_id: targetSessionId,
      proposed_display_role: proposedDisplayRole,
      reason,
    }),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || 'Failed to create role vote');
  }
  return response.json();
}

export async function fetchPollCard(id) {
  const response = await apiFetch(`/api/v1/polls/${id}/card`);
  if (!response.ok) {
    if (response.status === 404) return null;
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || 'Failed to load poll card');
  }
  return (await response.json()).card;
}

export async function fetchLiveAgendaMotions() {
  const response = await apiFetch('/api/v1/polls/live-agenda');
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || 'Failed to load live motions');
  }
  return response.json();
}

export async function createChatEvent(payload) {
  const response = await apiFetch('/api/v1/chat-events', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || 'Failed to schedule motion');
  }
  return response.json();
}

export async function deletePoll(id) {
  const response = await apiFetch(`/api/v1/polls/${id}`, { method: 'DELETE' });
  if (!response.ok) throw new Error('Failed to archive poll');
  return response.json();
}

export async function fetchReminders() {
  const response = await apiFetch('/api/v1/reminders');
  if (!response.ok) throw new Error('Failed to fetch reminders');
  return response.json();
}

export async function createReminder(reminder) {
  const response = await apiFetch('/api/v1/reminders', {
    method: 'POST',
    body: JSON.stringify(reminder),
  });
  if (!response.ok) throw new Error('Failed to create reminder');
  return response.json();
}

export async function updateReminder(id, reminder) {
  const response = await apiFetch(`/api/v1/reminders/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(reminder),
  });
  if (!response.ok) throw new Error('Failed to update reminder');
  return response.json();
}

export async function completeReminder(id, isCompleted) {
  const response = await apiFetch(`/api/v1/reminders/${id}/complete`, {
    method: 'POST',
    body: JSON.stringify({ is_completed: isCompleted }),
  });
  if (!response.ok) throw new Error('Failed to update reminder');
  return response.json();
}

export async function deleteReminder(id) {
  const response = await apiFetch(`/api/v1/reminders/${id}`, { method: 'DELETE' });
  if (!response.ok) throw new Error('Failed to archive reminder');
  return response.json();
}

export async function fetchComments(targetType, targetId) {
  const params = new URLSearchParams({ target_type: targetType, target_id: String(targetId) });
  const response = await apiFetch(`/api/v1/comments?${params.toString()}`);
  if (!response.ok) throw new Error('Failed to fetch comments');
  return response.json();
}

export async function createComment(targetType, targetId, content) {
  const response = await apiFetch('/api/v1/comments', {
    method: 'POST',
    body: JSON.stringify({ target_type: targetType, target_id: targetId, content }),
  });
  if (!response.ok) throw new Error('Failed to comment');
  return response.json();
}

export async function toggleReaction(targetType, targetId, emoji) {
  const response = await apiFetch('/api/v1/reactions/toggle', {
    method: 'POST',
    body: JSON.stringify({ target_type: targetType, target_id: targetId, emoji }),
  });
  if (!response.ok) throw new Error('Failed to react');
  return response.json();
}

export async function fetchPhotos(limit = 60, options = {}) {
  const params = new URLSearchParams({ limit: String(limit) });
  const opts = options || {};
  if (opts.offset)       params.set('offset', String(opts.offset));
  if (opts.event_id)     params.set('event_id', String(opts.event_id));
  if (opts.hub_item_id)  params.set('hub_item_id', String(opts.hub_item_id));
  if (opts.tag)          params.set('tag', opts.tag);
  if (opts.start_at)     params.set('start_at', opts.start_at);
  if (opts.end_at)       params.set('end_at', opts.end_at);
  if (opts.source_type)  params.set('source_type', opts.source_type);
  if (opts.sender)       params.set('sender', opts.sender);
  if (opts.sort)         params.set('sort', opts.sort);
  const response = await apiFetch(`/api/v1/photos?${params.toString()}`);
  if (!response.ok) throw new Error('Failed to fetch photos');
  return response.json();
}

export async function fetchPhotoSenders() {
  const response = await apiFetch('/api/v1/photos/senders');
  if (!response.ok) throw new Error('Failed to fetch photo senders');
  return response.json();
}

export async function fetchPhotoMonths(options = {}) {
  const params = new URLSearchParams();
  if (options.tag)         params.set('tag', options.tag);
  if (options.sender)      params.set('sender', options.sender);
  if (options.source_type) params.set('source_type', options.source_type);
  const query = params.toString();
  const response = await apiFetch(`/api/v1/photos/months${query ? `?${query}` : ''}`);
  if (!response.ok) throw new Error('Failed to fetch photo months');
  return response.json();
}

export async function fetchNotifications(limit = 30) {
  const res = await apiFetch(`/api/v1/notifications?limit=${limit}`);
  if (!res.ok) throw new Error('Failed to fetch notifications');
  return res.json();
}

export async function markNotificationRead(id) {
  await apiFetch(`/api/v1/notifications/${id}/read`, { method: 'PATCH' });
}

export async function markAllNotificationsRead() {
  await apiFetch('/api/v1/notifications/read-all', { method: 'PATCH' });
}

export async function uploadPhoto(file, options = {}) {
  const safeOptions = options || {};
  const dataUrl = await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error('Failed to read image'));
    reader.readAsDataURL(file);
  });

  const response = await apiFetch('/api/v1/photos', {
    method: 'POST',
    headers: {
      ...sessionHeaders(),
    },
    body: JSON.stringify({
      filename: file.name,
      content_type: file.type || 'image/jpeg',
      data_url: dataUrl,
      caption: safeOptions.caption || null,
      tags: safeOptions.tags || [],
      event_id: safeOptions.event_id || null,
      hub_item_id: safeOptions.hub_item_id || null,
    }),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || 'Failed to upload photo');
  }
  return response.json();
}

export async function setPhotoCover(photoId) {
  const response = await apiFetch(`/api/v1/photos/${photoId}/cover`, { method: 'POST' });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || 'Failed to set cover photo');
  }
  return response.json();
}

export async function deletePhoto(photoId) {
  const response = await apiFetch(`/api/v1/photos/${photoId}`, { method: 'DELETE' });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || 'Failed to delete photo');
  }
  return response.json();
}

export async function updateCoverPosition(hubItemId, x, y) {
  const response = await apiFetch(`/api/v1/hub-items/${hubItemId}/cover-position`, {
    method: 'PATCH',
    body: JSON.stringify({ x, y }),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || 'Failed to update cover position');
  }
  return response.json();
}

export async function fetchStats() {
  const response = await apiFetch('/api/v1/stats');
  if (!response.ok) throw new Error('Failed to fetch stats');
  return response.json();
}

function _statsParams(opts = {}) {
  const p = new URLSearchParams();
  if (opts.dateFrom) p.set('date_from', opts.dateFrom);
  if (opts.dateTo) p.set('date_to', opts.dateTo);
  if (opts.groupBy) p.set('group_by', opts.groupBy);
  if (opts.userId) p.set('user_id', opts.userId);
  if (opts.limit) p.set('limit', String(opts.limit));
  if (opts.offset) p.set('offset', String(opts.offset));
  if (opts.metric) p.set('metric', opts.metric);
  if (opts.normalise) p.set('normalise', opts.normalise);
  if (opts.direction) p.set('direction', opts.direction);
  if (opts.topN) p.set('top_n', String(opts.topN));
  if (opts.sender) p.set('sender', opts.sender);
  if (opts.emoji) p.set('emoji', opts.emoji);
  if (opts.sortBy) p.set('sort_by', opts.sortBy);
  if (opts.mediaFilter) p.set('media_filter', opts.mediaFilter);
  if (opts.ignoreThumbReactions) p.set('ignore_thumb_reactions', 'true');
  return p.toString() ? `?${p}` : '';
}

async function _statsGet(path, opts) {
  const response = await apiFetch(`/api/v1/stats${path}${_statsParams(opts)}`);
  if (!response.ok) throw new Error(`Stats fetch failed: ${path}`);
  return response.json();
}

export const fetchStatsOverview = (opts) => _statsGet('/overview', opts);
export const fetchRoomOverview = (opts) => _statsGet('/room-overview', opts);
export const fetchStatsActivity = (opts) => _statsGet('/activity', opts);
export const fetchStatsLeaderboard = (opts) => _statsGet('/leaderboard', opts);
export const fetchStatsTopReactions = (opts) => _statsGet('/reactions/top', opts);
export const fetchStatsReactionSignature = (opts) => _statsGet('/reactions/signature', opts);
export const fetchStatsReactionDyadic = (opts) => _statsGet('/reactions/dyadic', opts);
export const fetchStatsReactionTrends = (opts) => _statsGet('/reactions/trends', opts);
export const fetchStatsReactionsBySender = (opts) => _statsGet('/reactions/by-sender', opts);
export const fetchStatsTopReactedMessages = (opts) => _statsGet('/messages/top-reacted', opts);
export const fetchStatsTopReactedImages = (opts) => _statsGet('/messages/top-reacted-images', opts);

export async function search(query, types = 'ideas,polls,events,reminders,notes,comments,messages', limit = null) {
  const params = new URLSearchParams({ q: query, types });
  if (limit !== null && limit !== undefined) params.set('limit', String(limit));
  const response = await apiFetch(`/api/v1/search?${params}`);
  if (!response.ok) throw new Error('Search failed');
  return response.json();
}

export async function searchPhotos(query, {
  limit = 30,
  conversationId,
  dateFrom,
  dateTo,
  sourceType,
  importBatchId,
} = {}) {
  const q = String(query || '').trim();
  if (!q) throw new Error('Enter a search phrase');

  const params = new URLSearchParams({ q, limit: String(limit) });
  if (conversationId) params.set('conversation_id', conversationId);
  if (dateFrom) params.set('date_from', dateFrom);
  if (dateTo) params.set('date_to', dateTo);
  if (sourceType) params.set('source_type', sourceType);
  if (importBatchId) params.set('import_batch_id', String(importBatchId));

  const response = await apiFetch(`/api/v1/photos/search?${params}`);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = Array.isArray(data.detail)
      ? data.detail.map((d) => d.msg || JSON.stringify(d)).join('; ')
      : data.detail;
    if (response.status === 503) {
      throw new Error(detail || 'Photo search is unavailable until embeddings and pgvector are ready.');
    }
    throw new Error(detail || 'Photo search failed');
  }
  return data;
}

export async function askSearchHubBot(payload) {
  const response = await apiFetch('/api/v1/search/ask', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = Array.isArray(data.detail)
      ? data.detail.map((d) => d.msg || JSON.stringify(d)).join('; ')
      : data.detail;
    throw new Error(detail || 'Hub Bot could not answer that search');
  }
  return data;
}

export async function summariseChat({ hours = 24, maxMessages = 100 } = {}) {
  const response = await apiFetch('/api/v1/ai/summarise-chat', {
    method: 'POST',
    body: JSON.stringify({ hours, max_messages: maxMessages }),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = Array.isArray(data.detail)
      ? data.detail.map((d) => d.msg || JSON.stringify(d)).join('; ')
      : data.detail;
    throw new Error(detail || 'Summarise failed');
  }
  return data;
}

export async function hubBotChat(message, options = {}) {
  const response = await apiFetch('/api/v1/ai/hub-bot-chat', {
    method: 'POST',
    body: JSON.stringify({
      message,
      dry_run: Boolean(options.dryRun),
      include_debug: Boolean(options.includeDebug),
    }),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = Array.isArray(data.detail)
      ? data.detail.map((d) => d.msg || JSON.stringify(d)).join('; ')
      : data.detail;
    throw new Error(detail || 'Hub Bot could not answer');
  }
  return data;
}

export async function searchGroupLore(query, { limit = 20, offset = 0, dateFrom, dateTo } = {}) {
  const params = new URLSearchParams({ q: query, limit: String(limit), offset: String(offset) });
  if (dateFrom) params.set('date_from', dateFrom);
  if (dateTo) params.set('date_to', dateTo);
  const response = await apiFetch(`/api/v1/group-lore/search?${params}`);
  if (!response.ok) throw new Error('Group lore search failed');
  return response.json();
}

export async function fetchGroupLoreStats(query, { dateFrom, dateTo } = {}) {
  const params = new URLSearchParams({ q: query });
  if (dateFrom) params.set('date_from', dateFrom);
  if (dateTo) params.set('date_to', dateTo);
  const response = await apiFetch(`/api/v1/group-lore/stats?${params}`);
  if (!response.ok) throw new Error('Group lore stats failed');
  return response.json();
}

export async function fetchServerResources() {
  const response = await apiFetch('/api/v1/server/resources');
  if (!response.ok) throw new Error('Failed to fetch server resources');
  return response.json();
}

// ── AI Draft Actions ──────────────────────────────────────────────────────────

export async function updateDraftAction(id, { title, payload_json }) {
  const response = await apiFetch(`/api/v1/ai/draft-actions/${id}`, {
    method: 'PATCH',
    body: JSON.stringify({ title, payload_json }),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = Array.isArray(data.detail)
      ? data.detail.map((d) => d.msg || JSON.stringify(d)).join('; ')
      : data.detail;
    throw new Error(detail || `Failed to update draft action (HTTP ${response.status})`);
  }
  return data;
}

export async function acceptDraftAction(id) {
  const response = await apiFetch(`/api/v1/ai/draft-actions/${id}/accept`, {
    method: 'POST',
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = Array.isArray(data.detail)
      ? data.detail.map((d) => d.msg || JSON.stringify(d)).join('; ')
      : data.detail;
    throw new Error(detail || `Failed to accept draft action (HTTP ${response.status})`);
  }
  return data;
}

export async function rejectDraftAction(id) {
  const response = await apiFetch(`/api/v1/ai/draft-actions/${id}/reject`, {
    method: 'POST',
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = Array.isArray(data.detail)
      ? data.detail.map((d) => d.msg || JSON.stringify(d)).join('; ')
      : data.detail;
    throw new Error(detail || `Failed to reject draft action (HTTP ${response.status})`);
  }
  return data;
}

export async function fetchDraftAction(id) {
  const response = await apiFetch(`/api/v1/ai/draft-actions/${id}`);
  if (!response.ok) throw new Error(`Draft action not found (HTTP ${response.status})`);
  return response.json();
}

// ── Topics ───────────────────────────────────────────────────────────────────

export async function fetchTopicTimeline({ dateFrom, dateTo, detectionVersion } = {}) {
  const params = new URLSearchParams();
  if (dateFrom) params.set('date_from', dateFrom);
  if (dateTo) params.set('date_to', dateTo);
  if (detectionVersion) params.set('detection_version', detectionVersion);
  const response = await apiFetch(`/api/v1/topics/timeline?${params.toString()}`);
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || 'Failed to fetch topic timeline');
  }
  return response.json();
}

export async function fetchTopicDetail(topicId) {
  const response = await apiFetch(`/api/v1/topics/${encodeURIComponent(topicId)}`);
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || 'Failed to fetch topic detail');
  }
  return response.json();
}
