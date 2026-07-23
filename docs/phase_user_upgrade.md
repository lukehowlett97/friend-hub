# Phase — User Level Up

## 1. Summary

This phase upgrades Friend-Hub from temporary nickname-based sessions to persistent user identity.

The current model treats a browser/WebSocket session as the user. That works for a toy chat, but it causes problems once the app needs real members, roles, permissions, settings, ownership, and persistent social features.

The goal is to introduce a proper user model:

* `username` — fixed, unique login identity.
* `nickname` — fun visible display name, editable.
* `user_id` — stable internal identifier used by messages, reactions, roles, events, photos, etc.
* `session token` — remembers a browser/device after first login.
* `role` — owner/admin/member for group-level permissions.

This phase should make the app feel like:

> “I joined once, the server knows who I am, and I can come back without re-entering my nickname.”

It should also fix the current class of bugs where a WebSocket session can send messages before a valid user row exists.

---

## 2. Current Problem

Current behaviour appears to be:

1. Browser opens WebSocket with a generated `session_id`.
2. User enters a nickname.
3. Backend tries to create/register a user for that session.
4. If nickname setup fails, the frontend may still allow messages.
5. Backend attempts to insert a message linked to `user_session_id`.
6. Postgres rejects the insert if that session is not present in `users`.

Example failure:

```text
Nickname is already taken
insert or update on table "messages" violates foreign key constraint "messages_user_session_id_fkey"
Key (user_session_id) is not present in table "users".
```

This happens because the current app has mixed together:

* WebSocket connection identity
* temporary session identity
* display nickname
* database user identity

These should be separate concepts.

---

## 3. Desired Identity Model

### 3.1 Concepts

| Concept      | Meaning                |       Example |        Editable? |         Unique? |
| ------------ | ---------------------- | ------------: | ---------------: | --------------: |
| `user_id`    | Internal stable UUID   |      `4f2...` |               No |             Yes |
| `username`   | Login/account identity |        `luke` |       Usually no |             Yes |
| `nickname`   | Visible display name   | `Chat GBeanT` |              Yes | Not necessarily |
| `session_id` | Browser/device session |      `abc...` |               No |             Yes |
| `role`       | Permission level       |       `owner` | Admin-controlled |              No |

### 3.2 Example

```text
username: luke
nickname: Chat GBeanT
role: owner
```

Chat displays:

```text
Chat GBeanT: Sup lads
```

Backend stores:

```text
message.user_id = 4f2...
```

The username remains the stable identity, while the nickname can be fun and changeable.

---

## 4. Product Behaviour

### 4.1 First Visit

The user lands on the app and is asked to create or claim their identity:

```text
Username: luke
Nickname: Chat GBeanT
Invite code: ********
```

Backend validates:

* invite code is correct
* username is available
* username format is valid
* nickname format is valid

If valid:

* create `users` row
* create `user_sessions` row
* return a session token
* frontend stores the token
* user enters the app

### 4.2 Returning Visit

The browser already has a stored token.

Frontend calls:

```http
GET /api/v1/auth/me
```

Backend returns:

```json
{
  "user": {
    "id": "...",
    "username": "luke",
    "nickname": "Chat GBeanT",
    "role": "owner"
  }
}
```

The app loads immediately. No nickname prompt.

### 4.3 Nickname Change

User can later change visible nickname:

```http
PATCH /api/v1/users/me
```

Request:

```json
{
  "nickname": "Bean Commander"
}
```

This should update future display names and member lists.

Historical messages can either:

1. Always display the latest nickname by joining through `users`.
2. Store `display_name_snapshot` on each message.

Recommended v1: always display the current nickname. Simpler and good enough.

---

## 5. Recommended Authentication Approach

This is a private friend app, so avoid heavy auth for now.

### 5.1 Recommended v1: Invite Code + Persistent Session Token

Flow:

```text
First visit -> username + nickname + invite code -> session token
Returning visit -> token identifies user
```

Benefits:

* no password UX
* no email provider needed
* cheap and simple
* works well for a small private group

Trade-offs:

* if someone gets the invite code, they can create an account
* if someone gets the token, they can impersonate that user
* token revocation needs to be supported eventually

### 5.2 Token Storage

Two possible frontend storage options:

#### Option A — localStorage

Simplest:

```text
localStorage.friend_hub_token = "..."
```

Pros:

* easy to implement
* easy to debug
* works with WebSocket auth via query param or initial auth message

Cons:

* vulnerable if the frontend ever has XSS
* token visible to JavaScript

#### Option B — HTTP-only cookie

Better long-term:

```http
Set-Cookie: friend_hub_session=...; HttpOnly; Secure; SameSite=Lax
```

Pros:

* safer against token theft via JavaScript
* browser sends automatically
* cleaner REST auth

Cons:

* slightly more setup
* CORS/cookie behaviour can be annoying locally
* WebSocket cookie auth needs careful handling

### 5.3 Recommendation

For v1:

* Use localStorage token if speed/simplicity matters.
* Use HTTP-only cookie if you want cleaner production foundations.

Given this app is evolving into a real social hub, the best implementation is:

```text
HTTP-only cookie for REST + WebSocket auth
```

But if Codex struggles, fall back to:

```text
Bearer token in Authorization header for REST
Token query param or first auth message for WebSocket
```

---

## 6. Database Design

### 6.1 New `users` Table Shape

The existing `users` table may need refactoring.

Recommended target:

```sql
CREATE TABLE users (
    id UUID PRIMARY KEY,
    username VARCHAR(32) UNIQUE NOT NULL,
    nickname VARCHAR(64) NOT NULL,
    role VARCHAR(16) NOT NULL DEFAULT 'member',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP,
    last_seen_at TIMESTAMP,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);
```

Notes:

* `id` is the stable internal identity.
* `username` is fixed and unique.
* `nickname` is visible and editable.
* `role` is simple for now; can later move to `group_members`.
* `last_seen_at` helps member list/status later.
* `is_active` supports soft-deactivating users.

### 6.2 New `user_sessions` Table

```sql
CREATE TABLE user_sessions (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT UNIQUE NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMP NOT NULL,
    last_used_at TIMESTAMP,
    user_agent TEXT,
    ip_address INET,
    revoked_at TIMESTAMP
);
```

Notes:

* Store only `token_hash`, never the raw token.
* Raw token is only shown to the browser once.
* `expires_at` allows automatic expiry.
* `revoked_at` supports logout/revocation.

### 6.3 Message Table Refactor

Current messages likely reference `user_session_id`.

Target:

```sql
ALTER TABLE messages
ADD COLUMN user_id UUID REFERENCES users(id);
```

Eventually replace:

```text
messages.user_session_id
```

with:

```text
messages.user_id
```

Recommended staged migration:

1. Add nullable `user_id`.
2. New messages write `user_id`.
3. Backfill existing messages where possible.
4. Update reads to prefer `user_id`.
5. Later remove `user_session_id` when safe.

### 6.4 Reaction Table Refactor

Current reactions likely reference `user_session_id`.

Target:

```sql
ALTER TABLE reactions
ADD COLUMN user_id UUID REFERENCES users(id);
```

Same staged approach:

1. Add nullable `user_id`.
2. New reactions write `user_id`.
3. Backfill if possible.
4. Update logic to use `user_id` for uniqueness/toggle.
5. Later remove `user_session_id`.

### 6.5 Future Group Membership

Phase 2 Social Hub may introduce groups.

Long-term model:

```sql
CREATE TABLE groups (
    id UUID PRIMARY KEY,
    name VARCHAR(80) NOT NULL,
    description TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE group_members (
    group_id UUID NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role VARCHAR(16) NOT NULL DEFAULT 'member',
    joined_at TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (group_id, user_id)
);
```

For this phase, it is acceptable to keep `role` directly on `users`, as long as the design does not block moving roles into `group_members` later.

---

## 7. Backend Architecture Plan

### 7.1 New Domain

Add an auth/user domain rather than stuffing this into chat code.

Recommended folders:

```text
backend/app/domains/auth/
├── __init__.py
├── repository.py
├── service.py
├── schemas.py
└── tokens.py

backend/app/domains/users/
├── __init__.py
├── repository.py
├── service.py
└── schemas.py
```

### 7.2 Auth Responsibilities

`auth/repository.py`:

* create user
* find user by username
* create session
* find session by token hash
* revoke session
* update session last_used_at

`auth/service.py`:

* validate registration input
* validate invite code
* generate raw token
* hash token
* create user/session transactionally
* authenticate token
* return current user
* logout/revoke session

`auth/tokens.py`:

* generate secure random token
* hash token using SHA-256 or HMAC-SHA256
* constant-time comparison where appropriate

### 7.3 User Responsibilities

`users/repository.py`:

* get user by id
* get all active users
* update nickname
* update last_seen_at
* update role

`users/service.py`:

* validate nickname
* enforce permissions for role changes
* return member list

---

## 8. API Plan

### 8.1 Register / First Login

```http
POST /api/v1/auth/register
```

Request:

```json
{
  "username": "luke",
  "nickname": "Chat GBeanT",
  "invite_code": "secret-code"
}
```

Response:

```json
{
  "user": {
    "id": "...",
    "username": "luke",
    "nickname": "Chat GBeanT",
    "role": "owner"
  },
  "token": "raw-session-token-if-using-localStorage"
}
```

If using HTTP-only cookie, response does not need `token`; backend sets cookie.

### 8.2 Current User

```http
GET /api/v1/auth/me
```

Response:

```json
{
  "user": {
    "id": "...",
    "username": "luke",
    "nickname": "Chat GBeanT",
    "role": "owner"
  }
}
```

### 8.3 Logout

```http
POST /api/v1/auth/logout
```

Behaviour:

* revoke current session
* clear cookie or ask frontend to remove local token

### 8.4 Update Own Profile

```http
PATCH /api/v1/users/me
```

Request:

```json
{
  "nickname": "Bean Commander"
}
```

Response:

```json
{
  "user": {
    "id": "...",
    "username": "luke",
    "nickname": "Bean Commander",
    "role": "owner"
  }
}
```

### 8.5 Members List

```http
GET /api/v1/members
```

Response:

```json
{
  "members": [
    {
      "id": "...",
      "username": "luke",
      "nickname": "Bean Commander",
      "role": "owner",
      "is_online": true,
      "last_seen_at": "2026-05-01T12:00:00Z"
    }
  ]
}
```

### 8.6 Change Role

```http
PATCH /api/v1/members/{user_id}/role
```

Request:

```json
{
  "role": "admin"
}
```

Backend must enforce owner/admin permissions.

---

## 9. WebSocket Plan

### 9.1 Current Problem

Current flow lets an unauthenticated WebSocket session connect and then relies on `set_nickname` to create identity.

This should be replaced.

### 9.2 Target Flow

Recommended:

```text
Browser has session token
Browser opens WebSocket
Backend authenticates token
ConnectionManager maps websocket connection -> user_id
Chat messages use user_id
Presence uses user_id + nickname
```

### 9.3 Auth Options For WebSocket

#### Option A — Cookie Auth

If using HTTP-only cookie:

```text
new WebSocket("wss://domain/ws")
```

Browser sends cookies automatically if same-origin.

Backend reads session cookie during WebSocket handshake.

#### Option B — Query Param Token

If using localStorage:

```text
new WebSocket(`wss://domain/ws?token=${token}`)
```

Pros:

* easy
* works well in development

Cons:

* token can appear in logs
* less clean/security-conscious

#### Option C — Initial Auth Message

```text
connect websocket
send { type: "auth", token: "..." }
server accepts/rejects
```

Pros:

* token not in URL

Cons:

* connection exists briefly before auth
* every handler must check authenticated state

### 9.4 Recommendation

For clean production design:

```text
Use same-origin HTTP-only cookie auth.
```

For fastest implementation:

```text
Use token query param, then migrate to cookie later.
```

### 9.5 ConnectionManager Changes

Current manager likely maps:

```python
active_connections: dict[str, WebSocket]
session_nicknames: dict[str, str]
```

Target:

```python
active_connections: dict[str, WebSocket]  # connection_id -> websocket
connection_users: dict[str, UUID]         # connection_id -> user_id
user_connections: dict[UUID, set[str]]    # user_id -> connection_ids
```

This allows:

* same user open in multiple tabs
* presence remains accurate
* online users are unique by user, not by tab
* disconnect only marks user offline when all connections close

### 9.6 Presence Logic

On connect:

1. authenticate user
2. add connection
3. update `last_seen_at`
4. broadcast `online_users`

On disconnect:

1. remove connection
2. if user has no remaining connections, update `last_seen_at`
3. broadcast `online_users`

Online users should return unique users:

```json
{
  "type": "online_users",
  "users": [
    {
      "id": "...",
      "username": "luke",
      "nickname": "Chat GBeanT"
    }
  ]
}
```

---

## 10. Frontend Plan

### 10.1 Auth State

Create a central auth state/hook.

Suggested files:

```text
frontend/src/auth/AuthProvider.jsx
frontend/src/auth/useAuth.js
frontend/src/api/auth.js
frontend/src/api/client.js
```

State:

```js
{
  user,
  isLoading,
  isAuthenticated,
  login/register,
  logout,
  refreshMe,
}
```

### 10.2 First Visit UI

Create an identity setup screen:

```text
frontend/src/pages/WelcomePage.jsx
frontend/src/components/Auth/RegisterForm.jsx
```

Fields:

* username
* nickname
* invite code

Validation:

* username required
* username lowercase, simple characters only
* nickname required
* nickname max length
* invite code required

### 10.3 Returning Visit UI

On app boot:

1. `AuthProvider` calls `/api/v1/auth/me`.
2. If valid, render app shell.
3. If invalid/missing, render welcome/register page.

### 10.4 API Client

Create a small API helper that automatically attaches token if using localStorage.

Example behaviour:

```js
api.get("/api/v1/auth/me")
api.post("/api/v1/auth/register", payload)
```

If using cookie auth, use:

```js
credentials: "include"
```

### 10.5 WebSocket Hook Changes

Current hook likely generates a session id and connects to:

```text
/ws/{session_id}
```

Target:

```text
/ws
```

or:

```text
/ws?token=<token>
```

The hook should require an authenticated user before connecting.

Do not connect WebSocket while auth is loading.

Do not allow message sends when unauthenticated.

---

## 11. Validation Rules

### 11.1 Username

Recommended rules:

* lowercase only
* 3–24 characters
* letters, numbers, underscore, hyphen
* unique
* cannot be changed in v1

Regex:

```text
^[a-z0-9_-]{3,24}$
```

### 11.2 Nickname

Recommended rules:

* 1–40 characters
* trim whitespace
* allow spaces and fun characters
* not required to be unique
* editable

### 11.3 Invite Code

Simple v1:

```env
INVITE_CODE=some-secret
```

Backend compares submitted invite code to env var.

Later:

* per-user invite links
* expiring invite codes
* admin-generated invites

---

## 12. Permissions And Roles

This phase should lay groundwork for roles without building a huge permission system.

### 12.1 Roles

Start with:

```text
owner
admin
member
```

Optional later:

```text
guest
viewer
```

### 12.2 Static Permission Map

Backend:

```python
ROLE_PERMISSIONS = {
    "owner": {
        "manage_members",
        "manage_roles",
        "edit_group_settings",
        "delete_any_message",
    },
    "admin": {
        "manage_members",
        "delete_any_message",
    },
    "member": set(),
}
```

### 12.3 Enforcement

Frontend may hide buttons, but backend must enforce permissions.

Example:

```text
Only owner can promote someone to admin.
Only owner/admin can remove members.
Only message owner can edit own message.
Owner/admin can delete any message.
```

### 12.4 Bootstrap First Owner

Need a rule for who becomes owner.

Recommended v1:

```text
If no users exist, first registered user becomes owner.
Every later user becomes member.
```

This is simple and perfect for initial setup.

---

## 13. Migration Strategy

This is the riskiest part because existing messages reference session IDs.

### 13.1 Development DB Option

If the app is not live with valuable data yet, easiest option:

```text
reset dev DB and rebuild schema cleanly
```

This is fastest and avoids migration complexity.

### 13.2 Production-Safe Option

If preserving data matters:

1. Add new columns/tables without removing old ones.
2. Add `users.id`, `users.username`, `users.nickname`.
3. Add `user_sessions`.
4. Add `messages.user_id` nullable.
5. Add `reactions.user_id` nullable.
6. Update backend writes to use `user_id`.
7. Update reads to handle both old and new data.
8. Backfill old rows where possible.
9. Remove old session-based columns in a later phase.

### 13.3 Recommended For This Project

Since this is still early:

```text
Use a clean migration if possible.
Do not spend days preserving throwaway test chat data.
```

But implement the code in a way that does not leave identity ambiguous again.

---

## 14. Implementation Batches

## Batch A — Auth/User Planning And Schema

### Goal

Introduce persistent users and sessions at DB/model level.

### Backend Files Likely Touched

```text
backend/migrations/init.sql
backend/migrations/003_user_identity.sql
backend/app/models/user.py
backend/app/models/user_session.py
backend/app/models/message.py
backend/app/models/reaction.py
backend/app/models/__init__.py
backend/app/models/database.py
```

### Tasks

* Refactor/add `User` model with `id`, `username`, `nickname`, `role`, timestamps.
* Add `UserSession` model.
* Add migration for `user_sessions`.
* Add `user_id` to messages/reactions if needed.
* Keep old columns temporarily if needed.

### Acceptance Criteria

* Tables create successfully from fresh DB.
* Migration applies successfully to existing DB.
* Models import without circular dependency issues.
* Tests verify columns and relationships.

### Risks

* Existing `users` table may already use `session_id` as primary key.
* Foreign keys from messages/reactions may need staged migration.

---

## Batch B — Auth Service And REST Endpoints

### Goal

Allow users to register once and return via persistent session.

### Backend Files Likely Touched

```text
backend/app/domains/auth/*
backend/app/domains/users/*
backend/app/api/v1/auth.py
backend/app/api/v1/users.py
backend/app/api/v1/router.py
backend/app/config.py
backend/tests/test_auth.py
```

### Tasks

* Add invite code config.
* Add token generation/hash utilities.
* Add `POST /api/v1/auth/register`.
* Add `GET /api/v1/auth/me`.
* Add `POST /api/v1/auth/logout`.
* Add `PATCH /api/v1/users/me` for nickname update.
* First registered user becomes owner.

### Acceptance Criteria

* New user can register with valid invite code.
* Duplicate username rejected clearly.
* Invalid invite code rejected.
* Returning user can call `/auth/me` with valid token.
* Logout revokes session.
* Nickname update works.

### Risks

* Token accidentally returned/logged too often.
* State contains secrets if invite code is generated by Terraform.

---

## Batch C — Frontend Auth Flow

### Goal

Remember users after first setup and avoid asking for nickname every time.

### Frontend Files Likely Touched

```text
frontend/src/auth/AuthProvider.jsx
frontend/src/auth/useAuth.js
frontend/src/api/client.js
frontend/src/api/auth.js
frontend/src/pages/WelcomePage.jsx
frontend/src/components/Auth/RegisterForm.jsx
frontend/src/App.jsx
```

### Tasks

* Add auth provider.
* On app boot, call `/auth/me`.
* If authenticated, render app.
* If not authenticated, render welcome/register screen.
* Store token if using localStorage.
* Use cookie credentials if using cookie auth.
* Add logout control.

### Acceptance Criteria

* First visit shows registration form.
* Successful registration enters app.
* Refreshing page keeps user logged in.
* Closing/reopening browser keeps user logged in.
* Logout clears session.

### Risks

* Local dev CORS/cookie setup may be fiddly.
* Token storage choice affects WebSocket implementation.

---

## Batch D — WebSocket Auth Refactor

### Goal

Stop using random WebSocket session IDs as user identity.

### Backend Files Likely Touched

```text
backend/app/api/v1/websocket.py
backend/app/domains/chat/connection_manager.py
backend/app/domains/chat/message_handler.py
backend/app/domains/chat/events.py
backend/app/services/chat_service.py
```

### Frontend Files Likely Touched

```text
frontend/src/hooks/useWebSocket.jsx
frontend/src/components/Chat/Chat.jsx
frontend/src/components/Chat/MessageInput.jsx
```

### Tasks

* Authenticate WebSocket before accepting chat actions.
* Map connections to `user_id`.
* Allow multiple tabs per user.
* Online users are unique by user, not connection.
* Remove old `set_nickname` flow.
* Messages use authenticated `user_id`.
* Reactions use authenticated `user_id`.

### Acceptance Criteria

* Unauthenticated WebSocket cannot send messages.
* Authenticated user can send messages.
* Multiple tabs for same user do not create duplicate online users.
* Closing one of two tabs does not mark user offline.
* Closing all tabs removes user from online list.
* No FK errors when sending messages.

### Risks

* Existing frontend may depend on `sessionId` for `isMe` logic.
* Reactions may need new `reacted_by_me` logic.

---

## Batch E — Messages/Reactions Identity Refactor

### Goal

Make all user-owned entities use `user_id`.

### Backend Files Likely Touched

```text
backend/app/domains/messages/repository.py
backend/app/domains/messages/service.py
backend/app/domains/reactions/repository.py
backend/app/domains/chat/message_handler.py
backend/app/api/v1/router.py
```

### Tasks

* Message creation writes `user_id`.
* Message reads include user username/nickname.
* Own-message logic uses `user_id`.
* Edit/delete checks use `user_id`.
* Reaction toggles use `user_id`.
* API responses include `is_me` or enough user info for frontend.

### Acceptance Criteria

* Messages persist against stable users.
* Reactions toggle per user, not per browser session.
* Refreshing page preserves own-message styling.
* Same user in two tabs sees consistent ownership/reaction state.

### Risks

* Old messages may not have `user_id`.
* API response shape changes may break frontend rendering.

---

## Batch F — Member Directory And Role Foundations

### Goal

Expose proper members and roles for the Social Hub.

### Backend Files Likely Touched

```text
backend/app/domains/users/repository.py
backend/app/domains/users/service.py
backend/app/api/v1/members.py
backend/app/domains/permissions.py
```

### Frontend Files Likely Touched

```text
frontend/src/pages/MembersPage.jsx
frontend/src/components/Members/*
frontend/src/utils/permissions.js
```

### Tasks

* Add members endpoint.
* Show username, nickname, role, online status.
* Add permission helper.
* Allow owner to change role if in scope.

### Acceptance Criteria

* Members page shows all registered users.
* Online users are marked clearly.
* Owner/admin/member roles display correctly.
* First registered user is owner.

### Risks

* Role changes can lock out owner if not guarded.

---

## 15. Testing Strategy

### 15.1 Backend Tests

Add tests for:

* username validation
* nickname validation
* invite code validation
* first user becomes owner
* later users become members
* duplicate username rejected
* session token generated and hashed
* raw token not stored
* `/auth/me` works with valid token
* `/auth/me` rejects invalid/revoked/expired token
* logout revokes session
* message creation requires authenticated user
* WebSocket rejects unauthenticated send
* multiple WebSocket connections for one user

### 15.2 Frontend Tests / Manual Tests

Manual browser tests are enough initially if frontend testing is light.

Test cases:

1. Fresh browser opens welcome screen.
2. Register as first user.
3. Refresh page — still logged in.
4. Open second tab — same user, no duplicate online entry.
5. Register second user in private browser.
6. Send messages from both users.
7. Check own-message styling remains correct after refresh.
8. Change nickname and confirm chat/member list updates.
9. Logout and confirm welcome screen appears.
10. Invalid invite code shows clear error.

---

## 16. Security Considerations

### 16.1 Must Have

* Do not store raw tokens in DB.
* Do not log raw tokens.
* Do not allow messages from unauthenticated users.
* Do not rely on frontend-only auth checks.
* Use HTTPS before real friend usage.
* Keep invite code secret.
* Rate-limit register/auth endpoints eventually.

### 16.2 Should Have Soon

* session expiry
* logout/revoke session
* admin can revoke member sessions
* upload/auth checks before photo feature
* clear role permission checks

### 16.3 Can Wait

* password login
* email verification
* magic links
* OAuth
* full custom permissions
* device management UI

---

## 17. Deployment Implications

Add new environment variables:

```env
INVITE_CODE=some-secret
SESSION_SECRET=long-random-secret
SESSION_TTL_DAYS=90
AUTH_COOKIE_NAME=friend_hub_session
```

If using cookie auth in production:

```env
AUTH_COOKIE_SECURE=true
AUTH_COOKIE_SAMESITE=lax
```

For local dev:

```env
AUTH_COOKIE_SECURE=false
```

Terraform/cloud-init should pass these through carefully.

Important: if Terraform renders these into cloud-init or `.env`, Terraform state may contain secrets.

---

## 18. Open Questions

* Should username be changeable later?
* Should nickname be unique or can two users have the same nickname?
* Should the app use localStorage token first or go straight to HTTP-only cookies?
* Should first user automatically become owner?
* Should invite code be global or per-user invite links?
* How long should sessions last?
* Should old test messages be preserved or can the DB be reset?
* Should roles live directly on users for now or in `group_members` from the start?

Recommended answers for v1:

* username not changeable
* nickname not unique
* first user becomes owner
* global invite code
* 90-day session lifetime
* reset dev DB if possible
* role directly on user until group model lands

---

## 19. Non-Goals

Do not implement these in this phase:

* password reset
* email verification
* OAuth
* full magic link provider integration
* multi-group/multi-server support
* complex custom permissions UI
* audit logs
* admin dashboard for all sessions/devices
* enterprise-grade auth
* public signup

---

## 20. Final Acceptance Criteria

This phase is complete when:

* Users register once with username, nickname, and invite code.
* Returning users are remembered automatically.
* Users no longer enter nickname every time.
* Username is stable and unique.
* Nickname is visible and editable.
* Messages are linked to stable `user_id`, not temporary WebSocket session IDs.
* Reactions/edit/delete ownership uses stable `user_id`.
* WebSocket refuses unauthenticated chat actions.
* Online users are based on users, not tabs.
* Multiple tabs for the same user work correctly.
* First user becomes owner.
* Members endpoint can return username, nickname, role, and online state.
* The previous foreign-key error cannot happen anymore.

---

## 21. Recommended Codex Prompt For Batch A

```text
Implement Batch A of Phase User Level Up.

Goal:
Introduce persistent user identity and session schema without changing frontend behaviour yet.

Scope:
- Add/update database schema for stable users with id, username, nickname, role, created_at, updated_at, last_seen_at, is_active.
- Add user_sessions table with id, user_id, token_hash, created_at, expires_at, last_used_at, user_agent, ip_address, revoked_at.
- Add user_id to messages and reactions as nullable columns if existing data needs compatibility.
- Add SQLAlchemy models for UserSession and updated User.
- Ensure Message and Reaction can reference user_id while preserving old fields temporarily if needed.
- Add an idempotent migration file.
- Add tests for model columns and relationships.

Constraints:
- Do not implement REST auth endpoints yet.
- Do not change WebSocket behaviour yet.
- Do not remove old session_id/user_session_id columns in this batch unless the project has no data worth preserving and tests confirm a clean reset is intended.
- Keep changes small and reviewable.

Acceptance criteria:
- Fresh DB initialises successfully.
- Existing DB migration applies successfully.
- SQLAlchemy metadata includes users, user_sessions, messages, and reactions relationships.
- Tests pass.
```
