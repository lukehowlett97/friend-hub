# Phase: Chat Governance Vote Actions

## Goal

Build a reusable chat governance voting system, starting with nickname-change votes.

The first shipped behaviour should be:

User proposes changing a member's nickname
-> group members vote yes/no
-> vote passes or expires based on threshold/expiry
-> if passed, target user's nickname updates
-> Hub Bot/system messages and chat cards show the vote and result

This phase should avoid a dead-end nickname-only implementation. Nickname change is the first supported vote action, but the data model and service boundaries should support future governance actions.

## Implementation Status

Implemented:

- backend vote-action foundation
- migration `032_chat_vote_actions.sql`
- models `chat_vote_action.py` and `chat_vote_ballot.py`
- governance repository/service/router
- API endpoints under `/api/v1/governance/votes`
- nickname vote creation/casting/cancel/manual resolve
- denormalised yes/no counts with ballot source of truth
- majority-of-active-members threshold
- optional Hub Bot chat message integration for open/result messages
- `[[vote-action:{id}]]` chat marker rendering
- compact frontend `VoteActionCard`

Partial/remaining:

- no scheduled expiry job yet
- no `PersonPopup` proposal flow yet
- no future vote action types yet
- live updates are limited to local refresh/polling and broadcasted bot messages; cross-client count updates are not yet pushed over websocket

## Product Behaviour

### Propose Nickname Change

Example:

- Luke proposes renaming Tom to "Taxi Tom".
- A vote action is created with:
  - proposed action
  - proposer
  - target member
  - current nickname
  - proposed nickname
  - yes/no counts
  - expiry time
  - status: open/passed/expired/cancelled

The API-backed flow posts a Hub Bot message containing `[[vote-action:{id}]]`; the chat renderer swaps that marker for a governance vote card using the same marker-card approach as agenda polls.

The card should eventually show:

- title/summary
- proposer
- target member
- current nickname
- proposed nickname
- yes/no counts
- expiry time
- status
- yes/no buttons while open

### Vote Yes/No

- Each active group member can vote once.
- Vote changes are allowed while the vote is open.
- Changing a vote updates the existing ballot and recalculates counts; it must not duplicate counts.
- Creator/proposer can vote.
- Target can vote.
- Non-members cannot vote.
- Inactive, hidden, bot, system, or test users do not count as active voters.

Allowing vote changes matches the existing poll UX and is forgiving for a small friend group.

### Resolve Vote

- A vote passes immediately when the pass threshold is met.
- For v1, a vote expires when the threshold has not been met before `expires_at`.
- `failed` remains available in the schema, but v1 normal expiry should use `expired`.
- On pass, the target user's `users.nickname` value is updated.
- On expiry/cancel, no profile change is made.
- Result chat messages are created for passed, expired, and cancelled votes when chat message integration is enabled.

### Existing Policy Integration

This feature interacts with `NicknameChangePolicy`:

- `admin_only`: regular members cannot propose nickname votes; owner/admin may still use direct edit/override paths.
- `self_edit`: members can edit their own nickname directly; other-member nickname changes may use the vote system.
- `vote_required`: nickname changes by non-admins must use the vote system.
- `free_for_all`: direct edits may remain allowed; vote proposals can still exist as a fun path.

Initial recommendation:

- Keep the current default policy as-is until a real per-group governance setting exists.
- Make the vote service accept/consult a policy value so `vote_required` can plug in cleanly.
- Preserve existing direct profile behaviour.

Nickname uniqueness is an open decision. Enforce only if existing nickname/session logic requires it; otherwise allow duplicate display nicknames for v1.

## Data Model Plan

Add a dedicated governance vote model instead of using the existing `polls` tables as the action-execution source of truth.

Existing agenda polls are useful UI/message precedent, but they currently model scheduled polls and chat cards. Governance vote actions need explicit resolution semantics and action payloads.

### `chat_vote_actions`

Fields:

- `id`
- `group_id`
- `created_by_user_id`
- `target_user_id` nullable
- `action_type`
- `status`
- `title`
- `summary`
- `payload_json`
- `threshold_type`
- `threshold_value`
- `yes_count`
- `no_count`
- `expires_at`
- `resolved_at`
- `created_at`
- `updated_at`
- `resolved_by_user_id` nullable
- `open_message_id` nullable
- `result_message_id` nullable

Initial `action_type`:

- `nickname_change`

Future `action_type` values:

- `display_role_change`
- `restriction_apply`
- `restriction_remove`
- `rule_create`
- `rule_repeal`
- `council_motion`

Statuses:

- `open`
- `passed`
- `failed`
- `expired`
- `cancelled`

For v1, `expired` means the threshold was not met before `expires_at`. `failed` is reserved for future explicit failed resolutions unless implementation genuinely needs it.

`payload_json` for `nickname_change` should include:

- `target_session_id`
- `current_nickname`
- `proposed_nickname`
- optional `reason`

### `chat_vote_ballots`

Fields:

- `id`
- `vote_action_id`
- `user_id`
- `vote`
- `created_at`
- `updated_at`

Constraints:

- one ballot per user per vote action
- `vote in ('yes', 'no')`
- `action_type` check constraint
- `status` check constraint
- `threshold_type` check constraint
- `group_id` foreign key to `groups.id`
- user foreign keys to `users.id`
- message foreign keys to `messages.id`

### Counts

Store `yes_count` and `no_count` denormalised on `chat_vote_actions`.

`chat_vote_ballots` remains the source of truth. The service recalculates counts after each ballot insert/update so reads are simple and the card/API can return counts without repeatedly aggregating.

## Backend Architecture

Likely files:

- `backend/migrations/032_chat_vote_actions.sql`
- `backend/app/models/chat_vote_action.py`
- `backend/app/models/chat_vote_ballot.py`
- `backend/app/domains/governance/__init__.py`
- `backend/app/domains/governance/vote_repository.py`
- `backend/app/domains/governance/vote_service.py`
- `backend/app/domains/governance/vote_router.py`
- `backend/app/api/v1/router.py` or existing v1 router wiring
- `backend/tests/test_chat_governance_votes.py`

### Repository Responsibilities

- create vote action
- fetch vote action by id
- list vote actions for group
- fetch active member by session id
- count active group members
- get current user's ballot
- upsert ballot
- recalculate yes/no counts
- update vote action status/resolution metadata
- update target user nickname on pass

Membership source for v1:

- default group `main`
- `group_members.group_id`
- active, visible, non-bot, non-test, non-system users

This should mirror the current member list filtering as closely as possible.

### `create_nickname_vote()`

Responsibilities:

- validate proposer is an active group member
- validate target is an active group member
- validate proposed nickname is non-empty and within existing nickname length/format rules
- decide whether nickname uniqueness is required by existing identity/session constraints
- validate policy allows vote proposal
- create `chat_vote_actions` row with `action_type = nickname_change`
- store current/proposed nickname in `payload_json`
- return serialized vote state

Core service callers can run in no-message mode. The API path enables chat messages and creates an open Hub Bot message containing `[[vote-action:{id}]]`, storing the message id in `open_message_id`.

### `cast_vote()`

Responsibilities:

- validate vote action exists
- validate status is `open`
- validate voter is an active group member
- insert or update the user's ballot
- recalculate yes/no counts
- resolve immediately if pass threshold is reached
- return serialized vote state plus whether this request resolved the vote

### `resolve_vote()`

Responsibilities:

- if passed:
  - update target user nickname
  - set status `passed`
  - set `resolved_at`
  - set `resolved_by_user_id` when applicable
- if expired/cancelled:
  - do not update nickname
  - set terminal status and metadata
- be idempotent for already-terminal votes

When chat integration is enabled, terminal resolution creates a single result Hub Bot message and stores `result_message_id`. Repeated resolve calls must not duplicate result messages.

### `expire_votes()`

Responsibilities:

- find open votes with `expires_at <= now`
- mark them `expired`
- do not update nickname
- return expired vote ids or serialized votes for later result-message integration

Do not implement a scheduler yet. The method is designed so it can be called by a later scheduled/background job. When chat integration is enabled, expired votes can create result messages through the same result-message path.

## Threshold Recommendation

Use majority of active group members for the first implementation.

Formula:

- active member count = number of eligible active human group members
- pass threshold = `floor(active_member_count / 2) + 1`
- vote passes immediately when `yes_count >= threshold`

Reasons:

- simple mental model for small friend groups
- avoids a tiny turnout renaming someone while most members are absent
- no need to wait for expiry once clear majority is reached
- avoids complicated percentage configuration in v1

`threshold_type` should initially be `active_member_majority`.

`threshold_value` should store the computed required yes count at creation time. This makes old vote behaviour stable even if membership changes while a vote is open.

## API Plan

Proposed endpoints:

- `POST /api/v1/governance/votes/nickname`
- `GET /api/v1/governance/votes`
- `GET /api/v1/governance/votes/{id}`
- `POST /api/v1/governance/votes/{id}/ballot`
- `POST /api/v1/governance/votes/{id}/cancel`
- `POST /api/v1/governance/votes/{id}/resolve`

`resolve` should be admin/internal only.

Use a single target identifier in the API. Prefer the identifier already available in `PersonPopup` and member profile calls. For v1, use `target_session_id`.

Do not accept ambiguous "uuid-or-session-id" in one field.

### Create Nickname Vote Request

```json
{
  "target_session_id": "member-session-id",
  "proposed_nickname": "Taxi Tom",
  "reason": "optional",
  "expires_at": "optional ISO datetime"
}
```

Defaults:

- `expires_at`: default to a short duration suitable for chat, such as 10 minutes from creation.
- `reason`: optional.

### Cast Ballot Request

```json
{
  "vote": "yes"
}
```

Allowed vote values:

- `yes`
- `no`

### Response Shape

Responses should include:

- vote action id
- group id
- action type
- status
- title
- summary
- proposer
- target member
- payload
- threshold type/value
- yes/no counts
- expiry/resolution timestamps
- current user's vote
- `resolved: true/false` for mutation responses

## Frontend Plan

Initial frontend chat-card work is implemented.

Planned components:

- `VoteActionCard.jsx`
- `NicknameVoteCard.jsx` only if a specialised component keeps the generic card simple
- governance page/list later

### PersonPopup Integration

Add a "Propose nickname change" flow when:

- direct nickname edit is blocked by `vote_required`, or
- a member is trying to rename someone else and policy allows vote proposals.

Use `member.session_id` as `target_session_id`.

Preserve existing profile editing behaviour for currently allowed direct edits.

### Chat Integration

Add after the core vote service works:

Implemented:

- post/open a Hub Bot message when a vote is created
- embed `[[vote-action:{id}]]`
- render the marker as a vote card in chat
- show yes/no buttons
- refresh counts after voting
- show passed/expired/cancelled status
- post result message after resolution

Initial realtime behaviour can be simple:

- refresh the card after local vote submission
- poll while open if needed
- defer websocket broadcast polish unless low-cost

Current limitation:

- vote count updates are not broadcast to every already-open card in realtime; cards refresh after local voting and poll while open.

## Testing Plan

### Backend Tests

Add `backend/tests/test_chat_governance_votes.py` covering:

- migration/model columns exist
- create nickname vote
- reject blank nickname
- reject too-short/too-long nickname
- reject target outside group
- reject proposer outside group
- respect nickname policy
- cast yes vote
- cast no vote
- changing vote updates counts without duplication
- duplicate vote does not duplicate counts
- pass threshold updates nickname
- expired vote does not update nickname
- cancelled vote cannot be voted on
- non-members cannot vote
- open marker chat message creation
- stored `open_message_id`
- result message creation on pass/cancel
- no duplicate result message on repeated resolve

### Frontend Tests/Manual Checks

After frontend integration:

- vote card appears from `[[vote-action:{id}]]`
- yes/no buttons work
- counts update after voting
- passed vote changes displayed nickname
- expired vote leaves nickname unchanged
- mobile layout works
- propose nickname vote from profile popup remains future work

## Implementation Slices

1. Planning doc only. Done.
2. Migration + models for `chat_vote_actions` and `chat_vote_ballots`. Done.
3. Repository with create/get/list/upsert ballot/update status/update nickname. Done.
4. Core service with nickname vote creation, voting, resolution, and expiry. Done.
5. API endpoints. Done.
6. Chat open/result message integration. Done.
7. Frontend vote card. Done.
8. `PersonPopup` "Propose nickname change" flow. Remaining.
9. Expiry/cleanup scheduler later. Remaining.
10. Extend to generalised vote action types later. Remaining.

## Open Questions

- Should duplicate display nicknames be allowed in v1? Recommendation: allow duplicates unless existing identity/session logic requires uniqueness.
- Should `failed` be used at all in v1? Recommendation: use `expired` for threshold-not-met and reserve `failed`.
- Should vote cards poll or receive websocket updates? Recommendation: poll/refresh first, then add websocket polish.
- Should active member threshold be fixed at creation or recalculated live? Recommendation: store computed `threshold_value` at creation.
- Should result chat messages be generated by service or integration layer? Recommendation: keep core service independent, then add chat integration separately.
- Should existing agenda polls link to governance vote actions later? Recommendation: not for v1; keep systems separate until there is a clear product need.

## Remaining Work

- Add `PersonPopup` "Propose nickname change" flow.
- Add an expiry/background job that calls `expire_votes()`.
- Add future vote action types.
- Add websocket event/broadcast support for live count/status updates on already-rendered cards.
- Add a governance list/page only if the chat card flow needs a secondary surface.

## Constraints

- Do not implement silly restrictions yet.
- Do not implement group constitution/rules yet.
- Do not implement council sessions yet.
- Do not build a full admin panel.
- Keep the first feature focused on nickname-change votes.
- Keep the data model reusable for future vote action types.
- Preserve existing profile and chat behaviour.
- Do not break existing member profile tests.
