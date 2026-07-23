# Phase: Topic / Conversation Detection

## Goal

Add topic and conversation detection to Friend Hub so messages can be grouped into meaningful conversation threads using a combination of:

* existing chat embeddings
* message timing
* participant activity
* optional LLM refinement
* backfilled historical processing

The aim is to turn raw chat history into a navigable timeline of what the group talked about, when it happened, who was involved, and what was decided.

This should support:

* daily timelines
* room history
* better `/summarise`
* better `/search`
* topic-based browsing
* recurring topic detection over time

---

## Core Concept

Messages should be grouped into **topic instances**.

A topic instance is a bounded conversation chunk, for example:

```text
Saturday pub plans
2026-06-21 18:30 → 19:10
42 messages
Participants: Luke, Harrison, Ben
Tags: pub, plans, Saturday
Summary: The group discussed whether to go out on Saturday, where to meet, and who was coming.
```

Over time, topic instances can also be linked into recurring **conversation topics**, for example:

```text
Camping trip planning
Appeared across 6 days
First seen: 2026-05-12
Last seen: 2026-06-02
```

This allows both:

1. a daily timeline of conversations
2. a longer-term room memory of recurring subjects

---

## Data Model

### `conversation_topic_instances`

Represents one detected conversation/topic chunk.

```sql
CREATE TABLE conversation_topic_instances (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    room_id UUID NOT NULL REFERENCES rooms(id),

    title TEXT,
    summary TEXT,
    tags TEXT[] DEFAULT '{}',

    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ NOT NULL,

    message_count INTEGER NOT NULL DEFAULT 0,
    participant_ids UUID[] DEFAULT '{}',

    embedding VECTOR(512),

    confidence DOUBLE PRECISION,
    detection_method TEXT NOT NULL DEFAULT 'semantic_llm',

    topic_id UUID NULL REFERENCES conversation_topics(id),

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### `conversation_topic_instance_messages`

Links messages to detected topic instances.

```sql
CREATE TABLE conversation_topic_instance_messages (
    topic_instance_id UUID NOT NULL REFERENCES conversation_topic_instances(id) ON DELETE CASCADE,
    message_id UUID NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,

    PRIMARY KEY (topic_instance_id, message_id)
);
```

### `conversation_topics`

Represents recurring topics across multiple days.

```sql
CREATE TABLE conversation_topics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    room_id UUID NOT NULL REFERENCES rooms(id),

    canonical_title TEXT NOT NULL,
    description TEXT,
    tags TEXT[] DEFAULT '{}',

    embedding VECTOR(512),

    first_seen_at TIMESTAMPTZ,
    last_seen_at TIMESTAMPTZ,

    instance_count INTEGER NOT NULL DEFAULT 0,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

---

## Detection Strategy

This should not be purely time-based.

Time is useful, but only as a supporting signal. Group chats often have multiple overlapping conversations, jokes, side comments, and repeated topics across a day.

The detector should use a hybrid approach:

```text
messages
→ embeddings
→ candidate semantic groups
→ time/participant scoring
→ LLM refinement
→ stored topic instances
→ optional recurring topic linking
```

---

## Phase 1: Backfill Topic Instances Per Day

Start by processing one room/day at a time.

For each room and date:

1. fetch all messages for the day
2. fetch existing chat embeddings
3. build candidate groups
4. refine with LLM
5. store topic instances
6. link messages to topic instances

This allows old messages to be backdated into historical timeline entries.

Example worker job:

```text
topic_detection_backfill
room_id: ...
date: 2026-06-21
```

---

## Candidate Grouping

Candidate grouping should use embeddings first.

Useful signals:

* cosine similarity between message embeddings
* similarity to recent message window
* similarity to current topic centroid
* time gap from previous message
* same active participants
* reply/message reference, if available
* media/photo proximity
* message density

Basic boundary logic:

```python
def should_start_new_candidate(
    similarity_to_recent_window: float,
    minutes_since_previous: float,
    hard_gap_minutes: int = 120,
    soft_gap_minutes: int = 20,
    semantic_threshold: float = 0.55,
) -> bool:
    """Return whether a message may start a new topic candidate."""

    if minutes_since_previous >= hard_gap_minutes:
        return True

    if (
        minutes_since_previous >= soft_gap_minutes
        and similarity_to_recent_window < semantic_threshold
    ):
        return True

    if similarity_to_recent_window < 0.40:
        return True

    return False
```

The exact thresholds should be tuned after testing on real rooms.

---

## Handling Overlapping Conversations

A single time window may contain more than one conversation.

Example:

```text
18:00 football result
18:02 pub plans
18:03 football joke
18:05 pub logistics
18:06 football again
```

A pure time split would fail here.

The detector should allow multiple semantic groups inside the same time window.

Approach:

1. split messages into rough windows
2. cluster by embedding similarity within the day
3. preserve message order inside each cluster
4. ask the LLM to merge/split/refine the candidate groups

---

## LLM Refinement

After candidate groups are produced, pass compact candidate data to the LLM.

The LLM should:

* merge groups that are clearly the same conversation
* split groups that contain unrelated topics
* produce a short title
* produce a concise summary
* assign tags
* identify key participants
* assign confidence
* mark vague/general chat as low confidence

Example output shape:

```json
{
  "topics": [
    {
      "title": "Saturday pub plans",
      "summary": "The group discussed whether to go out on Saturday, where to meet, and who was coming.",
      "tags": ["pub", "plans", "Saturday"],
      "message_ids": ["..."],
      "confidence": 0.91
    }
  ]
}
```

The LLM should not invent conclusions. If a topic is unclear, it should use a generic title such as:

```text
General chat
```

or:

```text
Jokes and side comments
```

---

## Recurring Topic Linking

Once topic instances exist, link them to broader recurring topics.

For each new topic instance:

1. compare its embedding to existing `conversation_topics` in the same room
2. if similarity is above threshold, link it
3. otherwise create a new recurring topic
4. update `first_seen_at`, `last_seen_at`, and `instance_count`

Example:

```text
Topic instance: "Who is bringing tents?"
Recurring topic: "Camping trip planning"
```

This can be done after initial MVP.

---

## Worker Design

Topic detection should run outside the main request path.

Suggested job types:

```text
topic_detection_backfill_day
topic_detection_backfill_range
topic_detection_reprocess_day
topic_detection_reprocess_room
topic_detection_label_instance
topic_detection_link_recurring_topic
```

The worker should be idempotent.

For a given `room_id` and date, it should be safe to delete/recreate topic instances, or version them if needed.

Possible processing state table:

```sql
CREATE TABLE topic_detection_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    room_id UUID NOT NULL REFERENCES rooms(id),
    target_date DATE NOT NULL,

    status TEXT NOT NULL DEFAULT 'pending',
    error TEXT,

    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (room_id, target_date)
);
```

---

## Timeline UI

Add a room-level timeline view.

Example:

```text
Today

09:12 — Job chat
32 messages · 4 people

12:48 — Lunch photos
18 messages · 3 people · 5 photos

18:30 — Saturday pub plans
42 messages · 6 people

21:05 — Football jokes
66 messages · 5 people
```

Each topic should be clickable.

Topic detail page/modal:

* title
* summary
* time range
* participants
* tags
* linked photos/media
* message list
* related topics
* recurring topic link

---

## Search Integration

Search should be able to return both:

1. individual messages
2. matched topic instances

Example:

```text
Matched topic: Camping trip planning
6 topic instances · 182 messages · 9 photos
```

This allows questions like:

```text
What did we decide about camping?
```

to retrieve the whole conversation context rather than isolated messages.

---

## Topic Metrics And Engagement Signals

Once topic instances can be browsed and opened reliably, compute lightweight
metrics for each stored topic. These metrics should help the app identify
funny highlights, unusually active chats, photo-heavy moments, and likely
planning/event conversations without asking an LLM to infer everything from
text alone.

Useful derived fields:

* `message_count`
* `participant_count`
* `reaction_count`
* `unique_reactor_count`
* `top_reactions`, for example `{ "😂": 12, "❤️": 4 }`
* `photo_count`
* `gif_count`
* `link_count`
* `reply_count`
* `burst_score`, based on message density in the topic window
* `funny_score`, based on laugh reactions, reply bursts, and high engagement
* `planning_score`, based on planning terms, event-like tags, and logistics

Store these either on `chat_topics` or in a separate metrics table. A separate
table is preferable while the metrics are still evolving:

```sql
CREATE TABLE chat_topic_metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    topic_id UUID NOT NULL REFERENCES chat_topics(id) ON DELETE CASCADE,
    room_id UUID NOT NULL REFERENCES rooms(id),

    message_count INTEGER NOT NULL DEFAULT 0,
    participant_count INTEGER NOT NULL DEFAULT 0,
    reaction_count INTEGER NOT NULL DEFAULT 0,
    unique_reactor_count INTEGER NOT NULL DEFAULT 0,

    top_reactions JSONB NOT NULL DEFAULT '{}'::jsonb,

    photo_count INTEGER NOT NULL DEFAULT 0,
    gif_count INTEGER NOT NULL DEFAULT 0,
    link_count INTEGER NOT NULL DEFAULT 0,
    reply_count INTEGER NOT NULL DEFAULT 0,

    burst_score DOUBLE PRECISION,
    funny_score DOUBLE PRECISION,
    planning_score DOUBLE PRECISION,

    computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (topic_id)
);
```

Metrics should be recomputed from the messages covered by each topic segment.
When topic detection replaces topics for a date/version, the related metrics
should be recreated as well. A safe CLI command should also exist for
recomputing metrics without reclustering:

```bash
python -m app.domains.topic_detection.worker \
  --room-id <uuid> \
  --date-from 2020-09-01 \
  --date-to 2020-09-30 \
  --recompute-topic-metrics
```

The timeline UI can then show subtle cues:

```text
42 msgs · 8 people · 😂 14 · 3 photos
```

Later discovery views can use the same metrics:

* funniest topics
* most reacted topics
* most active topics
* photo-heavy topics
* likely plans/events

Metrics should also be available to LLM refinement as compact context:

```text
Engagement:
- 38 messages
- 9 participants
- 22 reactions
- top reactions: 😂 14, ❤️ 3
- 4 photos
```

This helps distinguish a funny highlight chat from ordinary general chat, and
helps identify planned events or nights out without relying only on wording.

---

## Summary Integration

`/summarise` should use topic instances where available.

Instead of summarising raw messages directly, it can first collect topic instances in the requested time range.

Example:

```text
/summarise 24h
```

Could return:

```text
There were 5 main conversations:

1. Saturday pub plans
2. World Cup chat
3. Camping logistics
4. New photos from last night
5. General jokes and memes
```

This should improve summary quality and reduce token usage.

---

## API Ideas

### Get daily timeline

```http
GET /rooms/:roomId/topics/timeline?date=2026-06-21
```

### Get topic instance

```http
GET /rooms/:roomId/topics/instances/:topicInstanceId
```

### Get recurring topics

```http
GET /rooms/:roomId/topics
```

### Reprocess day

```http
POST /rooms/:roomId/topics/reprocess
```

Body:

```json
{
  "date": "2026-06-21"
}
```

### Backfill range

```http
POST /rooms/:roomId/topics/backfill
```

Body:

```json
{
  "startDate": "2026-01-01",
  "endDate": "2026-06-21"
}
```

---

## MVP Scope

The first version should include:

* database tables for topic instances
* message-to-topic linking table
* daily backfill worker
* semantic candidate grouping using existing embeddings
* LLM labelling/refinement
* basic daily timeline endpoint
* simple UI showing topic cards per day

Do not start with recurring topics unless the instance-level timeline is working well.

---

## Later Enhancements

Possible later improvements:

* recurring topic clustering
* topic search
* topic-based `/summarise`
* topic metrics and engagement-based highlight views
* photo/media attachment to topics
* participant contribution stats
* “this week in the room” recap
* pinned important topic summaries
* manual correction/editing of topic titles
* topic confidence indicators
* reprocessing with improved models
* topic graph visualisation

---

## Risks

### Messy group chat structure

Group chats often contain overlapping conversations. Avoid relying only on time gaps.

### Bad LLM labels

LLM labels may be too generic or may over-interpret. Keep summaries grounded in message IDs.

### Over-fragmentation

Too many tiny topics would make the timeline noisy.

Use minimum message counts and confidence thresholds.

### Under-fragmentation

Large generic chunks like “General chat” are less useful.

Use semantic splitting and LLM refinement to improve this.

### Cost

Backfilling large history with LLM calls may be expensive.

Use embeddings and candidate grouping first, then only send compact candidate chunks to the LLM.

---

## Recommended Build Order

1. Add database tables.
2. Create a daily topic detection worker.
3. Use embeddings to create candidate groups.
4. Use LLM to refine and label those groups.
5. Store topic instances and message links.
6. Add a timeline API.
7. Add basic timeline UI.
8. Add chat anchors/highlighting from topics, search, gallery, stats, and profiles.
9. Add topic search.
10. Add topic metrics and highlight views.
11. Integrate topic instances into `/summarise`.
12. Add recurring topic clustering later.

---

## End Goal

Friend Hub should move from:

```text
searching raw messages
```

to:

```text
browsing group memory
```

The feature should make old conversations feel organised, searchable, and alive.
