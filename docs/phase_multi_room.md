# Phase: Multi-Room Architecture

## Goal

Allow one Friend Hub deployment to host multiple private groups, each with isolated chat, photos, polls, events, reminders, hub items, memories, notifications and settings.

This is the foundation for turning Friend Hub from a single private app into a hosted service where different friend groups can create and manage their own private spaces.

For the MVP, use:

- One VPS
- One app deployment
- One PostgreSQL database
- One shared backend/frontend
- Shared infrastructure
- Strict room_id isolation in the database and backend

Do not create one VPS/container stack per room yet.

---

## Naming

### User-facing name

Use Space.

Recommended user-facing language:

- App/platform: Friend Hub
- User-owned area: Space
- People inside it: Members
- Owner/admin: Space admin

Example:

“Create a Space for your group chat.”

This feels more natural and product-friendly than tenant, room or community.

### Internal name

Use room internally.

Reason:

- Short
- Clear
- Easy for code/database naming
- Already aligns with the multiple rooms idea

Core domain names:

- rooms
- room_memberships
- room_invites
- room_settings

---

## Product Model

Friend Hub
└── Space / Room
    ├── Members
    ├── Chat
    ├── Photos
    ├── Events
    ├── Polls
    ├── Reminders
    ├── Hub Items
    ├── Memories
    ├── Notifications
    └── Settings

A single user account can belong to many rooms.

A room contains private data that must never leak into another room.

Platform admin and room admin are separate roles.

Platform admin:
  manages the whole Friend Hub deployment

Room owner/admin:
  manages one specific room/space

---

## Architecture Recommendation

Use a shared database with room_id on room-owned tables.

Recommended MVP model:

One PostgreSQL database
One shared app
Every room-owned table has room_id
Every backend query is scoped by current room

Why this is best:

- Simple to run on one VPS
- Easy to back up
- Easy to develop
- Cheap
- Good enough for early customers
- No need for complex deployment automation yet
- Supports many rooms without duplicating infrastructure

Main risk:

- Every query must be room-scoped correctly

Mitigation:

- Centralise room access in backend dependencies/services
- Add tests specifically for cross-room isolation
- Avoid allowing frontend-supplied room_id directly into business logic

---

## Multi-Tenancy Options Considered

### Option 1: Shared database with room_id

Recommended for MVP.

Examples:

- messages.room_id
- photos.room_id
- events.room_id
- polls.room_id
- hub_items.room_id

Best balance of simplicity and scalability.

### Option 2: Separate schema per room

Not recommended yet.

More isolation, but migrations and querying become more awkward.

### Option 3: Separate database per room

Not recommended yet.

Better isolation, but too much operational overhead for early stage.

### Option 4: Separate VPS/container stack per room

Not recommended yet.

Useful much later for premium or enterprise deployments, but not for MVP.

---

## Core Database Tables

### rooms

Stores each private space.

Suggested fields:

- id
- slug
- display_name
- description
- owner_user_id
- status
- plan_key
- trial_started_at
- trial_ends_at
- suspended_at
- deleted_at
- created_at
- updated_at

Suggested status values:

- active
- trial
- suspended
- deleted

Suggested plan_key values:

- free
- trial
- starter
- plus
- pro

---

### room_memberships

Links users to rooms.

Suggested fields:

- id
- room_id
- user_id
- role
- status
- joined_at
- invited_by_user_id
- created_at
- updated_at

Add a unique constraint on:

- room_id
- user_id

Suggested role values:

- owner
- admin
- member
- guest

Suggested status values:

- active
- removed
- left
- pending

---

### room_invites

Room-specific invite codes.

Suggested fields:

- id
- room_id
- invite_code
- created_by_user_id
- max_uses
- use_count
- expires_at
- revoked_at
- created_at
- updated_at

Invite codes must map to one room only.

---

### room_settings

Stores room-level configuration.

Suggested fields:

- room_id
- theme_key
- allow_member_invites
- allow_photo_uploads
- enable_hub_bot
- enable_ai_features
- enable_image_embeddings
- created_at
- updated_at

Important:

enable_image_embeddings should default to false for production.

---

## Existing Tables That Need room_id

Room-owned data should be scoped.

Likely tables needing room_id:

- messages
- photos
- albums
- polls
- poll_votes
- events
- event_attendees
- reminders
- ideas
- hub_items
- comments
- reactions
- memories
- notifications
- search_index
- live_agendas
- live_motions
- chat_vote_actions
- chat_vote_ballots

Tables that should probably remain global:

- users
- user_sessions
- auth tokens
- platform-level admin settings
- push subscriptions

Tables that may need both global and room-aware handling:

- notification_preferences
- theme/user preferences
- AI usage logs
- billing/customer records

---

## Backfill Strategy

The current single-room app should become the first room.

Migration approach:

1. Create rooms
2. Create one default room with slug main
3. Add current admin/user as owner/member
4. Add nullable room_id to room-owned tables
5. Backfill all existing rows with default room ID
6. Make room_id non-null where safe
7. Add indexes
8. Update backend queries
9. Add cross-room isolation tests

Example migration logic:

- Add room_id column
- Backfill existing rows into default room
- Set room_id as not null
- Add indexes using room_id

Recommended indexes:

- messages: room_id, created_at
- photos: room_id, created_at
- notifications: room_id, user_id, created_at
- hub_items: room_id, status, created_at
- events: room_id, start_at
- polls: room_id, created_at

---

## Access Control Model

Every request that touches room-owned data should resolve:

- current user
- current room
- current membership

Backend dependencies should be:

- get_current_user
- get_current_room
- require_room_member
- require_room_admin
- require_room_owner

Service/repository functions should receive room_id explicitly.

Good pattern:

message_repository.list_messages(
    db=db,
    room_id=current_room.id,
    user_id=current_user.id,
)

Bad pattern:

message_repository.list_messages(db=db)

Very bad pattern:

message_repository.list_messages(
    db=db,
    room_id=request.body.room_id,
)

The frontend can select a room, but the backend must verify membership every time.

---

## Current Room Selection

Recommended MVP approach:

Use a current-room context stored client-side and sent via a header:

X-Room-Slug: my-room

Backend resolves:

slug -> room -> membership check -> current_room

Why this is best for MVP:

- Existing API routes can mostly stay the same
- Frontend remains simpler
- Less route churn
- Easier to preserve current single-room behaviour

Example:

GET /api/v1/messages
X-Room-Slug: lads-chat

Alternative later:

/api/v1/rooms/my-room/messages

That is cleaner REST-wise, but creates more frontend/API churn.

For MVP, prefer the header/context approach.

---

## API Design

New room routes:

- GET /api/v1/rooms
- POST /api/v1/rooms
- GET /api/v1/rooms/{room_slug}
- PATCH /api/v1/rooms/{room_slug}
- DELETE /api/v1/rooms/{room_slug}

New membership/invite routes:

- GET /api/v1/rooms/{room_slug}/members
- POST /api/v1/rooms/{room_slug}/invites
- POST /api/v1/join/{invite_code}
- DELETE /api/v1/rooms/{room_slug}/members/{user_id}

Current room routes:

- GET /api/v1/current-room
- POST /api/v1/current-room

Existing room-owned routes should use the selected current room:

- GET /api/v1/messages
- GET /api/v1/photos
- GET /api/v1/events
- GET /api/v1/polls
- GET /api/v1/search
- GET /api/v1/hub-items
- GET /api/v1/notifications

The backend should reject requests if:

- no current room is selected
- the room does not exist
- the user is not a member
- the room is suspended/deleted

---

## Frontend UX

### Room switcher

Add a room switcher near the app title/sidebar.

Mobile:

- Compact dropdown
- Current room name visible
- Switcher accessible from top nav or sidebar

Desktop:

- Show current room name
- Dropdown to switch
- Create Space option if allowed

---

### Room creation flow

Simple MVP flow:

1. Name your Space
2. Choose slug
3. Create
4. Invite friends

Example:

Space name: GC+
Slug: gc-plus

---

### Invite flow

Room admin creates invite link/code.

Members join via:

/join/{invite_code}

or:

Enter invite code

Invite should always map to one room only.

---

### Room admin settings

Settings page should gain a room admin section:

- Space name
- Invite members
- Manage members
- Member roles
- Room theme
- AI enabled/disabled
- Photo uploads enabled/disabled
- Room status

---

### Suspended room page

If a room is suspended, normal members see:

This Space is currently suspended.
Ask the Space owner to reactivate it.

Room owner sees:

This Space is currently suspended.
Reactivation and billing controls will be available here.

---

## Search Isolation

Search must only search the current room by default.

Rules:

- All searchable entities need room_id
- Search indexes need room_id
- Search API must require current room
- Counts/results/snippets must never include another room
- Semantic image search remains disabled in production

Every search query should effectively include:

WHERE room_id = current_room_id

Search should support:

- current room search
- optional future all-rooms search only if explicitly designed
- no accidental cross-room results

---

## Notifications

Notifications should be room-aware.

Add room_id to notifications unless the notification is truly platform-level.

Current-room bell behaviour:

- Show notifications for current room

Optional later:

- Show all-room unread count

Push payloads should include:

- title
- body
- url
- room_slug
- category

Example payload concept:

title: New poll in GC+
body: Vote on Saturday plans
url: /rooms/gc-plus/polls/123
room_slug: gc-plus
category: polls

Notification preferences may eventually become room-specific.

For MVP:

- Keep global user notification preferences
- Add room-aware notification delivery
- Consider per-room preferences later

---

## AI / Hub Bot Isolation

AI must be strongly room-scoped.

Rules:

- Hub Bot can only read current-room data
- Memories are room-scoped
- Chat context is room-scoped
- Search context is room-scoped
- Token usage should be tracked per room
- Expensive AI features can be disabled per room
- Free/trial rooms can have lower limits

Memory records should include:

- room_id
- created_by_user_id
- memory_type
- content
- source_entity_type
- source_entity_id

Never allow one room’s memories into another room’s prompt context.

---

## Photos and File Storage

Photo metadata must have room_id.

Storage paths should also become room-aware.

Recommended path pattern:

rooms/{room_id}/photos/{photo_id}/original.jpg
rooms/{room_id}/photos/{photo_id}/thumb.jpg

Prefer room ID internally because slugs can change.

Important:

- Never serve a file just because the URL exists
- Check user membership before returning file access
- Search/list/delete must be room-scoped
- Photo paths should not leak private room names unnecessarily

---

## Billing Readiness

Do not implement Stripe yet, but shape the data model for it.

Add billing-friendly fields to rooms:

- plan_key
- status
- trial_started_at
- trial_ends_at
- suspended_at
- owner_user_id

Potential future tables:

- room_billing_accounts
- room_usage_limits
- room_usage_daily

Future fields:

- stripe_customer_id
- stripe_subscription_id
- subscription_status
- current_period_end

Plan limits to support later:

- members_limit
- photo_storage_limit_mb
- monthly_ai_token_limit
- monthly_messages_limit
- events_limit
- polls_limit

Suspension behaviour:

active:
  full access

trial:
  full access until trial ends

suspended:
  read-only or blocked, depending on product decision

deleted:
  hidden/inaccessible

---

## Deployment Plan

MVP deployment stays simple:

VPS
├── Caddy
├── frontend
├── backend
├── worker
├── PostgreSQL + pgvector
└── backups

Do not add:

- Kubernetes
- per-room VPS
- per-room containers
- ML image embedding worker

Production image embeddings stay offline/disabled for now.

Future scaling path:

1. Bigger VPS
2. Managed PostgreSQL
3. Separate worker instance
4. Redis/queue if needed
5. External object storage for photos
6. Separate AI worker
7. Per-room isolated deployments only for premium/enterprise cases

---

## Security Risks

### Missing room filters

Risk:

User in room A sees room B data.

Mitigation:

- Every repository function takes room_id
- Add tests for cross-room access
- Add indexes using room_id
- Avoid raw unscoped queries

---

### ID guessing

Risk:

User guesses another room's photo/message/event ID.

Mitigation:

- Always check room membership
- Always query by both id and room_id
- Prefer 404 for inaccessible entities

Good query shape:

SELECT *
FROM photos
WHERE id = photo_id
AND room_id = current_room_id

---

### Admin confusion

Risk:

Platform admin and room admin permissions get mixed up.

Mitigation:

- Separate roles clearly
- is_admin should mean platform admin only
- Room admin comes from room_memberships.role

---

### Invite leakage

Risk:

Invite joins the wrong room or exposes room metadata.

Mitigation:

- Invite code maps to one room
- Check expiry/revocation/use count
- Avoid exposing private room details before join

---

### Notification leakage

Risk:

Push notification reveals another room's private info.

Mitigation:

- Notification has room_id
- Push only to room members
- Payloads should be short
- Avoid sensitive detail in lock-screen notifications

---

### File/photo leakage

Risk:

Photo URLs are accessible across rooms.

Mitigation:

- Room-aware paths
- Membership checks before serving
- No public directory listing

---

### Backup privacy

Risk:

One backup contains all rooms.

Mitigation:

- Secure server access
- Encrypt backups later
- Limit who can access database dumps

---

## Implementation Phases

## Phase 1: Backend Room Foundation

Goal:

Introduce rooms without breaking the current app.

Tasks:

- Add rooms
- Add room_memberships
- Add room_invites
- Add room_settings
- Create default room
- Backfill existing data into default room
- Add room_id to core tables
- Add backend current-room dependency
- Add membership checks
- Update core repositories/services to require room_id

Core tables to start with:

- messages
- photos
- polls
- events
- reminders
- hub_items
- notifications
- memories

Phase 1 is successful when:

- Existing app still works
- All existing data belongs to default room
- Backend has reliable current-room context
- Tests prove room A cannot access room B core data

---

## Phase 2: Frontend Room UX

Goal:

Make rooms visible and usable.

Tasks:

- Add room switcher
- Add room list API integration
- Add current-room storage
- Send current room header with API requests
- Add create room UI
- Add invite/join flow
- Add room members/admin settings
- Add suspended/empty states

Phase 2 is successful when:

- User can belong to multiple rooms
- User can switch rooms
- UI clearly shows current room
- Room admin can invite members

---

## Phase 3: Full Feature Isolation

Goal:

Make every feature room-aware.

Tasks:

- Search scoped to current room
- Photos scoped to current room
- Notifications scoped to current room
- Hub Bot scoped to current room
- Memories scoped to current room
- Comments/reactions scoped to current room
- Live agendas scoped to current room
- Push notification deep links include room route

Phase 3 is successful when:

- No room-owned data leaks across rooms
- Search only returns current-room data
- Notifications only show current-room data
- AI only uses current-room context

---

## Phase 4: Plan Limits and Billing Readiness

Goal:

Prepare for hosted paid rooms.

Tasks:

- Add room plan fields
- Add usage counters
- Add plan limits
- Add trial state
- Add suspended state
- Add owner-only upgrade/reactivation placeholders
- Add admin dashboard for room usage

Do not add Stripe yet unless ready.

Phase 4 is successful when:

- Rooms can be active/trial/suspended
- Limits can be enforced
- Data model is Stripe-ready

---

## Phase 5: Hosted Signup and Stripe

Goal:

Allow public hosted room creation.

Tasks:

- Landing page
- Create room checkout flow
- Stripe customer/subscription mapping
- Trial flow
- Payment failure handling
- Room suspension/reactivation
- Usage-based limits if needed

Phase 5 is successful when:

- Someone can create a hosted Friend Hub Space
- Pay monthly
- Invite friends
- Keep using it independently

---

## Testing Strategy

Add tests for:

- User in room A cannot read room B messages
- User in room A cannot read room B photos
- User in room A cannot read room B events
- User in room A cannot search room B content
- User in room A cannot receive room B notifications
- Same user can switch between rooms
- Room admin can invite members
- Normal member cannot manage members
- Invite code joins correct room
- Suspended room blocks writes
- Default backfilled room still works

Backend tests should specifically attempt cross-room access by ID.

Example test shape:

1. Create user A
2. Create room A
3. Create room B
4. Add user A to room A only
5. Create message in room B
6. Request message from room B while current room is room A
7. Expect 404 or 403

Prefer returning 404 for inaccessible room-owned entities to avoid confirming existence.

---

## Performance Notes

Indexes should usually include room_id.

Recommended indexes:

- messages: room_id, created_at
- photos: room_id, created_at
- notifications: room_id, user_id, created_at
- hub_items: room_id, status, created_at
- events: room_id, start_at
- polls: room_id, created_at

Room scoping should improve query performance as data grows.

---

## Production Feature Flags

Recommended flags:

ENABLE_MULTI_ROOM=true
ENABLE_IMAGE_EMBEDDINGS=false
ENABLE_AI_FEATURES=true
ENABLE_ROOM_BILLING=false
ENABLE_PUBLIC_ROOM_SIGNUP=false

For now:

ENABLE_IMAGE_EMBEDDINGS=false
ENABLE_PUBLIC_ROOM_SIGNUP=false
ENABLE_ROOM_BILLING=false

---

## First Implementation Prompt: Phase 1

Implement Phase 1 of the Friend Hub multi-room architecture.

Goal:
Introduce backend room support without breaking the existing single-room app.

Context:
Friend Hub is currently a single-room FastAPI + SQLAlchemy async + PostgreSQL + React/Vite app. It has chat, photos, polls, events, reminders, hub items, notifications, memories, search and Hub Bot features. The deployment is one VPS with Docker Compose, Caddy and local PostgreSQL.

For this phase, do not implement billing, Stripe, public signup, per-room VPS, Kubernetes or image embedding workers.

Use the internal domain name room.
User-facing copy can use Space later, but backend/database naming should use room.

Tasks:

1. Add migrations for:
   - rooms
   - room_memberships
   - room_invites
   - room_settings

2. Create one default room for existing deployments:
   - slug: main
   - display name: Main Space
   - status: active

3. Add the current main/admin user as room owner where possible.
   If the migration cannot safely infer this, create a clear follow-up bootstrap script.

4. Add room_id to core room-owned tables:
   - messages
   - photos
   - polls
   - events
   - reminders
   - hub_items
   - notifications
   - memories

   If some table names differ, inspect the existing schema and apply the same principle.

5. Backfill all existing rows into the default room.

6. Make room_id non-null after backfill where safe.

7. Add useful indexes using room_id, especially for list queries.

8. Add backend room domain code:
   - room model
   - room membership model
   - room invite model
   - room settings model
   - repository/service code following existing project patterns

9. Add FastAPI dependencies:
   - get_current_room
   - require_room_member
   - require_room_admin
   - require_room_owner

10. Current-room resolution:
    - Prefer X-Room-Slug header
    - If missing and the user belongs to exactly one room, use that room
    - If missing and the user belongs to multiple rooms, return a clear error requiring room selection
    - Always verify membership

11. Update core repositories/services so room-owned queries are scoped by room_id.

12. Do not trust frontend-supplied room IDs directly.
    Resolve room from slug/header/session and verify membership server-side.

13. Add API routes:
    - GET /api/v1/rooms
    - GET /api/v1/current-room

    Keep this phase minimal. Full create/invite/member UI can come later.

14. Add tests for:
    - default room creation/backfill
    - current-room resolution
    - user can access their own room data
    - user cannot access another room's messages/photos/events/hub items
    - user cannot use a room slug they are not a member of
    - existing single-room behaviour still works

15. Keep the frontend changes minimal:
    - do not build full room switcher yet
    - only add any required API/header support if necessary
    - existing app should continue working for a user with one room

Important:

- Avoid breaking existing APIs
- Keep migrations additive and safe
- Follow existing project conventions
- Use 404 or 403 consistently for inaccessible cross-room data
- Avoid touching unrelated styling or features
- Do not enable image embeddings in production

Output:

- Summarise changed files
- Summarise new migrations
- Summarise new models
- Summarise new dependencies
- Summarise new routes
- Summarise test results

---

## Key Principle

Every room-owned query should answer this question:

“Is this user a member of this room, and is this data inside that room?”

If yes, allow it.

If no, block it.

That is the whole foundation of multi-room Friend Hub.