# Phase — PWA Mobile Init

## 1. Summary

This phase turns the existing Friend-Hub React/Vite frontend into a mobile-friendly Progressive Web App.

The goal is not to create a new frontend and not to build a native app yet. The goal is to keep the current React/Vite app and make it feel much closer to a real phone app:

* usable on mobile screens
* installable to the phone home screen
* persistent full-height app layout
* mobile navigation
* touch-friendly chat experience
* groundwork for push notifications later

This phase should make it easy for friends to use the app casually from their phones without needing to remember a URL or repeatedly log in.

---

## 2. Product Goal

Friend-Hub should feel like a private group app, not just a website.

A user should be able to:

1. Open a link once.
2. Register or log in.
3. Add the app to their phone home screen.
4. Reopen it later from an icon.
5. Land straight back in the app.
6. Use chat/events/photos/members comfortably on a phone.

This phase is successful when the current web app feels credible as a daily-use mobile app, even before native Android/iOS apps exist.

---

## 3. Non-Goals

Do not implement these in this phase:

* native iOS app
* native Android app
* React Native rewrite
* Capacitor wrapper
* App Store / Play Store deployment
* complex offline-first behaviour
* full push notification system
* background sync
* heavy media caching
* full design system rewrite

This phase is about the mobile web/PWA foundation.

---

## 4. Current Assumption

The existing frontend is a React/Vite app.

That is a good foundation for a PWA. A PWA is not a separate frontend. It is the existing web app plus:

* responsive UX
* web app manifest
* app icons
* service worker
* HTTPS hosting
* install-to-home-screen behaviour
* optional push notification support later

The correct approach is:

```text
keep current frontend -> improve mobile UX -> add PWA features
```

Not:

```text
create new frontend -> rebuild existing app
```

---

## 5. Desired Mobile UX

### 5.1 Overall Feel

The app should feel like:

```text
A private social app for a friend group.
```

Not:

```text
A desktop web dashboard squeezed onto a phone.
```

### 5.2 Mobile Layout Principles

* Mobile-first layout.
* One main section visible at a time.
* Bottom navigation on phones.
* Sidebar/top navigation can remain for desktop/tablet.
* Large tap targets.
* Sticky chat input.
* Full-height viewport handling.
* Safe-area support for iPhone notches/home indicator.
* Minimal horizontal scrolling.
* Avoid tiny hover-only controls on mobile.

---

## 6. Recommended App Navigation

### 6.1 Desktop

Desktop can use:

```text
Left sidebar + main content
```

Example:

```text
Friend-Hub
├── Home
├── Chat
├── Calendar
├── Photos
├── Members
└── Settings
```

### 6.2 Mobile

Mobile should use bottom tabs:

```text
Home | Chat | Events | Photos | Members
```

Settings can live in:

* top-right cog
* profile menu
* overflow menu

Suggested mobile nav:

```text
[Main content]

--------------------------------
  Home   Chat   Events   Photos   Members
--------------------------------
```

### 6.3 Route Mapping

Keep route structure consistent:

```text
/home
/chat
/calendar
/photos
/members
/settings
```

Mobile tab labels can be shorter:

```text
Calendar -> Events
```

---

## 7. Mobile Chat UX

The chat is the most important mobile experience.

### 7.1 Requirements

The chat page should have:

* full-height layout
* scrollable message list
* sticky message input at bottom
* keyboard-safe behaviour
* clear own/other message styling
* visible timestamps where appropriate
* touch-friendly send button
* no reliance on hover for core actions

### 7.2 iOS/Android Keyboard Behaviour

Mobile browsers can behave awkwardly when the keyboard opens.

Plan for:

* `height: 100dvh` rather than only `100vh`
* sticky input container
* enough bottom padding for safe area
* avoid body-level double scrolling
* use a dedicated scroll container for messages

Useful CSS concepts:

```css
.app-shell {
  min-height: 100dvh;
}

.mobile-bottom-nav {
  padding-bottom: env(safe-area-inset-bottom);
}

.chat-input-bar {
  padding-bottom: env(safe-area-inset-bottom);
}
```

### 7.3 Message Actions On Mobile

Desktop can use hover actions.

Mobile should use:

* tap message to reveal actions
* long press later if desired
* visible reaction button
* simple overflow menu

Do not rely on hover-only controls for:

* reply
* edit
* delete
* react

---

## 8. PWA Requirements

### 8.1 Web App Manifest

Add a manifest that defines:

* app name
* short name
* description
* theme colour
* background colour
* display mode
* start URL
* icons

Suggested manifest values:

```json
{
  "name": "Friend-Hub",
  "short_name": "Friend-Hub",
  "description": "A private social hub for friend groups.",
  "start_url": "/home",
  "scope": "/",
  "display": "standalone",
  "theme_color": "#111827",
  "background_color": "#111827",
  "icons": []
}
```

Icons should include at least:

```text
192x192 PNG
512x512 PNG
maskable 512x512 PNG
Apple touch icon
```

### 8.2 Service Worker

Use `vite-plugin-pwa` unless the project already has a preferred setup.

Service worker should initially do simple app-shell caching:

* cache static JS/CSS/assets
* cache app shell
* do not aggressively cache API responses
* do not cache chat messages in v1
* avoid complex offline data behaviour

Recommended strategy:

```text
Static assets: cache-first/revisioned by Vite
Navigation fallback: serve index.html
API/WebSocket: network only
```

### 8.3 HTTPS Requirement

PWA install and service worker behaviour require secure context.

Local dev is okay on:

```text
localhost
```

Production should be:

```text
https://your-domain
```

The existing Caddy deployment is suitable once a real domain points to the VPS.

### 8.4 Install Behaviour

Android/Chrome can show install prompt more naturally.

iOS requires manual installation:

```text
Safari -> Share -> Add to Home Screen
```

The app should include a small install guidance component, especially for iPhone users.

---

## 9. Push Notification Groundwork

Do not implement full push notifications in this phase unless the base PWA is already stable.

However, design with notifications in mind.

### 9.1 Future Notification Types

Potential notifications:

* new message
* mention
* event reminder
* event RSVP update
* new photo uploaded
* reaction to your message

### 9.2 Future Backend Needs

Eventually the backend will need:

```text
push_subscriptions
- id
- user_id
- endpoint
- p256dh
- auth
- user_agent
- created_at
- revoked_at
```

### 9.3 Future Frontend Needs

Frontend will need:

* ask permission at the right time
* register push subscription
* send subscription to backend
* allow user to disable notifications

### 9.4 Recommendation

For this phase:

* Add PWA foundations only.
* Do not request notification permission on first load.
* Add a placeholder/settings idea for notifications later.

---

## 10. Authentication Interaction

PWA usefulness depends heavily on persistent login.

The user experience should be:

```text
Open app from home screen -> already logged in -> app loads
```

This phase should align with the User Level Up phase:

* no repeated nickname entry
* persistent identity
* current user loaded on app boot
* WebSocket connects only after auth state is known

If persistent login is not implemented yet, this phase should not hack around it. Instead, note that the PWA experience will feel incomplete until user/session persistence exists.

---

## 11. Frontend File Plan

Likely files to create:

```text
frontend/public/manifest.webmanifest
frontend/public/icons/icon-192.png
frontend/public/icons/icon-512.png
frontend/public/icons/maskable-icon-512.png
frontend/public/apple-touch-icon.png
frontend/src/components/PWA/InstallPrompt.jsx
frontend/src/components/PWA/InstallInstructions.jsx
frontend/src/components/Layout/AppShell.jsx
frontend/src/components/Layout/BottomNav.jsx
frontend/src/components/Layout/DesktopNav.jsx
frontend/src/components/Layout/AppHeader.jsx
frontend/src/styles/mobile.css
```

Likely files to modify:

```text
frontend/package.json
frontend/vite.config.js
frontend/index.html
frontend/src/App.jsx
frontend/src/components/Chat/Chat.jsx
frontend/src/components/Chat/MessageList.jsx
frontend/src/components/Chat/MessageInput.jsx
frontend/src/components/Chat/Message.jsx
frontend/src/components/Chat/Chat.css
```

Exact file names may differ depending on the current project structure.

---

## 11b. Batch A Audit Findings (completed 2026-05-01)

### Existing structure

| Item | Status |
|------|--------|
| Framework | React 18 + Vite 4 |
| Routing | Custom `history.pushState`, 6 routes: `/home /chat /calendar /photos /members /settings` |
| AppShell | Exists — `src/components/AppShell/AppShell.jsx` |
| Pages | Home, Calendar, Photos, Members, Settings exist; Chat is a component |
| Mobile breakpoint | 860 px — sidebar collapses to horizontal scroll bar **at the top** |
| PWA manifest | **None** |
| Service worker | **None** |
| App icons | **None** (only `favicon.ico`) |
| `vite-plugin-pwa` | **Not installed** |
| `index.html` manifest link | **Missing** |
| `theme-color` meta | **Missing** |
| `viewport-fit=cover` | **Missing** |
| `apple-mobile-web-app-capable` | **Missing** |

### Mobile layout issues

1. **`100vh` everywhere** — `AppShell.css` and `Chat.css` use `100vh`/`calc(100vh - Xpx)`. On iOS Safari the URL bar eats into `100vh`, pushing the chat input offscreen when the keyboard opens. Fix: `100dvh` with `100vh` fallback.
2. **No bottom navigation** — on ≤860 px the nav becomes a horizontal scroll bar at the top. The plan calls for a bottom tab bar on phone screens. → Batch B.
3. **Fragile chat height on mobile** — `.page-chat` uses `calc(100vh - 160px)` (hardcoded nav offset). Breaks if nav height changes; doesn't use `dvh`. → Batch C.
4. **Chat wrapped in `app-main` padding** — chat sits inside `app-main` with `padding: 1rem` on mobile, wasting vertical space and making height calculations worse. → Batch C.
5. **Hover-only message actions** — reply, edit, delete, react are CSS-hover-only; invisible on touch. → Batch C.
6. **Online users sidebar at mid-widths** — hidden only at ≤600 px; visible (and space-consuming) at 600–860 px. → Batch C.

### Batch A deliverables applied

- `index.html` — added `viewport-fit=cover`, `theme-color`, Apple PWA meta tags
- `App.css` — `min-height: 100dvh` with `100vh` fallback
- `AppShell.css` — `min-height: 100dvh` with `100vh` fallback on `.app-shell` and `.app-main`

---

## 12. Implementation Batches

## Batch A — Mobile Audit And Layout Baseline

### Goal

Understand the existing frontend layout and identify what needs to change for mobile.

### Tasks

* Inspect current React component tree.
* Identify current routing setup.
* Identify whether app already has manifest/service worker.
* Check current chat layout on mobile viewport.
* Document layout problems.
* Add a small mobile CSS baseline if missing.

### Acceptance Criteria

* Clear list of existing frontend structure.
* Clear list of mobile layout issues.
* No major functionality changes yet.

---

## Batch B — App Shell And Responsive Navigation

### Goal

Create a mobile-friendly app shell around the existing app sections.

### Tasks

* Add or refine `AppShell`.
* Add desktop navigation.
* Add mobile bottom navigation.
* Ensure routes work for:

  * `/home`
  * `/chat`
  * `/calendar`
  * `/photos`
  * `/members`
  * `/settings`
* Ensure chat remains accessible and working.
* Ensure active nav state is clear.

### Acceptance Criteria

* Desktop layout still works.
* Mobile layout shows bottom nav.
* User can switch sections easily on phone.
* No horizontal scrolling.
* Chat still works under `/chat`.

### Batch B Implementation Notes

Implemented in the existing React/Vite app shell:

* Desktop keeps the left sidebar navigation.
* Mobile hides the sidebar and shows a fixed bottom navigation.
* Bottom navigation covers `/home`, `/chat`, `/calendar`, `/photos`, `/members`, and `/settings`.
* Mobile label for `/calendar` is shortened to `Events`.
* Active route state uses visual styling and `aria-current="page"`.
* App shell now uses `100dvh` where supported and reserves bottom safe-area space.
* Global and shell CSS now prevent horizontal overflow.

Remaining work for later batches:

* Batch C should polish chat keyboard/input behaviour on mobile.
* Batch D should add manifest and icons.
* Batch E should add service worker/app-shell caching.

---

## Batch C — Mobile Chat Polish

### Goal

Make the chat page usable as a daily mobile chat.

### Tasks

* Use full-height layout with `100dvh`.
* Make message list the scroll container.
* Keep input sticky at the bottom.
* Add safe-area padding.
* Make send button touch-friendly.
* Ensure keyboard opening does not destroy layout.
* Replace hover-only actions with tap-accessible actions where needed.
* Ensure messages auto-scroll sensibly.

### Acceptance Criteria

* Chat is comfortable on a phone viewport.
* Message input remains accessible.
* Keyboard behaviour is acceptable on iOS/Android.
* Actions are usable without hover.

---

## Batch D — PWA Manifest And Icons

### Goal

Make the app installable as a basic PWA.

### Tasks

* Add manifest file.
* Add app icons.
* Add apple touch icon.
* Update `index.html` with manifest/theme tags.
* Set app name/short name/theme colour.
* Confirm Lighthouse recognises installability basics.

### Acceptance Criteria

* Browser detects the app manifest.
* App has icon/name metadata.
* Android Chrome can offer install/add-to-home-screen behaviour when served over HTTPS.
* iOS can add the app to home screen with correct icon/name.

---

## Batch E — Service Worker/App Shell Caching

### Goal

Add simple PWA service worker support without breaking live chat.

### Tasks

* Install/configure `vite-plugin-pwa`.
* Cache static build assets.
* Add navigation fallback to `index.html`.
* Ensure API requests are network-only.
* Ensure WebSocket is unaffected.
* Add update behaviour if a new app version is deployed.

### Acceptance Criteria

* Production build registers service worker.
* Reloading app works.
* Navigation to nested routes works.
* Chat messages/API are not stale due to caching.
* WebSocket still connects.

---

## Batch F — Install Guidance UX

### Goal

Help friends install the app easily.

### Tasks

* Add install prompt component for supported browsers.
* Add iOS manual install instructions.
* Only show install guidance when useful.
* Allow dismissing install guidance.
* Do not annoy users every session.

### Acceptance Criteria

* Android users see helpful install option when available.
* iPhone users see clear instructions.
* Users can dismiss the prompt.
* Prompt does not block core app usage.

---

## Batch G — Final Mobile QA

### Goal

Verify the app is usable by real friends on real devices.

### Tasks

* Test on desktop Chrome/Firefox.
* Test on Android Chrome.
* Test on iPhone Safari.
* Test home screen install.
* Test reload from home screen.
* Test WebSocket reconnect.
* Test chat while keyboard is open.
* Test route navigation.

### Acceptance Criteria

* App can be installed or added to home screen.
* App opens to the expected route.
* Auth/session persists if User Level Up is complete.
* Chat works reliably from mobile.
* Layout feels acceptable for daily usage.

---

## 13. Mobile CSS Checklist

Use this checklist during implementation:

* [ ] root app uses `min-height: 100dvh`
* [ ] no unwanted body scroll behind app shell
* [ ] message list scrolls independently
* [ ] chat input is always reachable
* [ ] bottom nav respects `safe-area-inset-bottom`
* [ ] tap targets are at least roughly 44px high/wide
* [ ] no core control depends only on hover
* [ ] text is readable on small screens
* [ ] long messages wrap correctly
* [ ] image/media previews cannot overflow horizontally
* [ ] app works in standalone display mode

---

## 14. PWA Checklist

* [ ] manifest exists
* [ ] manifest linked from `index.html`
* [ ] app has `name` and `short_name`
* [ ] app has `start_url`
* [ ] app has `scope`
* [ ] app uses `display: standalone`
* [ ] theme/background colours set
* [ ] 192px icon exists
* [ ] 512px icon exists
* [ ] maskable icon exists
* [ ] Apple touch icon exists
* [ ] service worker registered in production build
* [ ] API requests are not wrongly cached
* [ ] WebSocket is unaffected
* [ ] app served over HTTPS in production

---

## 15. Testing Strategy

### 15.1 Local Browser Testing

Use dev tools mobile emulation:

* iPhone SE size
* iPhone standard size
* Pixel/Android size
* tablet size

Check:

* layout
* scrolling
* nav
* chat input
* keyboard simulation where possible

### 15.2 Real Device Testing

Real device testing is required because mobile browser behaviour differs from desktop emulation.

Test with:

* iPhone Safari
* Android Chrome
* desktop browser

### 15.3 Deployment Testing

PWA features need production-like hosting.

Test after deploying over HTTPS:

* manifest detected
* service worker registered
* home screen install
* standalone mode
* WebSocket connection under HTTPS/WSS

---

## 16. Risks And Trade-Offs

### 16.1 PWA Limitations

PWAs are not identical to native apps.

Limitations may include:

* less obvious install flow on iOS
* notification limitations compared with native apps
* browser-specific quirks
* less integration with OS sharing/contact features

### 16.2 Service Worker Risk

Bad caching can make the app feel broken.

Avoid:

* caching API responses aggressively
* caching old frontend bundles incorrectly
* stale app versions without update flow

### 16.3 Mobile Layout Risk

Desktop layouts often fail on phones because:

* sidebars take too much space
* hover actions do not exist
* keyboard changes viewport height
* inputs become hidden

Mitigation:

* design mobile nav separately
* use `100dvh`
* test on real devices

---

## 17. Open Questions

* What should the app icon look like?
* Should the mobile default route be `/home` or `/chat`?
* Should bottom nav include settings or hide it behind a menu?
* Should install guidance appear before or after login?
* Should push notification permission be introduced in a later dedicated phase?
* Should photos be hidden from service worker caching initially?
* Should the app name be `Friend-Hub` or a more distinctive branded name?

Recommended v1 answers:

* default route: `/home`
* bottom nav: Home, Chat, Events, Photos, Members
* settings in header/profile menu
* install guidance after login
* push notifications deferred
* no media caching initially

---

## 18. Final Acceptance Criteria

This phase is complete when:

* The existing React/Vite frontend remains the only frontend.
* The app is comfortable to use on mobile screen sizes.
* The app has a mobile bottom navigation.
* Chat is usable on mobile with a sticky input and sensible scrolling.
* The app has a valid PWA manifest.
* App icons are configured.
* The app can be added to a phone home screen.
* The service worker/app-shell caching works without breaking API/WebSocket behaviour.
* The production deployment serves the app over HTTPS.
* Real-device testing has been performed on at least one iPhone or Android device.

---

## 19. Recommended Codex Prompt For Batch A

```text
Implement Batch A of Phase PWA Mobile Init.

Goal:
Audit the existing React/Vite frontend and prepare a small mobile/PWA baseline without changing major behaviour.

Scope:
- Inspect the current frontend structure.
- Determine whether the app already has a manifest, service worker, or PWA setup.
- Identify current routing and layout structure.
- Check the chat layout for mobile issues.
- Add a short docs note or update this phase document with findings if appropriate.
- Add only minimal safe CSS baseline if clearly needed.

Do not:
- create a new frontend
- add native app tooling
- implement push notifications
- rewrite chat
- make large visual redesigns

Acceptance criteria:
- Existing frontend still builds.
- Existing chat still works.
- There is a clear list of what needs to change for mobile/PWA readiness.
- No major application behaviour changes are introduced.
```
