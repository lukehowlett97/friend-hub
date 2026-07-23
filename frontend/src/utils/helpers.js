import { formatDistanceToNow, format, isToday, isYesterday, parseISO } from 'date-fns';

/**
 * Format a message timestamp for display.
 *
 * - Same day   → "just now" / "3 minutes ago"
 * - Yesterday  → "Yesterday 3:45 PM"
 * - Older      → "Dec 25, 3:45 PM"
 *
 * Pass the raw ISO string (or anything parseable by date-fns parseISO).
 * Returns a fallback locale string if parsing fails.
 */
export function formatTime(timestamp) {
  try {
    const date = parseISO(timestamp);

    if (isToday(date)) {
      const distance = formatDistanceToNow(date, { addSuffix: true });
      return distance === 'less than a minute ago' ? 'just now' : distance;
    }

    if (isYesterday(date)) {
      return `Yesterday ${format(date, 'h:mm a')}`;
    }

    if (date.getFullYear() !== new Date().getFullYear()) {
      return format(date, 'dd/MM/yy, h:mm a');
    }

    return format(date, 'MMM d, h:mm a');
  } catch {
    return new Date(timestamp).toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit',
    });
  }
}

/**
 * Format a timestamp as a full human-readable string, suitable for a tooltip.
 * e.g. "January 1, 2025 at 3:45:00 PM"
 */
export function formatFullTimestamp(timestamp) {
  try {
    return format(parseISO(timestamp), 'PPpp');
  } catch {
    return timestamp;
  }
}
