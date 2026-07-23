export function buildChatMessageHref(messageId, options = {}) {
  const numericId = Number(messageId);
  if (!Number.isInteger(numericId) || numericId <= 0) return '/chat';

  const params = new URLSearchParams({ message: String(numericId) });
  const highlightIds = [
    numericId,
    ...(Array.isArray(options.highlightIds) ? options.highlightIds : []),
  ]
    .map((id) => Number(id))
    .filter((id) => Number.isInteger(id) && id > 0);

  const uniqueHighlightIds = [...new Set(highlightIds)];
  if (uniqueHighlightIds.length > 0) {
    params.set('highlight', uniqueHighlightIds.join(','));
  }

  Object.entries(options.params || {}).forEach(([key, value]) => {
    if (value === null || value === undefined || value === '') return;
    params.set(key, String(value));
  });

  return `/chat?${params.toString()}`;
}
