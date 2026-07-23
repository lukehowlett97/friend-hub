# Phase 1 — Level Up: Group Chat Feel

Target features, ordered by dependency. Each section lists the exact files touched,
the data contracts added, and the acceptance criteria.

---

## 0. Prerequisite: DB schema additions

The current `init.sql` and `message.py` model are missing columns needed by several
features below. All changes are non-breaking (nullable / with defaults).

**`messages` table additions:**
```sql
reply_to_id  INTEGER  REFERENCES messages(id) ON DELETE SET NULL  -- reply-to
-- edited_at and is_deleted already exist in init.sql but are absent from the ORM model
```

**`reactions` table** — already in `init.sql`, but `reaction.py` is empty.

**Files:**
- `backend/migrations/init.sql` — add `reply_to_id` column + index
- `backend/migrations/002_add_reply_to.sql` — migration for existing databases
- `backend/app/models/message.py` — add `edited_at`, `is_deleted`, `reply_to_id` columns to ORM
- `backend/app/models/reaction.py` — implement `Reaction` SQLAlchemy model
- `backend/app/models/__init__.py` — export `Reaction`

---

## 1. Online user list

**What:** A sidebar showing who is currently connected and has set their nickname.

**Backend:**

`ConnectionManager` gains a second dict alongside `active_connections`:
```python
session_nicknames: Dict[str, str]  # session_id → nickname
```
New methods: `set_nickname(session_id, nickname)`, `get_nickname(session_id)`,
`get_online_users() -> list[{session_id, nickname}]`.
`disconnect()` removes from both dicts.

New event types in `events.py`:
```
ONLINE_USERS = "online_users"       # outgoing: full user list
```
New outgoing schema:
```python
OutgoingOnlineUsers(users=[{session_id, nickname}])
```

Flow:
1. On WS connect → send `online_users` with current list to the new client.
2. On `set_nickname` success → `connection_manager.set_nickname()` + broadcast `online_users` to all.
3. On disconnect → `connection_manager.disconnect()` (cleans nickname) + broadcast `online_users` to remaining.

`OutgoingUserDisconnected` gains `nickname: Optional[str]` so the disconnect banner uses the real name.

**Frontend:**

- `frontend/src/utils/colorUtils.js` — `getColorForNickname(nickname)` deterministic hash → one of 8 colours. Used everywhere an avatar or name colour is needed.
- `frontend/src/components/Chat/UserAvatar.jsx` — coloured circle + first initial. Props: `nickname`, `size`.
- `frontend/src/components/Chat/OnlineUsers.jsx` — renders `users` prop as a list of `UserAvatar` + name. Shows count in header.
- `frontend/src/components/Chat/OnlineUsers.css`
- `frontend/src/components/Chat/Chat.jsx` — add `onlineUsers` state, layout becomes two-column (chat | sidebar).
- `frontend/src/hooks/useWebSocket.jsx` — handle `online_users` event → update `onlineUsers` state; expose it.

**Acceptance:** Opening two browser tabs shows both nicknames in the sidebar. Closing one tab removes it within 1–2 seconds.

---

## 2. Join / leave messages using nicknames

**What:** System messages say "Luke joined the chat" / "Luke left the chat" instead of a UUID.

**Backend:**

`_handle_set_nickname` in `message_handler.py` already broadcasts `OutgoingUserJoined`
with `nickname` — no change needed there.

`_handle_disconnect` in `websocket.py` currently broadcasts `OutgoingUserDisconnected`
with only `session_id`. Change to look up nickname from `connection_manager.get_nickname(session_id)`
**before** calling `manager.disconnect()`, then include it in the event.

**Frontend:**

`useWebSocket.jsx` handler for `user_disconnected` currently builds the system message
from `data.session_id`. Change to use `data.nickname ?? data.session_id`.

`user_joined` handler already has `data.nickname` — just ensure the system message
reads `"${data.nickname} joined the chat"`.

**Acceptance:** System messages in the chat use real names, not UUIDs.

---

## 3. "Luke is typing…"

**What:** When a user is typing, all other users see a live indicator.

**Backend (relay-only, no DB):**

New event types:
```
TYPING      = "typing"       # incoming from client
STOP_TYPING = "stop_typing"  # incoming from client
TYPING_INDICATOR = "typing_indicator"  # outgoing to others
```
New outgoing schema:
```python
OutgoingTypingIndicator(session_id, nickname, is_typing: bool)
```

New handlers in `message_handler.py`:
- `_handle_typing` — look up nickname from `connection_manager`, broadcast `typing_indicator` excluding sender.
- `_handle_stop_typing` — same, `is_typing=False`.

**Frontend:**

`MessageInput.jsx` changes:
- On each keystroke (if `!isTyping`) → send `{type: "typing"}`, set `isTyping=true`.
- Debounce: 2 s after last keystroke → send `{type: "stop_typing"}`, set `isTyping=false`.
- On message send → send `stop_typing` immediately.

`useWebSocket.jsx`:
- `typingUsers: Map<session_id, nickname>` state.
- `typing_indicator` with `is_typing=true` → add to map; `is_typing=false` → remove.
- Also send `stop_typing` on WS disconnect.
- Expose `typingUsers`, `sendTyping()`, `sendStopTyping()`.

`TypingIndicator.jsx` — animated "Luke is typing…" with three-dot pulse. Receives `typingUsers` (Map).

`Chat.jsx` — render `<TypingIndicator>` between message list and input.

**Acceptance:** Opening two tabs, typing in tab A shows the indicator in tab B within 200 ms. Stopping typing or sending removes it within 2 s.

---

## 4. Message timestamps (already partially done)

**What:** Times shown as "just now", "3 minutes ago", "Yesterday 3:45 PM", "Dec 25, 3:45 PM". Full datetime shown on hover via `title` attribute.

**Status:** `MessageList.jsx` already implements this with `date-fns`. The gap is that
new WS messages sometimes arrive with a raw datetime string that `parseISO` can't handle
if the backend sends a non-ISO format.

**Backend:**

Audit all outgoing events that carry `timestamp` / `created_at` / `edited_at` — ensure
they're serialised as ISO 8601 strings. The custom `dict()` override on `OutgoingChatMessage`
already does this; extend it to cover `edited_at` when added.

**Frontend:**

Move `formatTime()` out of `MessageList.jsx` into `frontend/src/utils/helpers.js` so
`Message.jsx` and any other component can use it without re-implementing.

**Acceptance:** All message times display in human-readable relative format. Hovering a timestamp shows the exact datetime.

---

## 5. Profile colour / avatar per nickname

**What:** Each user gets a consistent coloured avatar (circle + initial) that appears to the left of their messages and in the online users list.

**Implementation:** Pure frontend, no DB changes.

`colorUtils.js`:
```js
const PALETTE = ['#e74c3c','#9b59b6','#3498db','#1abc9c','#f39c12','#e67e22','#2ecc71','#e91e63'];

export function getColorForNickname(nickname) {
  let hash = 0;
  for (let i = 0; i < nickname.length; i++) {
    hash = nickname.charCodeAt(i) + ((hash << 5) - hash);
  }
  return PALETTE[Math.abs(hash) % PALETTE.length];
}
```

`UserAvatar.jsx`:
```jsx
// Renders a coloured circle with the first character of nickname
export function UserAvatar({ nickname, size = 32 }) { ... }
```

`Message.jsx` — show `UserAvatar` to the left of messages from others. Own messages
(right-aligned) do not show an avatar. The sender name colour matches the avatar colour
via `style={{ color: getColorForNickname(nickname) }}`.

**Acceptance:** The same nickname always gets the same colour across tabs and page reloads. Colour is consistent between the avatar in the message, the online user sidebar, and the typing indicator.

---

## 6. Message reactions

**What:** Hover a message → a row of emoji buttons appears. Click to toggle your reaction.
Reactions shown as `👍 2` below the message.

**Backend:**

`reaction.py` ORM model:
```python
class Reaction(Base):
    __tablename__ = "reactions"
    id, message_id (FK), user_session_id (FK), emoji, created_at
```

`backend/app/domains/reactions/repository.py`:
- `toggle_reaction(message_id, session_id, emoji)` — if user already reacted with same emoji → delete; if different emoji → update; if none → insert. Returns updated reaction list for message.
- `get_reactions_for_messages(message_ids)` — batch fetch, returns `Dict[int, list]`.

`get_reactions_for_message` return format:
```python
[{"emoji": "👍", "count": 2, "session_ids": ["uuid1", "uuid2"]}]
```

New event types:
```
TOGGLE_REACTION  = "toggle_reaction"   # incoming
REACTION_UPDATED = "reaction_updated"  # outgoing
```

`OutgoingReactionUpdated(message_id: int, reactions: list)`:

New handler `_handle_toggle_reaction` in `message_handler.py` — calls service, broadcasts `reaction_updated` to all.

REST `GET /api/v1/messages` — include `reactions` array in each message dict.

**Frontend:**

`ReactionPicker.js` — small popover with 8 common emoji: `["👍","❤️","😂","😮","😢","🔥","🎉","👀"]`.
Appears on hover over a message. Calls `onToggleReaction(messageId, emoji)`.

`ReactionDisplay.js` — renders reaction pills below message content. Highlights the pill
if `sessionIds` includes the current user's `sessionId`. Clicking a pill toggles it.

`Message.jsx` — integrates `ReactionDisplay` and shows `ReactionPicker` on hover.

`useWebSocket.jsx`:
- `toggleReaction(messageId, emoji)` — sends `{type: "toggle_reaction", message_id, emoji}`.
- `reaction_updated` handler — find message by `data.message_id`, update its `reactions` array.

`Chat.jsx` — pass `sessionId` and `onToggleReaction` down through `MessageList` → `Message`.

**Acceptance:** Reacting in one tab is reflected in another tab within 500 ms. The reacted emoji is visually highlighted for the user who clicked it.

---

## 7. Reply-to / quote replies

**What:** Click "Reply" on any message → the input shows a quoted preview of the original.
Sent message includes the quote. Both tabs show the quote inline.

**Backend:**

`messages` table: `reply_to_id INTEGER REFERENCES messages(id) ON DELETE SET NULL`.

`Message` ORM model: `reply_to_id = Column(Integer, ForeignKey("messages.id"), nullable=True)`.

`MessageRepository.create_message` gains optional `reply_to_id` param.

`get_recent_messages_with_users` uses SQLAlchemy `aliased()` to LEFT JOIN the
replied-to message and its author:
```python
ReplyMsg = aliased(Message)
ReplyUser = aliased(User)
select(Message, User, ReplyMsg, ReplyUser)
  .join(User, ...)
  .outerjoin(ReplyMsg, Message.reply_to_id == ReplyMsg.id)
  .outerjoin(ReplyUser, ReplyMsg.user_session_id == ReplyUser.session_id)
```

Outgoing message format gains:
```json
"reply_to": {"id": 120, "content": "How are you?", "nickname": "Alice"}
```
(Truncate content to 100 chars for the preview.)

Incoming message format gains: `reply_to_id: int | null`.

`_handle_chat_message` in `message_handler.py` — read `reply_to_id` from `data`, pass to
service, include `reply_to` in broadcast.

**Frontend:**

`MessageInput.jsx` gains `replyTo` prop `{id, content, nickname}` and `onClearReply`.
When set, renders a dismissible quote banner above the input. `handleSubmit` includes
`reply_to_id` in the sent payload. On send, calls `onClearReply`.

`Message.jsx` — if `message.reply_to` is set, renders a muted quote block above the
message content (left border + original nickname + truncated text).

`Chat.jsx` — `replyTo` state, passed to `MessageInput`. `Message` receives
`onReply(message)` callback that sets the state.

**Acceptance:** Clicking Reply on a message shows a quote in the input. The sent message shows the quote in both tabs. Deleting the original message replaces the quote content with "[deleted]" (handled by `ON DELETE SET NULL` + frontend fallback).

---

## 8. Delete own message

**What:** A trash icon appears on hover for the user's own messages. Clicking it soft-deletes the message — all clients see "[message deleted]".

**Backend:**

Soft delete: set `is_deleted = true`, replace `content` with `"[message deleted]"`.
This keeps the message record for reply-to chains (the quote just shows "[deleted]").

`MessageRepository.soft_delete_message(message_id, requesting_session_id)`:
- Fetch message, verify ownership (compare `user_session_id` to session_id).
- If not owner → return `False`.
- Set `is_deleted = True`, `content = "[message deleted]"`, commit.

New event types:
```
DELETE_MESSAGE  = "delete_message"   # incoming
MESSAGE_DELETED = "message_deleted"  # outgoing
```

`OutgoingMessageDeleted(message_id: int, session_id: str)`

`_handle_delete_message` in `message_handler.py` — calls service, broadcasts `message_deleted`.

REST `GET /api/v1/messages` — include deleted messages with `is_deleted: true` so
reply-to chains are not broken. Frontend handles display.

**Frontend:**

`Message.jsx` — when `message.isMe`, show a trash icon on hover. `onClick` calls `onDeleteMessage(message.id)`.

`useWebSocket.jsx`:
- `deleteMessage(messageId)` — sends `{type: "delete_message", message_id: messageId}`.
- `message_deleted` handler — find message by id, replace content with "[message deleted]", set `isDeleted: true`.

`Chat.jsx` — pass `onDeleteMessage` to `MessageList` → `Message`.

**Acceptance:** Clicking delete shows "[message deleted]" in both tabs immediately. Cannot delete another user's message (backend returns error, frontend ignores delete icon for others).

---

## 9. Edit own message

**What:** A pencil icon on own messages. Clicking it puts the input into edit mode (pre-filled with current content). Saving broadcasts the update; an "(edited)" tag appears.

**Backend:**

`MessageRepository.edit_message(message_id, requesting_session_id, new_content)`:
- Fetch, verify ownership.
- Update `content`, set `edited_at = datetime.utcnow()`, commit, return updated message.

New event types:
```
EDIT_MESSAGE   = "edit_message"    # incoming
MESSAGE_EDITED = "message_edited"  # outgoing
```

`OutgoingMessageEdited(message_id: int, content: str, edited_at: str)`

`_handle_edit_message` in `message_handler.py` — validates content (not empty, ≤ 1000 chars),
calls service, broadcasts `message_edited`.

**Frontend:**

`MessageInput.jsx` gains `editingMessage` prop `{id, content}` and `onCancelEdit`.
When set, input pre-fills with `editingMessage.content`, submit button says "Save",
pressing Escape calls `onCancelEdit`.
`handleSubmit` in edit mode sends `{type: "edit_message", message_id, content}` instead
of `{type: "message", content}`.

`Message.jsx` — pencil icon on hover for own messages. `onClick` calls `onEditMessage({id, content})`.

`useWebSocket.jsx`:
- `editMessage(messageId, content)` — sends `{type: "edit_message", message_id: messageId, content}`.
- `message_edited` handler — find message by id, update `content`, `edited_at`, set `isEdited: true`.

`Chat.jsx` — `editingMessage` state, passed to `MessageInput`. `Message` receives `onEditMessage` callback.

**Acceptance:** Editing a message updates it in both tabs, shows "(edited)" tag. Cannot edit another user's message. Pressing Escape cancels edit mode without sending.

---

## File change summary

### Backend

| File | Change type |
|------|-------------|
| `backend/migrations/init.sql` | Add `reply_to_id` column + index |
| `backend/migrations/002_add_reply_to.sql` | New — migration for existing DBs |
| `backend/app/models/message.py` | Add `edited_at`, `is_deleted`, `reply_to_id` columns |
| `backend/app/models/reaction.py` | Implement `Reaction` model |
| `backend/app/models/__init__.py` | Export `Reaction` |
| `backend/app/domains/chat/connection_manager.py` | Add `session_nicknames` dict + methods |
| `backend/app/domains/chat/events.py` | Add 10 new event types + 7 new schemas |
| `backend/app/domains/reactions/__init__.py` | New |
| `backend/app/domains/reactions/repository.py` | New — `toggle_reaction`, batch fetch |
| `backend/app/domains/messages/repository.py` | Add `soft_delete`, `edit_message`, `reply_to` join |
| `backend/app/domains/messages/service.py` | Add `delete_message`, `edit_message`, `toggle_reaction` |
| `backend/app/services/chat_service.py` | Delegate new service methods |
| `backend/app/domains/chat/message_handler.py` | Add 5 new handlers |
| `backend/app/api/v1/websocket.py` | Send online users on connect/disconnect |
| `backend/app/api/v1/router.py` | Include reactions + reply_to in messages response |

### Frontend

| File | Change type |
|------|-------------|
| `frontend/src/utils/colorUtils.js` | New — deterministic colour from nickname |
| `frontend/src/utils/helpers.js` | Move `formatTime` here |
| `frontend/src/components/Chat/UserAvatar.jsx` | New |
| `frontend/src/components/Chat/OnlineUsers.jsx` | New |
| `frontend/src/components/Chat/OnlineUsers.css` | New |
| `frontend/src/components/Chat/TypingIndicator.jsx` | New |
| `frontend/src/components/Reactions/ReactionPicker.js` | Implement |
| `frontend/src/components/Reactions/ReactionDisplay.js` | Implement |
| `frontend/src/components/Chat/Message.jsx` | Implement (currently empty) |
| `frontend/src/components/Chat/MessageList.jsx` | Pass new props through |
| `frontend/src/components/Chat/MessageInput.jsx` | Add typing, reply mode, edit mode |
| `frontend/src/hooks/useWebSocket.jsx` | Handle 8 new event types, expose 4 new actions |
| `frontend/src/components/Chat/Chat.jsx` | Two-column layout, plumb all new state |
| `frontend/src/components/Chat/Chat.css` | Add styles for all new components |

---

## Implementation order

Dependencies flow top-to-bottom:

```
0. DB schema additions
   ↓
1. Online user list          (connection_manager + events + frontend hook/sidebar)
2. Join/leave nicknames      (depends on #1 — connection_manager.get_nickname)
3. Typing indicator          (depends on #1 — connection_manager.get_nickname)
4. Timestamps                (standalone, can go any time)
5. Profile colour/avatar     (standalone frontend, needed by #1 and #6)
   ↓
6. Reactions                 (depends on DB schema + Reaction model)
7. Reply-to                  (depends on DB schema + updated repository)
   ↓
8. Delete message            (depends on updated repository)
9. Edit message              (depends on updated repository)
```

Suggested batches:
- **Batch A:** `0 + 5` — schema + colour/avatar utility (no deps, unblocks everything)
- **Batch B:** `1 + 2 + 3 + 4` — all the live-feel features (all use same connection_manager change)
- **Batch C:** `6 + 7` — reactions and replies (both touch repository layer)
- **Batch D:** `8 + 9` — delete and edit (same pattern, do together)
