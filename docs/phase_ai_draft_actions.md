# Phase: AI Draft Actions

> **Status:** Implemented for Hub Lab and normal chat @hub draft creation  
> **Priority:** 1  
> **Depends on:** Hermes agent runtime (complete), AISuggestion system (complete), Hub Lab UI (complete)

### Implementation status

| Slice | Status |
|---|---|
| Migration + model | ✅ Complete |
| Repository | ✅ Complete |
| Service (create/accept/reject) | ✅ Complete |
| API endpoints (list/get/accept/reject) | ✅ Complete |
| Hermes tools (propose_poll/event/reminder) | ✅ Complete |
| draft_actions in hub-bot-chat response | ✅ Complete |
| Hub Lab DraftActionCard rendering | ✅ Complete |
| Chat @hub draft creation via Hermes tools | ✅ Complete |
| Chat marker rendering (`[[ai-draft-action:id]]`) | ✅ Complete |
| Edit-before-accept | ❌ Not implemented |
| Draft cards in announcements channel | ❌ Not implemented |
| Scheduled draft expiry | ❌ Not implemented |

### Known limitations

- There is no edit-before-accept flow. Users must accept or reject the AI proposal as-is.
- There is no announcements channel integration for draft actions.
- There is no scheduled expiry job for old draft actions.
- After accepting, navigation links point to list pages (`/polls`, `/reminders`) except for events which link to `/events/{id}` directly.
- The LLM (FakeLLMClient / Ollama) must actually emit a `tool_calls` JSON block invoking `propose_poll`, `propose_event`, or `propose_reminder` for a card to appear. With the FakeLLMClient used in testing, tool calls are not generated — live LLM providers (OpenRouter/Ollama) are required to see draft cards in production.

---

## Goal

The AI should be able to propose draft Events, Polls, and Reminders in response to natural language requests, but must never create them without explicit user confirmation. Every AI-proposed item stays in a `draft` state until a human presses Accept. The AI cannot call accept itself.

This is a safety-first design: the AI drafts, the user decides.

---

## Product Behaviour

### Example Flows

**Poll draft:**
> User: "Plan a poll for where we should go Saturday"

Hub Bot returns a draft poll card:
- Title: "Where should we go Saturday?"
- Options: ["City centre bar", "Someone's house", "Restaurant", "Leave it open"]
- Closes at: Friday 23:59 (auto-inferred from "Saturday")
- Vote mode: single
- Reason: "I've drafted a poll based on your request. Review the options and hit Accept to create it."

**Reminder draft:**
> User: "Create a reminder for everyone to book taxis before Friday"

Hub Bot returns a draft reminder card:
- Text: "Book taxis before Friday"
- Remind at: Thursday 18:00 (day before, sensible default)
- Target: all group members
- Reason: "Reminder drafted for the group. Accept to create it, or edit the time first."

**Event draft:**
> User: "Set up an event for curry night next Thursday at 7"

Hub Bot returns a draft event card:
- Title: "Curry Night"
- Starts at: next Thursday 19:00
- Description: "Curry night — details TBC"
- Location: (blank, user can fill in)
- Reason: "Event drafted. Add a location and accept when ready."

### Draft Card Interactions

Each draft card must support:
- **Accept** — creates the real Hub Item immediately
- **Reject** — dismisses without creating anything
- **Edit** (follow-up slice) — pre-fills a form for user to modify before accepting

### Date Ambiguity

If a date cannot be resolved unambiguously, the agent should ask a clarification question rather than guess:
- "next Thursday" is always resolvable relative to today's date
- "sometime next week" or "soon" should prompt: "Which day were you thinking?"
- Past dates should surface a warning, not silently create a draft

---

## Backend Plan

### Option A: Extend the Existing AISuggestion System

The current `AISuggestion` model already has:
- `suggestion_type`, `title`, `body`, `status` (`pending`/`accepted`/`rejected`/`archived`)
- `proposed_hub_item_type` and `proposed_payload` (JSON)
- Accept endpoint that creates a `HubItem` from the payload
- `created_hub_item_id` FK to link back to the result

**Pros:** Zero new tables. Accept/reject logic already works. Hub Lab already displays pending suggestions.

**Cons:**
- No `group_id` or `created_by_user_id` scoping — suggestions are currently global.
- No `source` field to distinguish Hub Lab vs. chat vs. scheduled job.
- No `agent_run_id` link for observability.
- `proposed_payload` is untyped JSON — no per-type validation at the DB level.
- Accept logic in the router is ad-hoc (raw SQL for sequence counting); type-specific creation (Polls, Reminders) requires calling the legacy `POST /polls` and `POST /reminders` stacks which include side-effects (notifications, linked HubItems) — these would need to be wired in.
- Polls and Reminders are not created via the `HubItem` POST endpoint; they have their own legacy endpoints with their own DB rows. The current accept path only creates a `HubItem` row, which is the mirror record — it would skip creating the canonical `Poll` or `Reminder` row.

### Option B: New `ai_draft_actions` Table

A purpose-built table with explicit fields for group scoping, source tracking, agent run linkage, per-type payload, and richer status lifecycle.

**Pros:** Clean domain model. Explicitly typed. Decoupled from the legacy suggestion system. Future-proof for bot activity feed / announcements channel.

**Cons:** New table, new migration, new repository, new endpoints — more upfront code.

### Recommendation: **Option B**

The existing suggestion system's accept path only creates a `HubItem` row and does not invoke the canonical `Poll` or `Reminder` creation stack. Polls require a `polls` row + `poll_options` rows + voting setup; Reminders require a `reminders` row + `reminder_assignees` rows. Retrofitting the current accept endpoint to handle all three types would require significant surgery to a working system. A new `ai_draft_actions` table lets us build the correct accept logic cleanly against the actual creation services, and add the scoping/observability fields that are missing today without risk of regressions.

The existing `AISuggestion` system can remain as-is for non-draft-action suggestions (ideas, tags, summaries, general notes). The two systems serve different purposes.

---

### Draft Action Schema

**Table: `ai_draft_actions`**

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `group_id` | INT FK → groups | Scopes draft to a group |
| `created_by_user_id` | UUID FK → members | User whose message triggered the draft |
| `proposed_by` | TEXT | Always `"ai"` for now; extensible |
| `action_type` | TEXT | Always `"create_hub_item"` for Phase 1 |
| `item_type` | TEXT | `"event"` \| `"poll"` \| `"reminder"` |
| `status` | TEXT | `"draft"` \| `"accepted"` \| `"rejected"` \| `"expired"` |
| `title` | TEXT | Display title for the card |
| `summary` | TEXT NULLABLE | AI reason / natural-language summary |
| `payload_json` | JSONB | Type-specific structured payload |
| `source` | TEXT | `"hub_lab"` \| `"chat"` \| `"scheduled_job"` |
| `source_message_id` | INT NULLABLE | FK → messages (if from chat) |
| `agent_run_id` | UUID NULLABLE | FK → ai_agent_runs |
| `created_hub_item_id` | UUID NULLABLE | FK → hub_items (set on accept) |
| `created_at` | TIMESTAMPTZ | |
| `updated_at` | TIMESTAMPTZ | |
| `resolved_at` | TIMESTAMPTZ NULLABLE | When accepted/rejected |
| `resolved_by_user_id` | UUID NULLABLE | Who accepted/rejected |

**Indexes:** `group_id`, `status`, `created_by_user_id`, `agent_run_id`

---

### Payload Shapes

**Event payload:**
```json
{
  "title": "Curry Night",
  "description": "Curry night — details TBC",
  "starts_at": "2026-05-21T19:00:00Z",
  "ends_at": null,
  "location": null,
  "tags": []
}
```

**Poll payload:**
```json
{
  "question": "Where should we go Saturday?",
  "options": ["City centre bar", "Someone's house", "Restaurant"],
  "vote_mode": "single",
  "closes_at": "2026-05-15T23:59:00Z",
  "tags": []
}
```

**Reminder payload:**
```json
{
  "text": "Book taxis before Friday",
  "remind_at": "2026-05-14T18:00:00Z",
  "group_wide": true,
  "target_user_ids": [],
  "tags": []
}
```

---

### Validation Rules (enforced at accept time, and ideally at propose time)

| Type | Rules |
|---|---|
| All | Title must not be empty or whitespace-only |
| Event | `starts_at` is required and must be in the future |
| Poll | `options` must contain at least 2 non-empty, distinct strings |
| Poll | `question` must not be empty |
| Reminder | `text` must not be empty |
| Reminder | Either `remind_at` is set (future), or `group_wide` is true — at least one targeting mechanism |
| All | AI-generated datetimes must be UTC ISO-8601; malformed strings are a validation error |
| All | Ambiguous date phrases trigger a clarification reply, not a draft |
| All | A draft in `accepted` or `rejected` status cannot be accepted or rejected again |

---

## Hermes Tooling Plan

### New Tools to Register

All three `propose_*` tools have safety level `safe_write` — they write a draft record but never a final Hub Item. The `accept_draft_action` and `reject_draft_action` tools should **not** be registered as Hermes tools at all. They are user-triggered HTTP endpoints only. The AI must not be able to call accept.

#### `propose_event`

```
safety: safe_write
arguments: title, description?, starts_at, ends_at?, location?, tags?
returns: { success, draft_action_id, draft }
```

Creates an `ai_draft_actions` row with `item_type="event"`, `status="draft"`.
Validates `starts_at` is present and parseable. Returns the draft record.

#### `propose_poll`

```
safety: safe_write
arguments: question, options (list[str], min 2), vote_mode?, closes_at?, tags?
returns: { success, draft_action_id, draft }
```

Creates an `ai_draft_actions` row with `item_type="poll"`, `status="draft"`.
Validates at least 2 non-empty options. Returns the draft record.

#### `propose_reminder`

```
safety: safe_write
arguments: text, remind_at?, group_wide?, target_user_ids?, tags?
returns: { success, draft_action_id, draft }
```

Creates an `ai_draft_actions` row with `item_type="reminder"`, `status="draft"`.
Returns the draft record. Does not send any notifications.

#### `list_draft_actions` (optional read-only tool)

```
safety: read_only
arguments: status?, item_type?, limit?
returns: { count, drafts }
```

Allows the agent to check what drafts are already pending for the group, to avoid duplicating proposals.

### Tool Registration Location

All new tools should be registered in `build_default_registry()` inside [backend/app/domains/ai/tools.py](backend/app/domains/ai/tools.py), following the existing pattern. Each handler receives `db` as its first argument plus keyword arguments matching the tool schema.

The `propose_*` tools need access to `group_id` and `created_by_user_id`. These are currently not passed through the tool call context. The tool handlers will need the runtime to inject them — either via a closure over context values at registry build time (matching how the registry is currently constructed), or by adding `group_id`/`user_id` fields to the tool call dispatch in `HubAgentRuntime`.

Looking at the existing tools, `create_ai_suggestion` and `create_memory_entry` do not take `group_id` — suggestions are currently not group-scoped. The new draft action tools must be group-scoped. The cleanest approach is to pass `group_id` and `user_id` as additional context into `ToolRegistry.call()`, or to build the registry with a partial closure over these values per request (as the runtime already receives context including group info).

### Dry-Run Behaviour

`propose_*` tools respect the existing dry-run flag: in dry-run mode, the tool returns what it *would* create but does not write to the DB. This is already how `safe_write` tools behave in `HubAgentRuntime.run()`.

---

## API Plan

All endpoints under `/api/v1/ai/draft-actions` in a new `ai_draft_router.py`, included from the main router. Auth via existing `_current_user_or_401` pattern.

### Endpoints

#### `POST /api/v1/ai/draft-actions`
Create a draft action directly (used internally by `propose_*` tool handlers; also callable from tests). Body: `{ item_type, title, summary?, payload_json, source, source_message_id?, agent_run_id? }`.

#### `GET /api/v1/ai/draft-actions`
List draft actions for the group. Query params: `status` (default `draft`), `item_type`, `limit` (default 20). Returns `{ drafts: [...], total: N }`.

#### `GET /api/v1/ai/draft-actions/{id}`
Fetch a single draft action by UUID.

#### `POST /api/v1/ai/draft-actions/{id}/accept`
Accept a draft. Validates payload again. Creates the real Hub Item (and canonical Poll/Reminder/Event row). Sets `status="accepted"`, `resolved_at`, `resolved_by_user_id`, `created_hub_item_id`. Returns `{ success, draft, created_hub_item }`.

The accept logic must call the correct creation path per type:
- **Event:** insert into `events` table + create mirrored `HubItem` via `_hub_item_for_source()` (or directly)
- **Poll:** insert into `polls` + `poll_options` + create mirrored `HubItem`
- **Reminder:** insert into `reminders` + `reminder_assignees` + create mirrored `HubItem`

This should be implemented in a `DraftActionService` rather than inline in the router to keep the logic testable.

#### `POST /api/v1/ai/draft-actions/{id}/reject`
Reject a draft. Sets `status="rejected"`, `resolved_at`, `resolved_by_user_id`. Returns `{ success, draft }`.

#### `PATCH /api/v1/ai/draft-actions/{id}` *(follow-up slice)*
Partial edit of `payload_json` and `title`/`summary` fields before accepting. Only allowed while `status="draft"`. Not in scope for slice 1.

---

### Hub Lab Endpoint Enhancement

The existing `POST /api/v1/ai/hub-bot-chat` endpoint returns:
```json
{ "reply": "...", "memory_count": N, "suggestion_count": N, "suggested_actions": [...], "agent_run_id": "..." }
```

This should be extended (or a new `POST /api/v1/ai/lab/run` endpoint created) to also return:
```json
{
  "reply": "...",
  "agent_run_id": "...",
  "tool_calls": [...],
  "draft_actions": [...],
  "suggestions": [...],
  "memories": [...]
}
```

Returning `draft_actions` inline with the run response means the Hub Lab UI can render the draft cards immediately after the prompt without a separate fetch. This also makes the endpoint suitable for the future bot activity feed.

**Recommendation:** Add `draft_actions` to the existing `hub-bot-chat` response rather than creating a new endpoint, to avoid splitting the Lab UI across two call patterns. The field is additive and won't break existing callers.

---

## Frontend Plan

### Hub Lab (AIPage.jsx) Changes

The Hub Lab at [frontend/src/pages/AIPage.jsx](frontend/src/pages/AIPage.jsx) should be the primary testing surface.

#### Chat Tab — Draft Card Area

After the AI response text, any proposed draft actions returned in `draft_actions` should render as cards below the reply. These are in addition to, not replacing, the existing suggestions display.

Each draft card shows:
- **Type badge** — colour-coded: Event (purple), Poll (blue), Reminder (amber)
- **Title** in large text
- **Summary** (AI reason) in muted text
- **Key fields** rendered per type:
  - Event: starts at, location (if present)
  - Poll: options list, closes at, vote mode
  - Reminder: remind at, target (group-wide or named members)
- **Status badge** — Draft / Accepted / Rejected
- **Accept button** — calls `POST /api/v1/ai/draft-actions/{id}/accept`
- **Reject button** — calls `POST /api/v1/ai/draft-actions/{id}/reject`
- **Link to created item** — shown after accept (e.g., "Created #P-12 — View")
- **Validation error display** — shown if accept fails with a 400

#### Draft Actions Tab (new tab, alongside Suggestions/Memories/History)

Shows all draft actions for the group (not just those from the current session). Same card component, but in a scrollable list. Filterable by status and type.

#### Component Structure

```
AIPage.jsx
  └── DraftActionCard.jsx         # single draft card (reusable)
        ├── EventDraftDetail.jsx  # event-specific fields
        ├── PollDraftDetail.jsx   # poll-specific fields
        └── ReminderDraftDetail.jsx
```

`DraftActionCard` should be written as a standalone component from the start, so it can later be dropped into:
- Chat message thread (when @hub proposes something in chat)
- Announcements channel feed
- Bot activity feed
- Homepage activity cards

#### Visual States

| State | Card appearance |
|---|---|
| `draft` | Normal, both buttons active |
| `accepted` | Muted background, Accept button replaced with link to created item |
| `rejected` | Muted/strikethrough, no buttons |
| Accept loading | Spinner on Accept button, Reject disabled |
| Accept error | Error banner below card, buttons re-enabled |

---

## Data Flow

```
User types in Hub Lab
  → POST /api/v1/ai/hub-bot-chat (or /lab/run)
      → SharedHubBotService.process_query()
          → HubAgentRuntime.run()
              → LLM generates structured JSON response
              → tool_calls: [{ "tool": "propose_poll", "arguments": {...} }]
              → ToolRegistry.call("propose_poll", db, group_id=..., user_id=..., ...)
                  → validates arguments
                  → inserts ai_draft_actions row (status="draft")
                  → returns { success: true, draft_action_id: "...", draft: {...} }
          → runtime collects tool_results
          → runtime returns AgentRuntimeResult
      → service collects draft_action_ids from tool results
      → fetches draft_action records from DB
      → returns HubAgentResult with draft_actions list
  → HTTP response: { reply, agent_run_id, draft_actions: [...], ... }

Frontend renders draft card (status: draft, buttons: Accept / Reject)

User clicks Accept
  → POST /api/v1/ai/draft-actions/{id}/accept
      → DraftActionService.accept(id, user_id, db)
          → fetch draft, assert status="draft"
          → re-validate payload_json
          → call type-specific creation:
              Poll   → insert polls row + poll_options + hub_items mirror
              Event  → insert events row + hub_items mirror
              Reminder → insert reminders row + reminder_assignees + hub_items mirror
          → set draft status="accepted", resolved_at, resolved_by_user_id, created_hub_item_id
      → return { success, draft, created_hub_item }

Frontend updates card: status badge = Accepted, link to created Hub Item shown

User clicks Reject
  → POST /api/v1/ai/draft-actions/{id}/reject
      → set status="rejected", resolved_at, resolved_by_user_id
      → return { success, draft }

Frontend updates card: status badge = Rejected, buttons removed
```

---

## Testing Plan

### Backend Tests (`backend/tests/test_ai_draft_actions.py`)

**Repository / Model:**
- Draft action can be created with all required fields
- Draft action defaults: status=draft, proposed_by=ai
- List drafts for a group returns only that group's drafts
- List drafts filtered by status works

**Propose tools:**
- `propose_event` tool creates a draft action with item_type=event
- `propose_poll` tool creates a draft action with item_type=poll
- `propose_reminder` tool creates a draft action with item_type=reminder
- `propose_poll` with fewer than 2 options returns a validation error, no draft created
- `propose_event` with missing `starts_at` returns a validation error, no draft created
- `propose_reminder` with empty text returns a validation error, no draft created
- In dry-run mode, propose tools return a proposed dict but do not insert any DB row

**Accept endpoint:**
- Accepting a poll draft creates a `polls` row + at least 2 `poll_options` rows + a `hub_items` mirror
- Accepting an event draft creates an `events` row + a `hub_items` mirror
- Accepting a reminder draft creates a `reminders` row + a `hub_items` mirror
- After accept: draft status is `accepted`, `created_hub_item_id` is set
- Accepting an already-accepted draft returns 400
- Accepting a rejected draft returns 400

**Reject endpoint:**
- Rejecting a draft sets status=rejected, records resolver
- Rejecting an already-rejected draft returns 400
- Rejecting does not create any Poll, Event, or Reminder row

**AI cannot bypass confirmation:**
- `accept_draft_action` is NOT in the tool registry (no such tool exists for the LLM to call)
- LLM output containing a call to `accept_draft_action` produces a "tool not found" error, not an accepted item

**Group scoping:**
- Draft created for group A is not returned when listing drafts for group B

### Frontend Tests

- Hub Lab renders a draft card when `draft_actions` is present in the response
- Draft card displays correct fields for each type (event, poll, reminder)
- Accept button calls the correct endpoint with correct draft ID
- Reject button calls the correct endpoint with correct draft ID
- After successful accept, card updates to show Accepted state and Hub Item link
- After failed accept (validation error), error message is displayed, buttons re-enabled
- After reject, card updates to show Rejected state, buttons removed

---

## Migration Plan

New file: `backend/migrations/031_ai_draft_actions.sql`

(Next available number after `030_link_messages_to_imported_identities.sql`)

```sql
CREATE TABLE ai_draft_actions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    group_id INTEGER NOT NULL REFERENCES groups(id),
    created_by_user_id UUID NOT NULL REFERENCES members(id),
    proposed_by TEXT NOT NULL DEFAULT 'ai',
    action_type TEXT NOT NULL DEFAULT 'create_hub_item',
    item_type TEXT NOT NULL CHECK (item_type IN ('event', 'poll', 'reminder')),
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'accepted', 'rejected', 'expired')),
    title TEXT NOT NULL,
    summary TEXT,
    payload_json JSONB NOT NULL DEFAULT '{}',
    source TEXT NOT NULL DEFAULT 'hub_lab'
        CHECK (source IN ('hub_lab', 'chat', 'scheduled_job')),
    source_message_id INTEGER REFERENCES messages(id) ON DELETE SET NULL,
    agent_run_id UUID REFERENCES ai_agent_runs(id) ON DELETE SET NULL,
    created_hub_item_id UUID REFERENCES hub_items(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ,
    resolved_by_user_id UUID REFERENCES members(id) ON DELETE SET NULL
);

CREATE INDEX idx_ai_draft_actions_group_id ON ai_draft_actions(group_id);
CREATE INDEX idx_ai_draft_actions_status ON ai_draft_actions(status);
CREATE INDEX idx_ai_draft_actions_created_by ON ai_draft_actions(created_by_user_id);
CREATE INDEX idx_ai_draft_actions_agent_run ON ai_draft_actions(agent_run_id);

CREATE TRIGGER set_ai_draft_actions_updated_at
    BEFORE UPDATE ON ai_draft_actions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
```

> Note: `update_updated_at_column()` trigger function already exists (used by other tables). Do not redefine it.

---

## Implementation Slices

Each slice is a small, safe, independently reviewable commit. Do not implement feature code until the planning doc is merged.

| # | Slice | Files touched |
|---|---|---|
| 1 | **Planning doc** (this file) | `docs/phase_ai_draft_actions.md` |
| 2 | **Migration** — add `ai_draft_actions` table | `backend/migrations/031_ai_draft_actions.sql` |
| 3 | **Model + Repository** — `AIDraftAction` SQLAlchemy model, `AIDraftActionRepository` with create/get/list/update_status | `backend/app/models/ai_draft_action.py`, `backend/app/domains/ai/draft_action_repository.py`, `backend/app/models/__init__.py` |
| 4 | **Service layer** — `DraftActionService` with `accept(id, user_id, db)` and `reject(id, user_id, db)` and type-specific creation logic | `backend/app/domains/ai/draft_action_service.py` |
| 5 | **Hermes tools** — `propose_event`, `propose_poll`, `propose_reminder`, `list_draft_actions` registered in `build_default_registry()` | `backend/app/domains/ai/tools.py` |
| 6 | **API endpoints** — draft actions router with GET/POST/accept/reject | `backend/app/domains/ai/draft_action_router.py`, `backend/app/api/v1/router.py` |
| 7 | **Hub Lab response** — extend `hub-bot-chat` response to include `draft_actions` field; update `HubAgentResult` and service | `backend/app/domains/ai/hub_agent_service.py`, `backend/app/api/v1/ai_router.py` |
| 8 | **Frontend — draft cards** — `DraftActionCard`, type-specific detail sub-components, integration in AIPage Chat tab | `frontend/src/pages/AIPage.jsx`, `frontend/src/components/DraftActionCard.jsx` (and sub-components) |
| 9 | **Frontend — Draft Actions tab** — new tab in AIPage listing all group draft actions | `frontend/src/pages/AIPage.jsx` |
| 10 | **Backend tests** | `backend/tests/test_ai_draft_actions.py` |
| 11 | **Frontend tests** | (test file per project convention) |
| 12 | **Polish** — validation error messages, date parsing edge cases, UI state transitions, doc updates | Various |
| 13 | **Normal chat @hub draft cards** — route chat mentions through shared Hermes runtime, persist `source="chat"` and `source_message_id`, render `[[ai-draft-action:{id}]]` markers with `DraftActionCard` | `backend/app/ai/bot.py`, `backend/app/domains/chat/message_handler.py`, `frontend/src/components/Chat/Message.jsx` |

---

## Open Questions

These areas need confirmation before implementation begins:

1. **Group context in tool calls** — resolved. `HubAgentRuntime` receives server-side tool context and forwards `group_id`, `created_by_user_id`, `source`, `source_message_id`, and `agent_run_id` to tools that accept `_ctx`.

2. **Poll creation stack** — `POST /polls` does more than insert a row: it creates `PollOption` rows and fires notifications. The `DraftActionService.accept()` for polls should replicate the core DB logic but likely skip the notification broadcast (or trigger a lighter one). Confirm whether broadcast on accept is wanted.

3. **Reminder assignees** — The reminder payload includes `group_wide` and `target_user_ids`. On accept, if `group_wide=true`, should we insert a `reminder_assignees` row per current group member (snapshot at accept time), or rely on a group-wide flag on the reminders table? The current `reminders` table doesn't have a `group_wide` column — this may require an additional migration or a convention.

4. **Event `ends_at`** — The current `events` table has `starts_at` but no `ends_at` column. The payload schema includes `ends_at`. Confirm whether to omit it from Phase 1 or add a column.

5. **Hub Lab auth** — The Hub Lab (`AIPage.jsx`) calls `POST /api/v1/ai/hub-bot-chat` with an `Authorization` header. The new draft action endpoints also need this. Confirm the session token is already accessible in the Lab page's API calls.

6. **Suggestions vs. draft actions coexistence** — The existing `create_ai_suggestion` tool and suggestion cards in Hub Lab will continue to exist alongside draft action cards. We need a clear visual distinction so users aren't confused by two similar-looking card types. Consider whether to rename/relabel one set.

7. **Source message ID in chat flow** — resolved. The WebSocket message handler passes the saved chat `message.id` into `HubBot.handle_hub_mention()`, and `propose_*` persists it on `ai_draft_actions.source_message_id`.

8. **Expiry** — The schema includes a `"expired"` status. Is there a plan for a background job to expire old drafts? If not, leave `expired` in the schema but don't implement the job in Phase 1.

9. **Edit-before-accept** — Scoped out of Phase 1 but the schema supports it. Confirm the PATCH endpoint is truly deferred and won't block the initial rollout.

10. **Migration numbering conflict** — Migrations `011` and `018` each have duplicate file numbers in the existing history. The next safe number appears to be `031`. Verify there are no untracked migration files before committing `031_ai_draft_actions.sql`.
