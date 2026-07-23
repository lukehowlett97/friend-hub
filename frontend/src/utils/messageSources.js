// Parsing for the trailing "Sources: [1] /chat?message=123 · [2] …" block that
// Hub Bot appends to /search replies (see backend hub_agent_service.py).
// Best-effort: only a complete trailing block is stripped, so ordinary
// messages that merely mention "Sources" are left untouched.

const SOURCES_BLOCK_RE = /(?:^|\n)\s*\**Sources:?\**\s*((?:\[\d+\]\s*\(?\/chat\?message=\d+\)?\s*(?:[·,;]\s*)?)+)\s*$/i;
const SOURCE_REF_RE = /\[(\d+)\]\s*\(?\/chat\?message=(\d+)\)?/g;

export function extractMessageSources(content = '') {
  const text = String(content || '');
  const match = text.match(SOURCES_BLOCK_RE);
  if (!match) return { sources: [], stripped: text };

  const sources = [];
  for (const ref of match[1].matchAll(SOURCE_REF_RE)) {
    const index = Number(ref[1]);
    const messageId = Number(ref[2]);
    if (Number.isFinite(messageId)) sources.push({ index, messageId });
  }
  if (!sources.length) return { sources: [], stripped: text };

  return { sources, stripped: text.slice(0, match.index).trim() };
}

export function stripMessageSources(content = '') {
  return extractMessageSources(content).stripped;
}
