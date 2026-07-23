# Member Cleanup and Messenger Identity Linking

## Goal

Clean up the member system so Friend Hub can clearly distinguish between:

- Real app users who can log in
- Imported Messenger participants from historical chat data
- Test users, bot users, and system users

The app should preserve all imported history, while keeping the normal member list clean and usable.

## Current Problem

The member list currently contains a mixed set of identities:

- Real users
- Imported Facebook Messenger names
- Temporary generated users
- Test accounts
- Hub Bot/system accounts

This creates several issues:

- The member list looks messy
- Imported Messenger users appear as if they are real app users
- Test users clutter the UI
- Historical message stats cannot cleanly combine with real app usage
- Admins have no clear way to say which imported Messenger identity belongs to which real user

## Desired Outcome

Admins should be able to manage identities properly.

At the end of this phase:

- Imported Messenger participants are stored as imported identities, not normal app users
- Real users remain separate login-capable accounts
- Admins can link imported Messenger identities to real users
- Linked stats can be combined across Messenger history and Friend Hub usage
- Test users can be marked, hidden, deactivated, or safely deleted
- Public member lists only show clean active members
- Admin pages can still show the full messy underlying identity data

## Identity Types

### 1. Real App User

A real app user is someone who can log in to Friend Hub.

Examples:

- Techlett
- lololhahahaa
- Dave
- Chris

These users may have:

- login credentials or PIN
- admin status
- active sessions
- profile details
- chat colour
- notification settings

### 2. Imported Messenger Identity

An imported Messenger identity is a historical participant from Facebook Messenger data.

Examples:

- Luke Howlett
- Max Harlow
- Adam Crease
- Charlie Richardson

These identities may not have app accounts.

They should be preserved for historical messages, stats, search, and AI context.

### 3. Test User

A test user is a development or temporary account.

Examples:

- TestUser2
- TestUser3
- User-129941b
- User-691d7d26
- User-d6369a5

These should be hidden from normal member lists and easy for admins to clean up.

### 4. Bot/System User

Examples:

- Hub Bot
- Meta AI
- Import System

These should be clearly marked as bot/system identities.

They should not be confused with human users.

## Data Model Proposal

### imported_identities

Create a dedicated table for imported Messenger participants.

Fields:

- id
- source
- source_participant_id nullable
- source_display_name
- normalised_name
- linked_user_id nullable
- status
- message_count
- first_seen_at
- last_seen_at
- confidence_score nullable
- notes nullable
- created_at
- updated_at

Source values:

- messenger

Status values:

- unlinked
- linked
- ignored
- duplicate
- archived

### users

Extend the existing users table with cleanup/status fields if they do not already exist.

Suggested fields:

- user_type
- status
- is_test_user
- is_bot
- hidden_from_member_list
- deactivated_at nullable

User type values:

- human
- bot
- system
- test

Status values:

- active
- invited
- deactivated
- archived
- deleted

Avoid hard deletion unless the user has no important linked data.

## Linking Behaviour

Admins should be able to link one or more imported Messenger identities to a real app user.

Example:

Luke Howlett imported from Messenger is linked to Techlett.

After linking:

- Historical Messenger messages still belong to the imported identity
- Friend Hub messages still belong to the real user
- Stats views can combine both under the linked real user
- Source-level breakdown remains available

Example display:

Luke / Techlett

- Friend Hub messages: 120
- Messenger messages: 14,230
- Total messages: 14,350

## Admin Identity Management Page

Add an admin-only page called:

Member Identity Management

Suggested tabs:

### Real Users

Shows login-capable app users.

Columns:

- Display name
- Username
- Role
- Status
- Linked imported identities
- Message count
- Last active
- Actions

Actions:

- Link imported identity
- Deactivate
- Reactivate
- Mark as test
- Hide from member list
- Reset PIN
- Make admin
- Remove admin

### Imported Messenger Identities

Shows imported historical participants.

Columns:

- Imported name
- Source
- Status
- Linked user
- Message count
- First seen
- Last seen
- Suggested matches
- Actions

Actions:

- Link to user
- Create invite for this person
- Mark ignored
- Mark duplicate
- Merge imported identities
- Add notes

### Cleanup

Shows likely junk/test/system users.

Examples:

- Generated usernames
- Users with no messages
- Users with no sessions
- Users with test-looking names
- Old imported placeholder users

Actions:

- Mark as test
- Hide from member list
- Deactivate
- Delete if safe
- Reassign messages if needed

## Member List Display Rules

Normal users should not see the messy identity layer.

Public member lists should show:

- active real users
- invited real users if relevant
- bot users only where useful

Public member lists should hide:

- unlinked imported identities
- ignored imported identities
- duplicate imported identities
- test users
- deactivated users
- archived users
- generated placeholder users
- system users unless explicitly needed

Admin pages can show everything.

## Messenger Import Rules

During Messenger import:

- Do not create real login users for every Messenger participant
- Create imported identities instead
- Attach imported messages to imported identities
- Preserve original Messenger display names
- Store normalised names for matching
- Avoid destructive merging during import

If the importer already created placeholder users, add a migration or admin cleanup flow to convert them into imported identities where safe.

## Matching Suggestions

The app can suggest likely links between imported identities and real users.

Suggested matching signals:

- exact display name match
- normalised name match
- nickname match
- same first name
- known aliases
- manually entered admin notes
- invite claim information
- imported participant name matching account display name

Do not auto-link permanently without admin approval.

## Stats Behaviour

Stats should support both separated and combined views.

For linked users:

- show combined totals by default
- allow source breakdown

Example:

Dave

- Total messages: 8,430
- Messenger: 8,100
- Friend Hub: 330

For unlinked imported identities:

- show them in historical stats if relevant
- do not show them as active app members

For ignored/test users:

- exclude from normal leaderboards by default
- allow admin/debug views to include them

## AI Behaviour

Hub Bot should understand linked identities.

If Luke Howlett is linked to Techlett:

- searches for Luke should include historical Messenger messages
- summaries should know they are the same person
- stats should combine where appropriate
- the bot should avoid treating imported Luke and current Luke as separate people

However, the bot should preserve source context when needed.

Example:

“Luke said this in the old Messenger chat.”

versus:

“Luke said this recently in Friend Hub.”

## Safety and Deletion Rules

Prefer soft deletion.

Safe cleanup order:

1. Mark as test
2. Hide from member lists
3. Deactivate login
4. Archive
5. Hard delete only if no important data exists

Before hard deleting a user, check:

- messages
- comments
- votes
- events created
- photos uploaded
- reactions
- sessions
- notifications
- linked imported identities

If any meaningful data exists, deactivate/archive instead.

## Migration Plan

### Step 1: Add imported identity model

Create imported_identities table.

### Step 2: Add user cleanup fields

Add user_type, status, is_test_user, is_bot, and hidden_from_member_list if missing.

### Step 3: Update Messenger importer

Ensure imported participants become imported identities, not real users.

### Step 4: Backfill existing imported users

Identify users that look like imported Messenger placeholders.

Move or link them into imported_identities where safe.

### Step 5: Build admin identity page

Create admin-only UI for linking, ignoring, merging, and cleaning up identities.

### Step 6: Update member list queries

Hide imported/test/deactivated/system users from normal member views.

### Step 7: Update stats

Allow stats to combine linked imported identities with real users.

### Step 8: Update Hub Bot context

Make AI/member lookup aware of linked identities.

## Acceptance Criteria

- Real users and imported Messenger identities are clearly separate
- Imported Messenger history is preserved
- Admins can link imported identities to real users
- Linked user stats can combine Messenger and Friend Hub messages
- Test users can be marked, hidden, deactivated, or safely deleted
- Normal member lists no longer show imported/test clutter
- Hub Bot is not broken by identity linking
- Existing messages remain attached to the correct historical identity
- No historical data is lost
- Existing authentication still works
- Existing admin user management still works
- Existing tests pass
- New tests cover identity linking, hidden users, and imported identity stats

## Future Ideas

- User profile page showing historical Messenger stats
- “Claim your old Messenger identity” invite flow
- Admin confidence score for suggested matches
- Alias system for nicknames
- Merge duplicate imported identities
- Per-user chat colour and profile customisation
- “Friend Hub Wrapped” stats using combined historical identity data