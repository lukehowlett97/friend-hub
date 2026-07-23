# Phase: Facebook Messenger Importer

## Goal

Create a robust Facebook Messenger import system for Friend Hub that can:

- Import historical Messenger group chats
- Preserve messages, reactions, media, timestamps, and participants
- Convert Messenger exports into Friend Hub's native internal schema
- Make imported history feel completely native inside the app
- Support future enrichment such as AI tagging, semantic search, and face recognition

The importer should be designed as a reusable ingestion pipeline rather than a one-off script.

---

# Core Objectives

The importer must:

- Accept a full Facebook export zip
- Locate Messenger chat folders automatically
- Allow selecting a specific chat/group
- Parse all message JSON files
- Extract:
  - messages
  - participants
  - reactions
  - photos
  - GIFs
  - videos
  - shared links
  - timestamps
  - poll/system messages
- Preserve chronological ordering
- Import media into Friend Hub storage
- Insert all data into PostgreSQL
- Preserve original timestamps
- Preserve sender identities
- Preserve reactions
- Support extremely large chats

---

# Important Design Principles

## Imported History Should Feel Native

Imported messages must become standard Friend Hub messages.

Avoid:

- special legacy UI
- archive-only rendering
- separate imported chat mode

Instead:

- convert Messenger data into Friend Hub's internal schema
- render using normal chat components

The user experience should feel like the group always existed inside Friend Hub.

---

## Import And Enrichment Must Be Separate

Importing and AI processing are different stages.

Import pipeline responsibilities:

- parse
- normalise
- insert
- store media

Enrichment responsibilities:

- image classification
- semantic embeddings
- face detection
- tagging
- clustering
- search indexing

This separation is critical for maintainability and debugging.

---

# Expected Facebook Export Structure

Facebook exports a very large nested archive.

Example:

your_facebook_activity/
messages/
inbox/
nipscrips_3103416529741799/
message_1.json
message_2.json
photos/
gifs/
videos/

The importer must recursively discover chats automatically.

---

# Messenger Data Characteristics

Observed fields from sample export:

- participants
- messages
- sender_name
- timestamp_ms
- content
- reactions
- photos
- gifs
- share
- creation_timestamp

Example message types:

- text messages
- photo messages
- GIF messages
- reactions
- shared links
- poll events
- system messages
- AI messages
- attachment messages

---

# Encoding Issues

Messenger exports contain mojibake/unicode corruption.

Examples:

- Youâ€™ve
- Iâ€™m

The importer must include automatic text normalisation and encoding repair.

Create:

encoding.py

Responsibilities:

- repair mojibake
- normalise unicode
- strip invalid control characters
- preserve emojis

---

# Proposed Architecture

backend/app/importers/facebook_messenger/

Modules:

- discovery.py
- parser.py
- normalise.py
- encoding.py
- media.py
- importer.py
- models.py
- cli.py

---

# Discovery Stage

Responsibilities:

- unzip export
- recursively search inbox folders
- identify Messenger chats
- detect available participants
- estimate message counts
- identify media availability

Desired output:

[
  {
    "chat_name": "Nips & Crips",
    "participant_count": 23,
    "message_count": 154321,
    "path": "...",
    "has_media": true
  }
]

---

# Chat Selection

User should be able to:

- select by chat name
- fuzzy search
- import all chats
- preview participants before import

Potential future UI:

- admin importer page
- import wizard
- progress view

---

# Parser Stage

Responsibilities:

- load all message JSON files
- merge message arrays
- preserve raw metadata
- sort chronologically
- identify message types
- validate structure

Important:

Facebook splits large chats into multiple files.

The parser must merge all chunks into a single ordered stream.

---

# Normalisation Stage

Convert Facebook-specific data into Friend Hub internal models.

Example internal message shape:

{
  "room_id": "...",
  "sender_id": "...",
  "body": "...",
  "sent_at": "...",
  "source_provider": "facebook_messenger",
  "source_message_id": "...",
  "metadata": {}
}

---

# Identity Mapping

Messenger only stores sender names.

Need mapping system:

Facebook name
→ Friend Hub user ID

Create:

external_identities table

Example:

{
  "provider": "facebook_messenger",
  "external_name": "Luke Howlett",
  "user_id": "..."
}

Unknown users should be stored safely until resolved.

---

# Media Import Pipeline

Supported media:

- photos
- GIFs
- videos
- audio
- stickers

Media should:

- be copied into Friend Hub storage
- generate thumbnails
- preserve original filenames
- preserve timestamps where possible

Suggested structure:

storage/imports/facebook/<batch_id>/photos/

Never store raw binaries in PostgreSQL.

Only store metadata in DB.

---

# Reactions

Messenger reactions should become native Friend Hub reactions.

Example:

{
  "emoji": "😂",
  "reactor_id": "...",
  "message_id": "..."
}

Support:

- multiple reactions
- duplicate emoji reactions
- unknown reactors

---

# Poll And System Messages

Messenger exports poll activity as plain text.

Examples:

- voted for "6th September"
- created a poll

These should initially import as system messages.

Future enhancement:

- reconstruct native polls

---

# Import Batch Tracking

Create:

import_batches table

Fields:

- id
- provider
- started_at
- completed_at
- status
- message_count
- media_count
- error_count
- imported_by_user_id

Purpose:

- observability
- resumability
- debugging
- progress tracking

---

# Large Chat Performance

Requirements:

- stream parsing where possible
- avoid loading all media into memory
- chunk DB inserts
- support 100k+ messages
- support multi-GB exports

Potential optimisations:

- async media copy
- bulk inserts
- parallel thumbnail generation

---

# Idempotency

Re-importing should not duplicate messages.

Need deterministic import keys.

Possible strategy:

hash(
  sender_name +
  timestamp_ms +
  content
)

Store:

source_message_hash

---

# CLI Design

Initial implementation should be CLI-first.

Example flow:

friend-hub-import discover export.zip

friend-hub-import preview nipscrips_3103416529741799

friend-hub-import import nipscrips_3103416529741799

friend-hub-import enrich-images

friend-hub-import detect-faces

---

# Image Enrichment Pipeline

Separate post-import pipeline.

Goals:

- image classification
- object detection
- semantic search
- face clustering

Potential local models:

- OpenCLIP
- YOLO
- BLIP
- InsightFace

Outputs:

- image tags
- captions
- detected objects
- face embeddings

---

# Future Features Enabled

Once imported:

- semantic search
- friendship graphs
- message analytics
- memory timelines
- AI summaries
- media galleries
- yearly recaps
- quote search
- face-based search
- "photos with X"
- meme detection
- event reconstruction

---

# Security Considerations

Messenger exports contain highly sensitive private data.

Requirements:

- local-first processing
- avoid third-party APIs
- secure temporary storage
- cleanup temp directories
- configurable retention policy

Potential future feature:

encrypted media storage

---

# Recommended Implementation Order

## Phase 1

- discovery
- parser
- DB insertion
- text messages only

## Phase 2

- reactions
- media import
- thumbnails

## Phase 3

- identity mapping
- admin tooling
- import tracking

## Phase 4

- image enrichment
- embeddings
- semantic search

## Phase 5

- face clustering
- AI memory systems
- advanced analytics

---

# Success Criteria

The importer is successful when:

- historical chats import cleanly
- media renders correctly
- timestamps are preserved
- reactions work normally
- imported history feels native
- users can scroll seamlessly through years of chat history
- large imports complete reliably
- imports are repeatable and debuggable