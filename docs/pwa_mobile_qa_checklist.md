# PWA Mobile QA Checklist

Use this for Batch G: Final Mobile QA. Record the device, browser/app mode, date, build/commit, and any screenshots or screen recordings for failures.

## Test Run

- Date:
- Tester:
- Build/commit:
- App URL:
- Notes:

## Devices And Modes

- [ ] iPhone Safari
- [ ] iPhone installed PWA
- [ ] Android Chrome
- [ ] Android installed PWA
- [ ] Desktop browser sanity check

## Core App Checks

- [ ] App loads without a blank screen.
- [ ] Refreshing a route works.
- [ ] Bottom navigation works.
- [ ] Active bottom navigation state is correct.
- [ ] More menu opens, navigates, and closes correctly.
- [ ] Non-chat pages keep good mobile padding.
- [ ] Desktop layout still has sidebar navigation and sensible content width.
- [ ] Standalone PWA opens in app-like mode from the home screen.
- [ ] Manifest, icon, splash/install presentation, and install guidance look correct.

## Chat Checks

- [ ] Open chat.
- [ ] Send a message.
- [ ] Receive a message.
- [ ] Scroll older history.
- [ ] Return to latest messages.
- [ ] Open and close the keyboard.
- [ ] Composer remains visible with keyboard closed.
- [ ] Composer remains visible with keyboard open.
- [ ] Bottom nav does not cover the composer.
- [ ] There is no double scrolling between page and message list.
- [ ] Long messages wrap correctly without horizontal overflow.
- [ ] Typing indicator does not break layout.
- [ ] Message actions are visible/tappable on touch.
- [ ] Reaction picker opens and is not clipped.
- [ ] Mention dropdown works with keyboard open.
- [ ] Mention dropdown handles a long suggestion list.
- [ ] Agenda banner renders and remains usable.
- [ ] Agenda modal opens and closes.
- [ ] Chat settings modal opens and closes.
- [ ] Group info panel opens and closes.
- [ ] Photo preview/modal opens and closes.
- [ ] Refreshing on `/chat` restores the chat route.

## PWA And Service Worker Checks

- [ ] Install to home screen.
- [ ] Launch from home screen.
- [ ] Background and foreground the app.
- [ ] Lock and unlock the phone while the app is open.
- [ ] WebSocket reconnects after background/foreground.
- [ ] WebSocket reconnects after lock/unlock.
- [ ] App update flow does not break routing.
- [ ] API routes are not served by the app shell fallback.
- [ ] WebSocket routes are not served by the app shell fallback.
- [ ] Upload routes are not served by the app shell fallback.
- [ ] Chat still receives live messages after service worker activation.

## Known Risks To Verify Manually

- iOS keyboard viewport behavior.
- Bottom nav and composer spacing on small screens and devices with a home indicator.
- Dense always-visible message actions on mobile.
- Mention dropdown with the keyboard open.
- Reaction picker clipping near scroll container edges.
- Standalone mode safe-area behavior.

## Results Template

### Device/Mode:

- Result: Pass / Fail / Blocked
- Browser or OS version:
- Install state: Browser / Installed PWA
- Account/session:
- Issues found:
- Screenshots/recordings:
- Follow-up owner:

### Issue Template

- Device/mode:
- Route:
- Steps:
- Expected:
- Actual:
- Severity: Blocker / Major / Minor
- Notes:

## Batch G Exit Criteria

- [ ] All device/mode categories have been tested or explicitly marked unavailable.
- [ ] No blocker issues remain.
- [ ] Chat composer is reachable in browser and standalone PWA modes.
- [ ] Bottom navigation does not cover primary actions.
- [ ] `/chat` refresh works.
- [ ] Non-chat routes retain acceptable mobile padding.
- [ ] Service worker does not intercept API, WebSocket, or upload routes incorrectly.
