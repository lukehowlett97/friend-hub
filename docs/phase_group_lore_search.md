# Group Lore

## Purpose

The Group Lore page is a searchable memory layer for Friend Hub.

It lets users search historic chat messages, find old jokes, settle arguments, rediscover plans, and analyse who says certain phrases the most.

This page should feel fun, social, and nostalgic — not like enterprise search.

The goal is to make the group chat feel like it has a living archive.

## Product Feeling

Group Lore should feel like:

- finding old receipts
- rediscovering group jokes
- searching shared memories
- settling “who said that?” debates
- exploring the history of the friendship group

It should not feel like:

- admin tooling
- analytics software
- database search
- corporate message search

Suggested emotional direction:

> Find old lore, settle arguments, and rediscover funny moments.

## Core Features

### 1. Message Search

Users can search for a word or phrase across the imported group chat.

The app should return a list of matching message candidates.

Each result should show:

- sender avatar
- sender name
- message snippet
- highlighted matching text
- timestamp/date
- surrounding context if available
- click/tap action to open that message in the chat

Example result:

Luke  
“Benidorm is going to ruin us”  
4 Mar 2025  
Open in chat

### 2. Open Result In Chat

Clicking a search result should navigate to the exact message location in the chat.

Expected behaviour:

- open the chat page
- scroll to the message
- highlight the matched message temporarily
- load enough surrounding messages to give context
- preserve the search query state when returning to Group Lore

This makes search useful for rediscovering full conversations, not just isolated messages.

### 3. Phrase Occurrence Stats

For a searched phrase, the page should optionally show a bar chart of how many times each person said that phrase.

Example:

Search: “pub”

Luke: 42  
Ryan: 25  
Tom: 12  
Ben: 8

This should be fun and social, almost like a leaderboard.

Possible use cases:

- who says “lol” the most?
- who first mentioned “Benidorm”?
- who talks about the pub the most?
- who uses a specific in-joke?
- which phrases define the group?

### 4. Search Modes

The page should support multiple modes.

#### Messages

Default mode.

Shows matching message candidates.

#### People

Shows phrase counts by sender.

Includes chart visualisation and summary stats.

#### Timeline

Optional future mode.

Shows occurrences over time.

Useful for seeing when a joke, plan, or topic became active.

Example:

“Benidorm peaked in March before the trip was booked.”

## Suggested Page Layout

Mobile-first layout:

1. Header
2. Search bar
3. Search filters
4. Result mode tabs
5. Results area

Example:

Group Lore  
Find old jokes, receipts, and forgotten plans.

Search messages...

Tabs:
- Messages
- People
- Timeline

## Search Filters

Useful filters:

- exact phrase
- fuzzy search
- sender/person
- date range
- chat/source
- has photo
- has reaction
- has link
- has attachment

Start simple, but design the structure so filters can be added later.

## Result Card Design

Each search result card should be compact but rich.

Required fields:

- sender avatar
- sender name
- timestamp
- message snippet
- highlighted phrase
- open in chat action

Optional fields:

- reaction count
- attached image thumbnail
- nearby context
- linked hub item references
- “create hub item from this” action

Design style:

- soft rounded cards
- clean spacing
- highlighted matched text
- subtle hover/tap feedback
- clear timestamp
- no dense metadata

## Phrase Stats Design

The phrase stats view should show:

- total occurrences
- number of people who used the phrase
- first known use
- most recent use
- bar chart by person
- top sender
- optional funniest/most reacted instance

Example summary:

Phrase: “Benidorm”

Total mentions: 87  
First said by: Ryan  
Peak activity: March 2025  
Top user: Luke, 31 mentions

## AI Summary Ideas

Future enhancement:

After a search, Hub Bot can generate a small social summary.

Example:

“Benidorm mostly appears around planning the stag trip. Ryan first mentioned it, and most messages happened during the week flights were being discussed.”

Possible summaries:

- what the phrase usually refers to
- when it became popular
- who started it
- who talks about it most
- related events, polls, photos, or hub items
- funny or important moments involving it

This should be optional and clearly separated from raw search results.

## Integration With Hub Items

Search results should be linkable to Hub Items.

Potential actions:

- create item from message
- link message to existing item
- reference message inside an item
- attach search result to an event, poll, idea, or memory
- create a “lore item” from a funny message

Example:

A user searches “Benidorm”, finds the original planning message, and links it to the Benidorm trip event.

## Data Model Considerations

The feature should work with imported Messenger data and native Friend Hub messages.

Important fields:

- message id
- chat id
- sender id
- message body
- timestamp
- reactions
- attachments
- linked media
- imported source metadata
- normalised searchable text

Search indexing should support:

- case-insensitive search
- exact phrase search
- basic fuzzy matching
- sender filtering
- date filtering
- pagination
- efficient counts by sender

## Backend API Ideas

Possible endpoints:

GET /api/v1/group-lore/search

Query params:

- q
- mode
- sender_id
- date_from
- date_to
- exact
- limit
- offset

Returns matching message candidates.

GET /api/v1/group-lore/stats

Query params:

- q
- date_from
- date_to
- exact

Returns phrase occurrence stats by person.

GET /api/v1/group-lore/timeline

Query params:

- q
- date_from
- date_to
- bucket

Returns mentions over time.

## Frontend Components

Suggested components:

- GroupLorePage
- GroupLoreSearchBar
- GroupLoreFilters
- GroupLoreTabs
- MessageResultCard
- PhraseStatsChart
- TimelineChart
- EmptySearchState
- SearchLoadingState
- SearchErrorState
- OpenInChatButton

## Empty States

Before searching:

“Search the group memory.”

Subtext:

“Find old jokes, forgotten plans, receipts, and legendary messages.”

No results:

“No lore found for this one.”

Subtext:

“Try a shorter phrase, another spelling, or search by person.”

## Performance Requirements

- Debounce search input
- Avoid loading huge result sets at once
- Paginate results
- Lazy-load surrounding chat context only when opening a result
- Cache recent searches locally
- Use database indexes for message body, sender, and timestamp
- Avoid expensive full scans where possible

## Privacy and Safety

This page can surface old messages, so it should feel respectful.

Consider:

- only visible to authorised chat members
- imported messages should keep source metadata
- deleted/archived messages should not appear unless intended
- respect future privacy settings
- avoid AI summaries for sensitive searches unless explicitly requested

## Future Ideas

- “Who said it first?”
- “Most quoted messages”
- “Most reacted messages”
- “Phrase of the week”
- “Group catchphrases”
- “Lore timeline”
- “Receipts mode”
- “Random memory”
- “On this day”
- “Create memory card”
- “Share result back to chat”
- “Pin as group lore”
- “AI explain this in-joke”

## Success Criteria

The feature is successful if users can:

- quickly find old messages
- jump directly to the message in chat
- see who uses a phrase most
- rediscover funny or meaningful moments
- link old chat history to current hub items
- use the page for both practical search and entertainment

The final experience should feel like the searchable memory of the friend group.