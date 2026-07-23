/**
 * Discriminated union types for activity feed items
 * Each activity type has a distinct structure and visual representation
 */

/**
 * @typedef {Object} PinnedItemActivity
 * @property {'pinned-item'} type
 * @property {string} id
 * @property {string} itemType - 'idea' | 'poll' | 'event' | 'reminder' | 'hub_item'
 * @property {string} title
 * @property {string} [shortId]
 * @property {number} [commentCount]
 * @property {string} [icon]
 * @property {string} [color]
 * @property {string} [timestamp]
 * @property {string} [route]
 */

/**
 * @typedef {Object} ActivePollActivity
 * @property {'active-poll'} type
 * @property {string} id
 * @property {string} title
 * @property {string} [shortId]
 * @property {number} [responseCount]
 * @property {number} [totalVoters]
 * @property {string} [closesAt]
 * @property {string} [status] - 'active' | 'closing-soon' | 'closed'
 * @property {string} [route]
 */

/**
 * @typedef {Object} UpcomingEventActivity
 * @property {'upcoming-event'} type
 * @property {string} id
 * @property {string} title
 * @property {string} [shortId]
 * @property {string} [startsAt]
 * @property {string} [location]
 * @property {number} [attendeeCount]
 * @property {string} [status] - 'upcoming' | 'today' | 'tomorrow'
 * @property {string} [route]
 */

/**
 * @typedef {Object} AIMemoryActivity
 * @property {'ai-memory'} type
 * @property {string} id
 * @property {string} suggestion
 * @property {string} [context]
 * @property {string} [timestamp]
 * @property {string} [actionLabel]
 * @property {string} [actionRoute]
 */

/**
 * @typedef {Object} PhotoUploadActivity
 * @property {'photo-upload'} type
 * @property {string} id
 * @property {number} count
 * @property {string} [uploaderName]
 * @property {string} [uploaderAvatar]
 * @property {string} [folderName]
 * @property {string} [timestamp]
 * @property {string} [route]
 */

/**
 * @typedef {Object} RecentEditActivity
 * @property {'recent-edit'} type
 * @property {string} id
 * @property {string} itemType - 'idea' | 'poll' | 'event' | 'reminder'
 * @property {string} itemTitle
 * @property {string} [itemShortId]
 * @property {string} [editorName]
 * @property {string} [editorAvatar]
 * @property {string} [changeType] - 'comment' | 'edit' | 'status-update'
 * @property {string} [timestamp]
 * @property {string} [route]
 */

/**
 * @typedef {Object} OpenReminderActivity
 * @property {'open-reminder'} type
 * @property {string} id
 * @property {string} title
 * @property {string} [shortId]
 * @property {string} [dueAt]
 * @property {string} [status] - 'overdue' | 'due-today' | 'due-soon'
 * @property {string[]} [assignees]
 * @property {string} [route]
 */

/**
 * @typedef {Object} HubItemUpdate
 * @property {'hub-item-update'} type
 * @property {string} id
 * @property {string} title
 * @property {string} [shortId]
 * @property {string} [updateType] - 'new' | 'updated' | 'active'
 * @property {number} [actionCount]
 * @property {string} [timestamp]
 * @property {string} [route]
 */

/**
 * Union type of all activity items
 * @typedef {PinnedItemActivity | ActivePollActivity | UpcomingEventActivity | AIMemoryActivity | PhotoUploadActivity | RecentEditActivity | OpenReminderActivity | HubItemUpdate} ActivityFeedItem
 */

/**
 * Filter type for activity feed
 * @typedef {'all' | 'live' | 'pinned' | 'upcoming' | 'ai'} ActivityFilter
 */

/**
 * Status badge types used across activities
 * @typedef {'active' | 'pinned' | 'closing-soon' | 'unresolved' | 'new' | 'live' | 'overdue' | 'due-today' | 'due-soon' | 'today' | 'tomorrow'} StatusBadge
 */

/**
 * Create a pinned item activity
 * @param {Object} item
 * @param {string} itemType
 * @returns {PinnedItemActivity}
 */
export function createPinnedItemActivity(item, itemType = 'hub_item') {
  const icons = {
    idea: '💡',
    poll: '🗳️',
    event: '📅',
    reminder: '⏰',
    hub_item: '◆',
    note: '📝',
  };

  return {
    type: 'pinned-item',
    id: item.id,
    itemType: itemType,
    title: item.title || item.question || 'Untitled',
    shortId: item.short_id || item.hub_item?.short_id,
    commentCount: item.comment_count || 0,
    icon: icons[itemType] || '◆',
    color: getColorForType(itemType),
    timestamp: item.pinned_at || item.created_at,
    route: getRouteForItem(item, itemType),
  };
}

/**
 * Create an active poll activity
 * @param {Object} poll
 * @returns {ActivePollActivity}
 */
export function createActivePollActivity(poll) {
  const optionCount = poll.options?.length || 0;
  const responseCount = poll.responses?.length || 0;
  const closesAt = poll.closes_at || poll.deadline_at;
  const status = getPolStatus(closesAt);

  return {
    type: 'active-poll',
    id: poll.id,
    title: poll.question || poll.title || 'Untitled poll',
    shortId: poll.short_id,
    responseCount: responseCount,
    totalVoters: optionCount,
    closesAt: closesAt,
    status: status,
    route: `/polls/${poll.id}`,
  };
}

/**
 * Create an upcoming event activity
 * @param {Object} event
 * @returns {UpcomingEventActivity}
 */
export function createUpcomingEventActivity(event) {
  const startsAt = event.event_start_at || event.starts_at;
  const status = getEventStatus(startsAt);
  const attendeeCount = event.invites?.length || 0;

  return {
    type: 'upcoming-event',
    id: event.id,
    title: event.title || event.name || 'Untitled event',
    shortId: event.short_id,
    startsAt: startsAt,
    location: event.location,
    attendeeCount: attendeeCount,
    status: status,
    route: `/events/${event.id}`,
  };
}

/**
 * Create an AI memory activity/suggestion
 * @param {Object} suggestion
 * @returns {AIMemoryActivity}
 */
export function createAIMemoryActivity(suggestion) {
  return {
    type: 'ai-memory',
    id: suggestion.id || `ai-${Date.now()}`,
    suggestion: suggestion.suggestion || suggestion.content || '',
    context: suggestion.context,
    timestamp: suggestion.created_at || new Date().toISOString(),
    actionLabel: suggestion.action_label || 'View',
    actionRoute: suggestion.action_route,
  };
}

/**
 * Create a photo upload activity
 * @param {Object} upload
 * @returns {PhotoUploadActivity}
 */
export function createPhotoUploadActivity(upload) {
  return {
    type: 'photo-upload',
    id: upload.id,
    count: upload.count || upload.photo_count || 1,
    uploaderName: upload.uploader_name || upload.user?.nickname,
    uploaderAvatar: upload.uploader_avatar || upload.user?.avatar_url,
    folderName: upload.folder_name || 'Photos',
    timestamp: upload.created_at || upload.uploaded_at,
    route: `/photos${upload.folder_id ? `?folder=${upload.folder_id}` : ''}`,
  };
}

/**
 * Create a recent edit activity
 * @param {Object} activity
 * @returns {RecentEditActivity}
 */
export function createRecentEditActivity(activity) {
  const changeTypeMap = {
    'comment': 'comment',
    'edit': 'edit',
    'reply': 'comment',
    'tag': 'edit',
    'status_update': 'status-update',
  };

  return {
    type: 'recent-edit',
    id: activity.id,
    itemType: activity.target_type,
    itemTitle: activity.target_name || 'Untitled',
    itemShortId: activity.target_short_id,
    editorName: activity.actor?.nickname,
    editorAvatar: activity.actor?.avatar_url,
    changeType: changeTypeMap[activity.action] || 'edit',
    timestamp: activity.created_at,
    route: getActivityRoute(activity),
  };
}

/**
 * Create an open reminder activity
 * @param {Object} reminder
 * @returns {OpenReminderActivity}
 */
export function createOpenReminderActivity(reminder) {
  const dueAt = reminder.due_at || reminder.deadline_at;
  const status = getReminderStatus(dueAt);

  return {
    type: 'open-reminder',
    id: reminder.id,
    title: reminder.title || 'Untitled reminder',
    shortId: reminder.short_id,
    dueAt: dueAt,
    status: status,
    assignees: reminder.assignees?.map((a) => a.nickname) || [],
    route: `/reminders/${reminder.id}`,
  };
}

/**
 * Create a hub item update activity
 * @param {Object} item
 * @returns {HubItemUpdate}
 */
export function createHubItemUpdateActivity(item) {
  const updateType = item.is_new ? 'new' : item.recently_updated ? 'updated' : 'active';

  return {
    type: 'hub-item-update',
    id: item.id,
    title: item.title || 'Untitled item',
    shortId: item.short_id,
    updateType: updateType,
    actionCount: item.unresolved_count || item.comment_count || 0,
    timestamp: item.updated_at || item.created_at,
    route: `/items/${item.id}`,
  };
}

// ────── Helper Functions ──────────

function getColorForType(type) {
  const colors = {
    idea: '#f59e0b',
    poll: '#3b82f6',
    event: '#10b981',
    reminder: '#ef4444',
    hub_item: '#8b5cf6',
    note: '#6b7280',
  };
  return colors[type] || '#6b7280';
}

function getRouteForItem(item, type) {
  if (type === 'event') {
    const eventId = item.source_id || item.id;
    return `/events/${eventId}`;
  }
  const routes = {
    idea: '/ideas',
    poll: `/polls/${item.id}`,
    reminder: `/reminders/${item.id}`,
    hub_item: `/items/${item.id}`,
    note: `/notes/${item.source_id || item.id}`,
  };
  return routes[type] || '/home';
}

function getActivityRoute(activity) {
  if (activity.target_type === 'event')    return `/events/${activity.target_id}`;
  if (activity.target_type === 'idea')     return '/ideas';
  if (activity.target_type === 'poll')     return `/polls/${activity.target_id}`;
  if (activity.target_type === 'reminder') return `/reminders/${activity.target_id}`;
  if (activity.target_type === 'note')     return `/notes/${activity.target_id}`;
  if (activity.target_type === 'hub_item') return `/items/${activity.target_id}`;
  if (activity.target_type === 'message')  return '/chat';
  return '/home';
}

function getPolStatus(closesAt) {
  if (!closesAt) return 'active';
  const now = new Date();
  const closeDate = new Date(closesAt);
  const msUntilClose = closeDate - now;
  const hoursUntilClose = msUntilClose / (1000 * 60 * 60);

  if (msUntilClose < 0) return 'closed';
  if (hoursUntilClose < 2) return 'closing-soon';
  return 'active';
}

function getEventStatus(startsAt) {
  if (!startsAt) return 'upcoming';
  const now = new Date();
  const startDate = new Date(startsAt);
  const msSinceStart = now - startDate;
  const msUntilStart = startDate - now;
  const daysUntilStart = msUntilStart / (1000 * 60 * 60 * 24);
  const daysSinceStart = msSinceStart / (1000 * 60 * 60 * 24);

  if (daysSinceStart > 0) return 'past';
  if (Math.abs(msUntilStart) < 1000 * 60 * 60 * 24) return 'today';
  if (daysUntilStart < 2) return 'tomorrow';
  return 'upcoming';
}

function getReminderStatus(dueAt) {
  if (!dueAt) return 'unresolved';
  const now = new Date();
  const dueDate = new Date(dueAt);
  const msSinceDue = now - dueDate;
  const msUntilDue = dueDate - now;
  const daysUntilDue = msUntilDue / (1000 * 60 * 60 * 24);

  if (msSinceDue > 0) return 'overdue';
  if (Math.abs(msUntilDue) < 1000 * 60 * 60 * 24) return 'due-today';
  if (daysUntilDue < 3) return 'due-soon';
  return 'unresolved';
}

/**
 * Format relative time for display
 * @param {string | Date} timestamp
 * @returns {string}
 */
export function formatRelativeTime(timestamp) {
  if (!timestamp) return '';
  const date = new Date(timestamp);
  const now = new Date();
  const diffMs = now - date;
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return 'just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  return date.toLocaleDateString();
}

/**
 * Format absolute date for display
 * @param {string | Date} timestamp
 * @returns {string}
 */
export function formatAbsoluteDate(timestamp) {
  if (!timestamp) return '';
  const date = new Date(timestamp);
  return date.toLocaleDateString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}
