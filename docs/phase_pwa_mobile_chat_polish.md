# Phase: PWA Mobile Chat Polish

## Goal

Make the mobile chat page feel native, reliable, and space-efficient inside the installed PWA and mobile browser.

## Current Problems

- `frontend/src/components/AppShell/AppShell.css` still had fragile chat height ownership before this phase: `.page-chat` used `height: calc(100vh - clamp(...))` and, on mobile, `height: calc(100vh - var(--mobile-chat-height-offset))`. This tied chat layout to guessed shell spacing instead of flex ownership.
- `frontend/src/components/Chat/Chat.css` defines `.chat-wrapper` with `height: 100vh` and `height: 100dvh`. The `.page-chat .chat-wrapper` override now makes the route flex-owned, but the top-level chat default remains worth revisiting if chat is ever embedded outside `.page-chat`.
- Mobile chat padding was partly handled by `.app-main:has(.page-chat)` in `AppShell.css`. That works in modern browsers, but it is implicit and harder to reason about than route-aware shell state. `AppShell.jsx` now adds `app-main--chat` for `/chat`.
- Normal `.app-main` padding wastes vertical space for chat. The chat route now removes that padding on mobile through `.app-main--chat`, while normal pages keep `var(--page-padding)` and bottom-nav padding.
- The message list/composer model is mostly correct but should be protected carefully: `.chat-container` is flex column, `.message-list` is `flex: 1`, `min-height: 0`, and `overflow-y: auto`, and `.message-input-container` is fixed in the column. This should remain the only main chat scrolling region.
- Bottom nav overlap risk remains a key mobile constraint because `.mobile-bottom-nav` is `position: fixed` in `AppShell.css`. The first slice keeps the nav behavior and reserves composer padding on mobile with `var(--bottom-nav-height)` unless the nav is hidden or the keyboard is open.
- Safe-area handling exists in `.mobile-bottom-nav` and `.message-input-container` through `env(safe-area-inset-bottom)`, but it still needs real iPhone standalone PWA and Safari testing.
- iOS keyboard behavior is not fully proven. `MessageInput.jsx` toggles `body.chat-keyboard-open` on input focus/blur, and `Chat.jsx` writes `--visual-viewport-height` from `window.visualViewport`. This is the right direction, but it needs testing with Safari browser chrome, standalone PWA mode, rotation, and lock/unlock.
- Hover-only message actions have already been partially addressed. `MessageList.jsx` tracks `activeMsgId`, `Message.jsx` adds `.show-actions` on tap, and `Chat.css` reveals `.message-actions` on `.message.chat.show-actions`. Desktop hover remains, but core reply/react/edit/delete actions are not hover-only on touch.

## Desired Layout Model

App shell owns the viewport
→ mobile bottom nav is fixed outside the main content flow or explicitly accounted for
→ chat route gets a special compact/full-height layout
→ chat page uses flex column
→ message list is the only scrolling region
→ composer stays visible
→ no hardcoded viewport subtraction where avoidable

Important CSS rules:

- Put `min-height: 0` on flex parents that contain the scrollable message list: `.app-main--chat`, `.page-chat`, `.chat-wrapper`, `.chat-container`, and `.message-list`.
- Use `overflow: hidden` on app/chat containers that own the viewport so the body or page does not become a competing scroll container.
- Keep `overflow-y: auto` on `.message-list`; avoid adding independent vertical scrolling to `.chat-container` or `.page-chat`.
- Use `100dvh` with `100vh` fallback at the shell boundary. Prefer flex sizing inside the shell over repeated `calc(100vh - ...)` rules.
- Reserve bottom safe-area and bottom-nav clearance at the composer/bottom nav layer, not by shrinking the whole chat route with guessed viewport subtraction.
- Avoid fixed pixel chat heights. If a fixed shell component must be accounted for, use a shared CSS variable like `--bottom-nav-height` near the component it affects.

## Recommended Architecture

Use a route-aware app shell layout mode:

- In `frontend/src/components/AppShell/AppShell.jsx`, detect `currentPath === '/chat'`.
- Add `app-main--chat` to `<main className="app-main">` for the chat route.
- Keep normal `.app-main` padding for Home, Items, Photos, Calendar, Members, Settings, and other feature pages.
- Make `.app-main--chat` a flex column with hidden overflow, and let `.page-chat` plus `.chat-wrapper` fill the available space.

Class names now used or recommended:

- `app-main--chat`
- `page-chat`
- `chat-wrapper`
- `chat-container`
- `message-list`
- `message-input-container`

If the chat component is renamed later, prefer semantic names like `chat-shell`, `chat-message-list`, and `chat-composer`, but avoid a broad rename during this phase.

## Implementation Plan

1. Audit current mobile chat layout and CSS.
2. Add route-aware chat layout class in the app shell.
3. Remove fragile chat height calculations.
4. Refactor chat container to use flex-based full-height layout.
5. Ensure message list is the only scrollable area.
6. Ensure composer remains visible above bottom nav and safe areas.
7. Remove hover-only dependencies or add tap-visible equivalents.
8. Test desktop chat still works.
9. Add manual QA checklist for Batch G.

## Manual QA Checklist

Mobile browser:

- [ ] iPhone Safari
- [ ] Android Chrome

Standalone PWA:

- [ ] iPhone installed to home screen
- [ ] Android installed to home screen

Scenarios:

- [ ] Open chat
- [ ] Send message
- [ ] Receive message
- [ ] Scroll message history
- [ ] Open keyboard
- [ ] Rotate device
- [ ] Lock/unlock phone
- [ ] Background/foreground app
- [ ] Verify WebSocket reconnect
- [ ] Verify bottom nav does not cover composer
- [ ] Verify composer does not disappear behind keyboard
- [ ] Verify latest messages remain reachable
- [ ] Verify chat route refresh works
- [ ] Verify non-chat pages still have good padding

## Batch C Remaining Work

- Manually test the current visualViewport keyboard path on iOS Safari and standalone iOS PWA.
- Verify whether composer bottom-nav clearance feels too tall when the mobile nav is visible; tune only after device screenshots.
- Confirm message actions are discoverable on touch. The tap-to-reveal mechanics exist, but a visible affordance or long-press pattern may still be useful.
- Check agenda banner, loading/error bars, typing indicator, mention dropdown, photo modal, group info panel, and chat settings sheet inside the mobile flex layout.

## Slice 2 Findings

- `frontend/src/components/Chat/Chat.css` still gave `.chat-wrapper` its own `height: 100vh` / `height: 100dvh`. That made the chat component compete with the route-aware app shell for viewport ownership.
- `frontend/src/components/Chat/ChatHome.css` appears unused by the current `/chat` route, but it still had old standalone page assumptions: `.chat-home { height: 100vh; overflow-y: auto; }`. If reintroduced, it would bypass the intended app-shell/chat flex model.
- `frontend/src/components/Chat/AgendaModal.css` uses a fixed overlay, so it should not be clipped by `.app-main--chat { overflow: hidden; }`. Its inner modal still used `calc(100vh - 2rem)`, so it needed a `100dvh` override for mobile browser chrome.
- `HubItemPopup.css`, `PersonPopup.css`, `ChatSettingsModal` styles in `Chat.css`, and `GroupInfoPanel` styles in `Chat.css` already use fixed-position overlays/backdrops. These should escape chat container clipping, but still need device testing for safe-area and keyboard behavior.
- Message actions were not hover-only in code because `MessageList.jsx` and `Message.jsx` support tap-to-reveal via `.show-actions`. However, the controls were still visually hidden until the user discovered the tap interaction.

## Slice 2 Changes

- `frontend/src/components/AppShell/AppShell.css`
  - Promoted `app-main--chat` to explicit viewport ownership on all breakpoints with `height: 100vh` / `height: 100dvh`.
  - Kept mobile chat padding removal scoped to `.app-main--chat`.
- `frontend/src/components/Chat/Chat.css`
  - Changed `.chat-wrapper` from direct viewport sizing to `height: 100%` plus `min-height: 0`, so `/chat` inherits the shell-owned height.
  - Added a coarse-pointer fallback that keeps `.message-actions` visible and tappable on touch devices, including compact spacing mode.
- `frontend/src/components/Chat/ChatHome.css`
  - Replaced standalone viewport sizing with flex-owned `height: 100%`, `flex: 1`, `min-height: 0`, and `overflow: hidden`.
  - Kept `.members-list` as the scrollable region and added mobile bottom-nav/safe-area padding to the wrapper.
- `frontend/src/components/Chat/AgendaModal.css`
  - Added `100dvh` max-height overrides and mobile safe-area bottom padding for the bottom-sheet modal.

## Remaining Layout Risks

- Real iOS Safari and installed iOS PWA behavior still needs manual confirmation. The `visualViewport` path and `chat-keyboard-open` class are browser-sensitive.
- Always-visible mobile message actions may need visual tuning after testing with dense message history. This was chosen as a low-risk accessibility/discoverability fallback.
- The mention dropdown is positioned above the sticky composer and should stay in the chat column, but it should be checked with the keyboard open and with long suggestion lists.
- Reaction picker is still positioned inside the message row/list. It may clip near the top edge of the scroll container if opened on the first visible message.
- ChatHome is not currently routed, so its changes are preventive and should be verified only if that view is restored.
