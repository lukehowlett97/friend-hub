Phase: Chat Council, Roles, Nicknames, and Banter Systems
Goal

Make the group chat feel more alive, funny, and socially interactive by introducing playful governance features.

This phase turns the chat into a tiny democratic society where members can vote on nicknames, roles, rules, silly punishments, and scheduled Council Sessions.

The aim is not serious moderation. The aim is banter, group identity, running jokes, and lightweight chaos.

Core Concept

The chat should support:

member nicknames
member roles
member descriptions
vote-based nickname changes
vote-based role changes
admin-controlled governance settings
silly temporary punishments
group rules
scheduled Council Sessions
AI-aware group context later

The app should feel like a smooth mobile-first social app, not an admin dashboard.

Feature 1: Member Profiles

Each chat member should have a profile containing:

display name
nickname
role
description
avatar or emoji
current status
active restrictions
created date
updated date

Example:

Name: Luke
Nickname: The Bean Chancellor
Role: Founding Member
Description: Starts most of the chaos and pretends it is product strategy.
Status: Free citizen

Nicknames and roles should be visible in chat without cluttering the message UI.

Example chat display:

The Bean Chancellor · Founding Member
Anyone fancy the pub?

Feature 2: Nickname Voting

Members should be able to propose nicknames for each other.

Example:

Motion: Rename Mike to “The Maybe Merchant”
Target: Mike
Duration: 10 minutes
Options: Approve / Reject

If the vote passes, the nickname is changed automatically.

The result should post into the chat:

Motion passed. Mike is now known as “The Maybe Merchant”.

Feature 3: Admin-Controlled Nickname Settings

The group admin should be able to choose how nicknames work.

Possible settings:

admin only
self edit
vote required
free for all

Recommended default:

vote required

This gives the feature its personality. Nobody fully owns their identity. The council does.

The admin should also be able to configure:

minimum votes required
vote pass threshold
vote duration
whether self nickname changes are allowed
whether admin override is allowed

Example:

Nickname changes require:

at least 3 votes
more than 50 percent approval
vote open for 10 minutes
Feature 4: Roles

Members can have roles.

Roles should start as cosmetic, then become more powerful later.

Examples:

Admin
Council Member
Jester
Vibes Officer
Treasurer of Pints
The Accused
Emoji Prisoner
Pub Secretary
Minister for Bad Ideas

Roles can be assigned by:

admin
vote
Council Session result
temporary event outcome

Role settings could include:

admin only
vote required

Roles can be temporary or permanent.

Example:

Mike is Jester until Friday 23:59.

Feature 5: Silly Temporary Punishments

The group should be able to vote for tiny, harmless punishments.

Examples:

1 minute timeout
emoji-only mode
caps-only mode
no vowels mode
3 words max mode
must end every message with “my liege”
only allowed to send pub-related words

These should always be:

short
funny
reversible
clearly visible
not serious moderation

Example:

Motion passed. Luke has entered emoji jail for 60 seconds.

When the user tries to send a normal message:

You are currently in emoji jail. 34 seconds remaining.

Feature 6: Group Rules

The chat can build its own constitution.

Members can propose rules.

Example:

Motion: Create new rule
Rule: Anyone who says “quiet pint” must attend.
Duration: 15 minutes

If passed, the rule is added to the group rulebook.

Rule statuses:

active
expired
repealed
rejected

The app should have a “Group Rules” or “Constitution” section.

Feature 7: Council Sessions

Council Sessions are scheduled group events where important or stupid matters are voted on.

Example:

Council Session: Friday Pub Council
Time: Friday 18:00
Agenda:

Where are we going?
Who is actually coming?
Should Mike be punished for saying maybe?
Vote on Luke’s new nickname

A Council Session should have:

title
description
scheduled start time
scheduled end time
agenda items
linked votes
host
status

Statuses:

scheduled
live
completed
cancelled

When a Council Session starts, the chat should show a live banner:

Council Session is live: Friday Pub Council
Agenda item 1: Where are we going?

Votes can become active during the session.

Example:

Agenda item 2 is now open for voting:
Should Mike be renamed “The Maybe Merchant”?

Feature 8: Council Session Voting

A Council Session can contain multiple matters.

Each matter can have a vote.

Matter types:

nickname change
role change
rule creation
rule repeal
punishment
general poll
event decision

Example matter:

Matter: Rename Luke
Type: nickname change
Target: Luke
Proposed nickname: The Bean Chancellor
Voting opens: 18:10
Voting closes: 18:15

When voting closes, the result is applied automatically if the matter passes.

Example result:

Council decision passed.
Luke is now “The Bean Chancellor”.

Feature 9: AI Group Context

Later, the AI chatbot should be able to understand the group’s identity and history.

Useful context:

members
nicknames
roles
descriptions
active rules
recent Council Session outcomes
running jokes
active restrictions
important group lore

Example AI context:

Luke is currently known as The Bean Chancellor.
Mike is known as The Maybe Merchant.
The group rulebook says anyone who suggests a quiet pint must attend.
Mike is currently Jester until Friday.

This would make the chatbot much funnier and more personal.

Recommended Build Order
Phase 1: Member Profiles and Roles

Build:

member nickname field
member role field
member description field
member profile modal
role badge in chat
basic admin edit controls

Do not build voting yet.

Phase 2: Vote-Based Nickname Changes

Build:

propose nickname change
vote card in chat
approve or reject voting
vote expiry
automatic nickname update when passed
admin setting for nickname change mode

This is the first properly fun phase.

Phase 3: Generalised Vote Actions

Extend voting to support:

role changes
rule creation
rule repeal
silly punishments
general polls

Create a reusable vote action system.

Phase 4: Silly Restrictions

Build temporary restrictions:

timeout
emoji-only mode
caps-only mode
no vowels mode
max words mode

Restrictions should be enforced when sending messages.

Phase 5: Group Rules and Constitution

Build:

rule proposals
active rules list
repealed rules list
rule history
rule cards
link rules to votes
Phase 6: Council Sessions

Build:

scheduled Council Sessions
agenda items
live event banner
linked votes
matter voting
automatic result posts
completed session summary
Data Model Ideas

Possible tables:

chat member profiles
chat roles
chat votes
chat vote options
chat vote responses
chat vote actions
chat rules
chat restrictions
council sessions
council session agenda items
council session matters

Existing Hub Items could be used for references:

Vote item
Rule item
Event item
Council matter item

Example references:

V-1 Nickname Vote
R-1 Group Rule
E-1 Council Session
M-1 Council Matter
UX Principles

Keep it:

mobile-first
funny
fast
tap-based
social
visible in chat
not buried in settings
not too serious

Use bottom sheets, cards, banners, and quick actions.

Avoid making it feel like Discord admin settings.

Example Chat Flow

Luke proposed a motion:
Rename Mike to “The Maybe Merchant”

Votes:

Approve: 4
Reject: 1
Time remaining: 03:22

Then:

Motion passed.
Mike is now known as “The Maybe Merchant”.

Then Mike sends a message:

The Maybe Merchant · Jester
I might come out Friday

Then the chat replies:

Council violation detected.
Use of “might” has been recorded.