# Chat Embeddings — Operations

Semantic search over chat history (Slice B). One background worker keeps
`chat_embeddings` in sync; the API only ever reads.

## Requirements

- Postgres with pgvector (prod compose already uses `pgvector/pgvector:pg16`;
  migration 052 falls back to TEXT columns without it, which disables vector
  search but breaks nothing).
- Ollama with the embedding model:

```bash
ollama pull nomic-embed-text
```

## Environment

Set in `backend/app/.env` (dev) or `.env.prod` (prod — see
`deploy/prod.env.example`):

```env
AI_ENABLE_CHAT_EMBEDDINGS=true
AI_EMBEDDING_PROVIDER=ollama        # fake | ollama | openai
AI_EMBEDDING_MODEL=nomic-embed-text
AI_RETRIEVAL_SIMILARITY_FLOOR=0.50  # see "Similarity floor tuning" below
```

Both the API server and the worker read these. The flag gates everything:
with it off, `/search` uses keyword ILIKE only and the worker exits at startup.

## First run: historical backfill

```bash
cd backend
.venv/bin/python -m app.domains.chat_embeddings.worker --backfill
```

Resumable: kill it any time and rerun — the job table's unique constraint and
the sweep's forward-only batching guarantee no duplicates. Exits when done.

## Steady state: continuous worker

```bash
cd backend
.venv/bin/python -m app.domains.chat_embeddings.worker --sleep-seconds 30
```

Each tick: sweep (enqueue new message batches, new memories/summaries/hub
items, and **re-embeds for anything edited since its last embedding**), then
claim and process pending jobs. Tick failures back off exponentially (capped
at 10 min) and never kill the worker; individual job failures retry up to
`AI_EMBEDDING_MAX_RETRIES` (default 3) then park as `failed`.

As a systemd service: `deploy/systemd/friendhub-chat-embeddings.service`
(instructions in the file header).

Notes:
- New chat accumulates into batches of ~15 messages; a partial tail batch is
  flushed once it is 6h old (`AI_EMBEDDING_BATCH_FLUSH_HOURS`), so very recent
  messages may take up to one flush window to become semantically searchable.
  `/search` date queries and keyword fallback cover the gap meanwhile.
- Edits to memories/hub items are picked up by the stale sweep on the next
  tick (≤ ~30s + embed time).

## Health check

```text
GET /api/v1/admin/chat-embeddings/status   (owner only)
```

Returns enabled/provider/model/floor, total embeddings for the active model,
job counts by status, and last-processed timestamps. A healthy system shows
`pending` near 0 and a recent `last_processed_at`. `failed > 0` means jobs
exhausted retries — check `chat_embedding_jobs.last_error`.

Usage accounting: every embedding call writes an `ai_usage_log` row
(`feature='embedding'`, `command='embedding_worker'` or `'search'`). Search
routing decisions (semantic vs keyword fallback, hit counts, top scores) are
logged at INFO by `app.domains.ai.retrieval` and recorded per run in
`ai_agent_runs.parsed_response`.

## Similarity floor tuning

`nomic-embed-text` cosine scores cluster high. Measured against this group's
real history (2026-06-12):

| Query type | Top scores |
|---|---|
| Genuinely related ("football match results", "going to the pub on friday") | 0.55 – 0.63 |
| Topic absent but question-phrased ("when did we talk about camping?") | ~0.52 |
| Completely unrelated ("quantum chromodynamics", "mortgage rates") | 0.46 – 0.50 |

The boundary is ~0.50, hence the default. If weak matches still surface,
raise towards 0.52; if real matches get dropped, lower towards 0.47. The INFO
logs print top scores per query, so a day of normal use tells you which way
to move it. Changing provider/model invalidates this calibration — re-tune
after switching.

## Switching providers/models

Embeddings are keyed by (model, provider); old rows are simply ignored after a
switch. To rebuild: update the env vars, then

```sql
DELETE FROM chat_embeddings; DELETE FROM chat_embedding_jobs;
```

and rerun `--backfill`.
