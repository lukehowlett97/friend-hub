# Phase: AI Catchup, Semantic Search, and Chat Timeline

> **Status:** Slice A complete (2026-06-11). Slice B complete (2026-06-11) — extended with date-aware retrieval; see "Slice B implementation notes" below. Slice C planned.
> **Priority:** 2
> **Depends on:** Hermes agent runtime (complete, now two-pass), AI memory tables (complete), HubSummaryService (complete), capabilities module (complete), photo embeddings pipeline (complete — pattern to copy)
> **Created:** 2026-06-10

## Goal

Make the group's history a first-class feature, in three slices that build on each other:

- **A. `/catchup`** — "what did I miss?" answered from summaries + messages since you last read.
- **B. pgvector semantic search** — embeddings over messages, summaries, and memories so old discussions are actually retrievable.
- **C. Chat timeline** — a browsable visual history of the group: summaries, events, polls, photos, and lore moments on one scrollable timeline, with links back to the original messages.

A is useful on day one with no new infrastructure. B upgrades A's retrieval and the existing `/search` and memory-context features. C is the user-facing payoff that consumes both.

---

## Current Foundation

Already in place (do not rebuild):

- `HubSummaryService` produces `daily_summary`, `weekly_summary`, `decision`, `unresolved_plan`, `funny_moment`, `user_preference` memory entries.
- AI memory entries are now injected into the Hub Bot chat context (`MEMORY:` section) with keyword relevance.
- The agent runtime is two-pass: read-only tools (`search_memories`, `search_hub_items`, …) results are fed back for a final reply.
- `/search` answers questions over old chat via ILIKE keyword search (`search_ask_service.py`).
- Photo embeddings already use pgvector with a job-queue pattern (`photo_embeddings`, `photo_embedding_jobs`) — slice B copies this wholesale.
- Hub items have short IDs (#E-1, #P-2) and stable routes.

Known gap this phase must fill: **there is no per-user chat read tracking anywhere** (only notification `is_read` flags). Slice A introduces it.

---

## Slice A: /catchup

### Product behaviour

```text
@hub catchup            → everything since I last read
/catchup                → same
/catchup since Monday   → explicit window override
```

Reply shape (kept short, links back to items):

```text
Since you were last here (Tue 19:40, 142 messages):
• Friday is now pub night — #E-4 created, 5 going.
• Poll #P-6 "BBQ or beach?" closes tonight — you haven't voted.
• Mike still hasn't booked the train (reminder #R-2).
Want the full summary? /summarise since 19:40
```

### Read tracking

New table:

```sql
chat_read_state (
  user_id      uuid not null,
  room_id      uuid not null,
  last_read_message_id bigint not null,
  updated_at   timestamptz not null default now(),
  primary key (user_id, room_id)
)
```

- Frontend posts `PUT /api/v1/rooms/{room_id}/read-state {message_id}` when the chat view is scrolled to bottom / visible (debounced, reuse the existing visibility handling from the PWA chat polish work).
- This table is independently useful later (unread badges per room).

### Catchup assembly (server-side)

1. Look up `last_read_message_id` for (user, room). If none, fall back to 24h.
2. Gap small (≤ ~80 messages): summarise the messages directly via the existing summarise path.
3. Gap large: prefer stored summaries (`daily_summary` / `weekly_summary` memory entries covering the gap) + the tail of recent messages, instead of raw history.
4. Always append: open polls the user hasn't voted in, events created/changed in the gap, reminders still open — straight from hub item queries, not the LLM (ground truth, no hallucinated IDs).
5. Record usage event with `command="catchup"`.

### Acceptance criteria

- `/catchup` and "what did I miss" via @hub both work.
- Reply references real short IDs only; item facts come from queries, not the LLM.
- A user with nothing missed gets a friendly one-liner, no LLM call wasted.
- Read state updates do not spam the API (debounced client-side).
- `/help` lists the new command (add to `capabilities.py` — single source of truth).

---

## Slice B: pgvector Semantic Search

### What gets embedded

| Entity | Granularity | Why |
|---|---|---|
| chat messages | batches of ~10–20 consecutive messages | single messages are too thin; batches carry conversational meaning |
| memory entries | per entry | makes the chat MEMORY section relevance-ranked instead of ILIKE |
| summaries | per entry | lets /catchup and /search pull the right week |
| hub items | per item (title + body) | "that idea about cottages" → #I-7 |

### Schema (mirrors photo embeddings)

```sql
chat_embeddings (
  id            bigserial primary key,
  source_type   text not null,        -- message_batch | memory | summary | hub_item
  source_id     text not null,
  room_id       uuid null,
  message_start_id bigint null,       -- for message_batch
  message_end_id   bigint null,
  model_name    text not null,
  model_version text not null,
  embedding     vector not null,      -- pgvector; ORM column stays Text like photo_embedding.py
  created_at    timestamptz not null default now(),
  unique (source_type, source_id, model_name, model_version)
)

chat_embedding_jobs (
  -- same shape and statuses as photo_embedding_jobs: pending/processing/completed/failed
)
```

### Pipeline

- Background worker identical in shape to the image-embeddings worker: enqueue on write (new memory/summary/hub item), plus a backfill command for historical messages.
- Embedding provider goes through the AI gateway like chat models (env-configurable, never frontend-exposed).
- Retrieval: cosine top-k, bounded (k ≤ 8, with a similarity floor), always returning `source_type/source_id` so replies can link back.

### Integration points (in order of payoff)

1. `_build_memory_context` in `hub_agent_service.py` — replace keyword ILIKE with vector top-k (keep ILIKE as fallback when no embeddings exist).
2. `/search` (`search_ask_service.py`) — retrieve message batches + summaries semantically, keep the existing source-attribution reply format.
3. `search_memories` / `search_hub_items` agent tools — same upgrade, so the two-pass runtime benefits automatically.
4. `/catchup` — semantic dedupe of summary candidates.

### Env vars

```text
AI_EMBEDDING_MODEL=
AI_EMBEDDING_PROVIDER=
AI_ENABLE_CHAT_EMBEDDINGS=false
```

### Acceptance criteria

- "when did we talk about camping?" retrieves the right discussion with message links.
- Memory context in chat is ranked by relevance to the query.
- Backfill is resumable and idempotent (job table, like photos).
- Everything degrades gracefully to keyword search when embeddings are disabled or missing.
- Retrieval cost is bounded (no unbounded scans, k capped).

---

## Slice B implementation notes (as built, 2026-06-11)

- Tables `chat_embeddings` / `chat_embedding_jobs` (migration 052), dimensionless `vector` column — every similarity query filters `model_name`/`model_version`.
- Providers behind `AI_EMBEDDING_PROVIDER` (`fake` | `ollama` | `openai`) via `get_embedding_provider` in `app/ai/gateway.py`. Default: Ollama + `nomic-embed-text`.
- **Worker ops:** `python -m app.domains.chat_embeddings.worker --backfill` once (resumable — kill and rerun any time), then a long-running `--sleep-seconds 30` process or periodic `--once` cron. The sweep enqueuer inside the worker is also what picks up new messages/memories/hub items — no write-path hooks.
- Date-aware retrieval: `app/domains/ai/date_parsing.py` + `retrieve_for_day` in `app/domains/ai/retrieval.py`. Day windows are **UTC** (no room timezone exists yet). `/summarise` and `/catchup` accept explicit dates now too.
- `/search` (chat) routes topic → semantic, date → day sources, hybrid → both; keyword ILIKE remains the fallback. Search page `GET /api/v1/search` merges semantic message hits; `POST /search/ask` inherits them via `visible_results`.
- Deferred from this slice: vector upgrade of the `search_memories`/`search_hub_items` agent tools (integration point 3), semantic dedupe in `/catchup` (point 4), re-embedding when memories/hub items are edited (sweep only catches new rows).

## Slice C: Chat Timeline

### Product behaviour

A new "Timeline" page: an infinite-scroll, newest-first river of the group's life. Zoomable altitude:

- **Month view** — one card per week: weekly summary headline, top photo, biggest event.
- **Week view** — day cards: daily summary, events that happened, polls decided, funny moments.
- **Day view** — the actual artefacts: summary text, hub items, photos, "lore" memory entries, each linking to `#short-id` routes or scroll-to-message in chat.

```text
── May 2026 ──────────────────────────
▸ w/c 25 May — "Lakes trip booked 🎉"   [photo strip]
▸ w/c 18 May — "BBQ washout, pub instead"
   • Mon: #P-9 decided (pub) · 2 photos
   • Sat: #E-7 Pub night — 6 went
   • 💬 "the swan incident" (lore)
```

### Data model

No new content tables — the timeline is a **read model** over what already exists:

```text
GET /api/v1/timeline?room_id=&before=&zoom=month|week|day
→ buckets[] of { period, summary, events[], polls[], photos[], lore[], message_anchors[] }
```

Sources per bucket: memory entries (`daily_summary`/`weekly_summary`/`funny_moment`/`group_lore` with their `message_start_id`/`message_end_id` ranges), hub items by `created_at`/`starts_at`, photos by taken/posted date.

Server assembles buckets; a small cache table is acceptable later if assembly gets slow, but do not start with one.

### Dependencies and gaps to close

- Summaries must be generated **on a schedule**, not only on demand — add the daily job (trigger options were already specced in the original AI integration phase). Without steady summaries, the timeline has holes.
- Summary entries must reliably carry `message_start_id`/`message_end_id` so "jump to chat" works.
- Slice B is optional for v1 but powers "search the timeline" later.

### Frontend

- New route + nav entry, reuse existing card components (draft action cards / hub item cards established the pattern).
- Each timeline entry deep-links: hub items → existing routes, message ranges → chat scroll-to-message, photos → Photos viewer.

### Acceptance criteria

- Timeline renders month/week/day altitudes with real data and no dead links.
- Empty periods collapse (no blank cards).
- Daily summary job runs unattended and is idempotent per (room, day).
- Works on mobile PWA (this is a "show your mates" feature — it must look good on a phone).

---

## Build order

1. `chat_read_state` table + read-state endpoint + frontend debounced reporting (A).
2. `/catchup` command: gap detection, summary-or-messages strategy, ground-truth item appendix (A).
3. Scheduled daily summary job with message-range metadata (A/C shared dependency).
4. `chat_embeddings` + jobs tables, worker, backfill command (B).
5. Wire vector retrieval into memory context, then `/search`, then tools (B).
6. Timeline read-model endpoint (C).
7. Timeline frontend, day view first, then week/month rollups (C).

## Safety / cost rules

- Embedding and catchup calls are recorded as usage events like every other AI call.
- Catchup for huge gaps must use summaries, never dump thousands of messages into a prompt.
- Timeline endpoint requires the same room-membership auth as chat history.
- All new commands registered in `capabilities.py` so `/help` and the prompts stay truthful.

## Definition of done

- A user who was away for a week gets a useful `/catchup` in one message.
- "When did we talk about X?" works via semantic retrieval with links back.
- The timeline page tells the group's story month by month, and every entry links to its source.
