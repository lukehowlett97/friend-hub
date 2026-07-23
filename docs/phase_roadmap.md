# Friend App — Next Phases Roadmap

## Purpose

Build the app into a private friends hub before attempting to replace Messenger.

The near-term goal is to create something useful enough for friends to test, without needing a fully mature real-time chat system from day one.

The app should become a place for:

* planning nights out, trips, events, and ideas
* voting on decisions
* storing reminders and useful links
* viewing group activity and stats
* eventually chatting, searching, and importing old Messenger history

---

## Guiding Principle

Do not build “proper chat” first.

Proper chat requires a more organised storage model, user identity, message persistence, permissions, backups, and eventually attachments/search. Instead, build the surrounding social/planning features first so the app has value before chat is perfect.

The first testable version should feel like a lightweight private group operating system.

---

# Phase 1 — Testable Friends Hub

## Goal

Create a useful version of the app that a small group of friends can test immediately.

This phase should prove whether people will actually open and use the app.

## Core Features

### 1. Home Dashboard

A simple landing page showing the current state of the group.

Include:

* recent activity
* upcoming events
* active polls
* latest ideas
* reminders
* server/app status summary
* group stats teaser

The homepage should make the app feel alive even before chat exists.

### 2. Ideas Section

A place to store potential plans and schemes.

Example categories:

* pub ideas
* trip ideas
* camping ideas
* film/night ideas
* food places
* random schemes

Each idea could support:

* title
* description
* creator
* created date
* status: maybe / planned / done / rejected
* comments
* reactions

### 3. Polls

A quick way to make group decisions.

Useful for:

* which date works best
* where to go
* who is in
* what activity to do
* what time to meet

Minimum fields:

* question
* options
* voters
* deadline, optional
* linked idea/event, optional

### 4. Events

A simple planning calendar for group activities.

Include:

* title
* date/time
* location
* description
* attendees
* maybe/maybe not responses
* linked reminders
* linked poll, optional

### 5. Reminders

Shared reminders for plans and admin.

Examples:

* bring tent
* book train
* pay someone back
* buy tickets
* check weather
* confirm numbers

Fields:

* reminder text
* due date/time, optional
* assigned person, optional
* linked event, optional
* completed status

### 6. Admin / Server Resources Page

Mostly for debugging and self-hosting confidence.

Show:

* CPU usage
* RAM usage
* disk usage
* Docker container status
* uptime
* database size
* last deploy time
* backup status
* recent errors/log snippets
* active users
* number of ideas/events/polls/messages

This helps make the VPS setup feel like a proper self-hosted product.

## Phase 1 Storage Requirements

Use PostgreSQL as the main source of truth.

Suggested tables:

```text
users
ideas
polls
poll_options
poll_votes
events
event_attendees
reminders
activity_log
```

Avoid heavy attachment handling for now. Keep Phase 1 mostly text-based.

## Phase 1 Success Criteria

Phase 1 is successful if:

* 3–5 friends can log in
* people can add ideas
* people can vote in polls
* events can be created and updated
* reminders are visible and useful
* the homepage gives a quick overview
* the app feels useful without full chat

## Suggested Test Pitch

> I’m testing a little private group planning app. Use it for the next pub plan/trip idea and tell me what’s annoying.

Avoid pitching it as a Messenger replacement at this stage.

---

# Phase 2 — Make It Feel Alive

## Goal

Add social feedback loops so the app feels active and worth checking.

## Features

### 1. Activity Feed

Show a timeline of group actions.

Examples:

* Dan created an idea
* Mike voted in a poll
* Luke added an event
* Someone completed a reminder
* A plan moved from maybe to planned

This gives the app energy and helps users understand what changed.

### 2. Comments

Add comments to:

* ideas
* events
* polls
* reminders

This gives the group a lightweight discussion layer before full chat.

### 3. Reactions

Simple emoji reactions on ideas/comments/events.

Useful because they are low-effort and fun.

### 4. Mobile Polish / PWA Improvements

The app should feel decent on phones.

Focus on:

* responsive layout
* bottom navigation
* large touch targets
* installable PWA behaviour
* sensible loading states
* clear empty states

### 5. Notifications

Start simple.

Possible notification types:

* new poll created
* event updated
* reminder due soon
* someone commented on your idea

This could begin as in-app notifications before email/push notifications.

## Phase 2 Storage Requirements

Additional tables:

```text
comments
reactions
notifications
user_notification_preferences
```

## Phase 2 Success Criteria

Phase 2 is successful if:

* users can see what changed since they last opened the app
* ideas/events have lightweight discussion
* the mobile experience is usable
* notifications or reminders bring people back

---

# Phase 3 — Proper Chat Foundation

## Goal

Add basic chat once the user, group, and storage model are stable.

Do not overbuild chat initially. Start with one private group chat.

## Minimum Chat Features

* send message
* persist messages
* display message history
* basic user identity
* timestamps
* reactions
* edited/deleted status, optional
* simple read status, optional

## Features To Delay

Avoid these until basic chat works well:

* attachments
* voice notes
* complex threads
* multi-room permissions
* typing indicators
* end-to-end encryption
* advanced moderation

## Suggested Tables

```text
chat_threads
chat_messages
message_reactions
message_reads
```

## Storage Considerations

For text chat, PostgreSQL is enough.

For files/images later, use either:

* local VPS filesystem with a clean directory structure
* S3-compatible object storage
* dedicated object storage provider

Suggested local structure if using the VPS filesystem:

```text
/app-data/
  uploads/
    images/
    files/
  exports/
  backups/
  logs/
```

## Phase 3 Success Criteria

Phase 3 is successful if:

* the group can use one shared chat
* messages persist reliably
* the database can be backed up
* the app remains stable after normal usage

---

# Phase 4 — Search And Memory Layer

## Goal

Make the app useful as a searchable memory bank for the group.

## Search Targets

Search should cover:

* ideas
* events
* reminders
* comments
* chat messages
* links
* imported Messenger history later

## Search Approach

Start with PostgreSQL full-text search.

Avoid Elasticsearch or OpenSearch unless PostgreSQL becomes too limited.

## Nice Features

* filter by person
* filter by date
* filter by content type
* search shared links
* saved searches
* “on this day” style discoveries

## Suggested Tables / Columns

May not need many new tables initially, but add indexed searchable text columns where useful.

Potential addition:

```text
shared_links
search_index
```

A dedicated `search_index` table could be useful later, but simple PostgreSQL indexes are enough at first.

## Phase 4 Success Criteria

Phase 4 is successful if:

* users can find old plans, comments, and messages
* search is fast enough for normal usage
* the app starts to feel like a group archive

---

# Phase 5 — Plotly Stats Dashboard

## Goal

Integrate the existing Plotly dashboard work into the app.

This should be one of the fun, distinctive features of the app.

## Dashboard Ideas

* messages per person
* activity by day/week/month
* most active hours
* most used words
* reaction counts
* biggest yapper leaderboard
* event attendance stats
* poll participation stats
* group timeline
* nostalgia charts

## Integration Options

### Option A — Static HTML Embed

Export Plotly dashboard as HTML and embed it in the app.

Pros:

* easiest
* quick to ship
* minimal backend complexity

Cons:

* less interactive with live app state
* harder to apply permissions cleanly

### Option B — Generate Figures In Backend

Generate Plotly JSON from backend data and render it in the frontend.

Pros:

* cleaner long-term integration
* works with live data
* easier to filter by date/person

Cons:

* more engineering effort

### Option C — Separate Analytics Service

Run the stats/dashboard as a separate internal service.

Pros:

* keeps app cleaner
* useful if analytics becomes heavy

Cons:

* more deployment complexity

## Recommendation

Start with Option A or B.

If the current Plotly dashboard already exists and works, embed/export it first, then refactor later.

## Phase 5 Success Criteria

Phase 5 is successful if:

* users can view group stats inside the app
* charts update from stored app data or imported chat data
* the dashboard feels fun rather than just technical

---

# Phase 6 — Facebook Messenger Import

## Goal

Import old Facebook Messenger history and turn it into searchable/fun group memory.

## Import Pipeline

1. Export Facebook Messenger data as JSON.
2. Upload export to the app or process locally first.
3. Parse messages.
4. Normalise participants.
5. Store messages in PostgreSQL.
6. Generate stats.
7. Make imported messages searchable.
8. Decide what is visible to the group.

## Important Privacy Point

Be careful with this.

Old private messages becoming searchable could feel weird to people. It is better to start with private/local analytics, then expose selected stats or nostalgia features once everyone is comfortable.

## Suggested Import Tables

```text
import_jobs
imported_message_sources
chat_messages
message_attachments_metadata
participant_aliases
```

## Features From Imported Data

* search old messages
* group stats
* “on this day” moments
* funniest quotes
* most active periods
* old shared links
* timeline of the group chat

## Phase 6 Success Criteria

Phase 6 is successful if:

* Messenger JSON can be imported reliably
* participants are mapped to current users
* imported messages are searchable or analysable
* privacy expectations are clear

---

# Longer-Term Ideas

## Shared Links Board

A place to save links that would otherwise vanish in chat.

Categories:

* places
* restaurants
* events
* Airbnbs
* campsites
* tickets
* memes
* useful resources

## Group Ledger

Track simple debts and shared costs.

Examples:

* who owes who
* trip costs
* petrol money
* tickets
* food shop split

## Friend Profiles

Small fun profiles for each friend.

Fields could include:

* nickname
* birthday
* running jokes
* favourite quotes
* attendance stats
* most-used words
* personal leaderboard stats

## Plan Board

A simple Kanban-style board for group plans.

Columns:

```text
Maybe
Planned
Booked
Done
Rejected
```

Useful for trips, nights out, camping weekends, and holidays.

---

# Recommended Build Order

## Immediate Next Build

Build these first:

1. Home dashboard
2. Ideas
3. Polls
4. Events
5. Reminders
6. Admin/server resources page

This gives you a testable product without needing mature chat.

## Then Add

1. Activity feed
2. Comments
3. Reactions
4. Mobile polish
5. In-app notifications

## Then Add

1. Basic group chat
2. Search
3. Plotly stats dashboard
4. Messenger import

---

# MVP Scope For First Friend Test

The first version does not need to be perfect.

It only needs:

* login
* one group
* home dashboard
* create idea
* vote in poll
* create event
* add reminder
* basic mobile layout

Do not add too many settings or admin controls early.

The test question is simple:

> Do my friends actually use this for planning anything?

If yes, continue building.

If no, improve the loop before building more infrastructure.

---

# Technical Notes

## Backend

Use PostgreSQL as the main database.

Core early tables:

```text
users
groups
group_members
ideas
polls
poll_options
poll_votes
events
event_attendees
reminders
activity_log
```

Later tables:

```text
comments
reactions
notifications
chat_threads
chat_messages
message_reactions
message_reads
shared_links
import_jobs
```

## Backups

Before inviting friends properly, add a backup process.

Minimum:

* daily PostgreSQL dump
* keep last 7–14 days
* store outside the main app directory if possible
* test restore once

## VPS Storage

Suggested structure:

```text
/srv/friend-app/
  app/
  data/
    postgres/
    uploads/
    exports/
    backups/
    logs/
  docker-compose.yml
  .env
```

## Deployment

Keep deployment simple:

* Docker Compose
* PostgreSQL container or managed database later
* reverse proxy
* HTTPS
* environment variables in `.env`
* basic monitoring page inside the app

---

# Final Recommendation

Treat the app as a private social planning and memory tool first.

The strongest next feature set is:

```text
Home dashboard
Ideas
Polls
Events
Reminders
Admin/server status
```

This lets the app become useful quickly, gives friends something to test, and avoids getting stuck building a full Messenger replacement before the foundations are ready.
