Phase: Mobile Push Notifications

1. Add PWA basics
- Add manifest.json
- Add app name, icons, theme colour
- Register service worker
- Make app installable on mobile

2. Add notification permission flow
- Add a small “Enable notifications” prompt inside Settings or Home
- Do not request permission immediately on page load
- Store whether user declined/enabled notifications

3. Add Web Push subscription
- Frontend calls serviceWorkerRegistration.pushManager.subscribe()
- Use VAPID public key
- Send subscription object to backend
- Store subscription against user/member/device

4. Backend push service
- Add push_subscriptions table
- Store endpoint, keys, user/member id, created_at, last_success_at
- Use pywebpush or equivalent Python library
- Add helper: send_push_notification(user_id, title, body, url)

5. Trigger notifications
Start with only high-value alerts:
- someone mentions you — implemented for chat @mentions in `backend/app/domains/chat/message_handler.py`
- event reminder
- poll created — partially implemented for primary `POST /api/v1/polls` creation
- important pinned item
- maybe new chat message later, but avoid spam

@mention trigger notes:
- Chat message creation schedules best-effort push fanout after the WebSocket broadcast.
- Mention push targets are scoped to active users in the default Friend Hub group membership (`groups.slug = 'main'` via `group_members`), matched by `@username`, and exclude the sender.
- Push payload opens `/chat?message={message_id}`, which the frontend uses to load message context.
- Generic "new chat message" push fanout was deliberately removed in this slice; chat push is mention-only to avoid spam.
- Existing in-app notification behaviour is unchanged; this slice does not add mention `notifications` rows.

Remaining trigger work:
- event reminders
- pinned-item notifications
- poll-created notifications for non-primary creation paths, if desired

6. Service worker notification handler
- Listen for push event
- Show system notification
- Include icon, badge, title, body, and target URL
- On notification click, open/focus Friend Hub at the right page

7. Mobile UX
- Add “Install Friend Hub” prompt/instructions
- For iPhone, explain: open in Safari → Share → Add to Home Screen
- After installed, user opens the Home Screen app and enables notifications

Acceptance criteria:
- Android receives notifications when browser is backgrounded
- iPhone receives notifications when installed as a Home Screen web app
- Notifications open the correct Friend Hub page when tapped
- Backend removes dead/expired push subscriptions
- User can disable notifications

Manual QA notes for @mentions:
- Install Friend Hub as a mobile PWA, sign in as User B, and enable notifications in Settings.
- From User A, send a chat message containing `@user-b-username`.
- Confirm User B receives a system notification with a concise sender/message preview.
- Tap the notification and confirm it opens Friend Hub at `/chat?message={message_id}` with the relevant chat context.
- Confirm User A does not receive a push for mentioning themselves, and ordinary chat messages without @mentions do not create push notifications.

Poll-created trigger notes:
- Primary poll creation (`POST /api/v1/polls`) schedules `_bg_poll_created_push_notification` in `backend/app/api/v1/router.py`.
- Poll-created push targets are active users in the poll's group membership, excluding the creator and cleanup/system/test/bot users.
- The existing in-app broadcast notification still runs for `new_poll`, but its generic push fanout is disabled on this path to avoid duplicate mobile pushes.
- Push payload uses `notif_type: poll_created`, `target_type: poll`, `target_id: poll.id`, and includes `hub_item_id` when the poll hub item mirror is available.
- AI draft accepted polls are not covered in this slice; `DraftActionService` intentionally creates canonical rows without notifications, and adding push there should be handled separately to avoid hidden side effects.
- Chat agenda motions create poll rows through `POST /api/v1/chat-events`; those retain their existing `new_chat_event` broadcast path and are not covered by the poll-created push payload in this slice.

Manual QA notes for poll-created push:
- Install Friend Hub as a mobile PWA, sign in as User B, and enable notifications.
- From User A, create a normal poll from the Polls page.
- Confirm User B receives a system notification titled "New poll in Friend Hub" with the creator and poll question preview.
- Tap the notification and confirm it opens Friend Hub at `/polls`.
- Confirm User A does not receive a push for their own poll, and inactive/non-member users do not receive one.
