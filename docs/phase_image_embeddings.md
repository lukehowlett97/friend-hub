# Phase: Image Embeddings & Photo Search

## Goal

Add a local, no-paid-API image understanding layer to Friend Hub so imported Messenger photos can become searchable.

At MVP stage, this must not depend on paid external APIs. The system should run using:

- Existing VPS
- Existing PostgreSQL database
- Local image storage / mounted volume
- Optional local GPU worker on development machine for batch embedding
- Open-source models only

This phase should sit parallel to the Messenger importer because Messenger imports are expected to be the main initial source of images.

---

## Core Idea

Messenger importer brings in:

- messages
- participants
- timestamps
- attachments
- photos

Image embeddings phase then processes imported images into searchable metadata:

- image embedding vector
- optional text caption
- optional object/style tags
- source message link
- source conversation link
- import batch link
- searchable timestamp/context

The image pipeline should not block the Messenger import itself.

---

## Proposed Architecture

```text
Messenger Importer
  -> imports messages
  -> saves image files
  -> creates photo records
  -> queues photo_embedding_jobs

Image Embedding Worker
  -> reads pending jobs
  -> loads image file
  -> generates OpenCLIP image embedding
  -> optionally generates lightweight tags/caption
  -> stores embedding + metadata
  -> marks job complete

Search API
  -> user enters text query
  -> query is embedded using same CLIP model
  -> pgvector cosine search against photo embeddings
  -> returns matching photos with source context
```

---

## Non-Goals For MVP

Do not add:

- paid image generation APIs
- paid image classification APIs
- cloud-hosted vector databases
- complex face recognition
- identity recognition
- automatic moderation decisions
- advanced albums
- full AI photo chat

This phase is just about making imported images searchable.

---

## MVP User Stories

### 1. Search imported photos by text

User can search:

```text
camping
beach
pub night
group photo
snow
birthday
food
dog
people around a table
```

The app returns visually relevant photos.

---

### 2. Open the source message

Each result should link back to:

- original message
- chat/conversation
- approximate timestamp
- sender/uploader if known

---

### 3. Filter by context

MVP filters:

- conversation
- date range
- sender
- import batch
- has embedding / missing embedding

---

### 4. Re-run failed embeddings

Admin/dev can requeue failed jobs without re-importing Messenger data.

---

## Data Model

### `photos`

Represents an imported or uploaded image.

Suggested fields:

```text
id UUID primary key
source_type text not null
source_id UUID null
conversation_id UUID null
message_id UUID null
import_batch_id UUID null

storage_path text not null
original_filename text null
content_type text null
file_size_bytes integer null
width integer null
height integer null

taken_at timestamptz null
created_at timestamptz not null
updated_at timestamptz not null
```

Example `source_type` values:

```text
messenger_import
chat_upload
event_upload
manual_upload
```

---

### `photo_embeddings`

Stores the searchable vector.

For OpenCLIP ViT-B-32, embedding size is usually `512`.

```text
id UUID primary key
photo_id UUID not null references photos(id) on delete cascade

model_name text not null
model_version text not null
embedding vector(512) not null

caption text null
tags jsonb not null default '[]'

created_at timestamptz not null
updated_at timestamptz not null
```

Recommended unique constraint:

```text
unique(photo_id, model_name, model_version)
```

---

### `photo_embedding_jobs`

Tracks async processing.

```text
id UUID primary key
photo_id UUID not null references photos(id) on delete cascade

status text not null
attempt_count integer not null default 0
last_error text null

created_at timestamptz not null
started_at timestamptz null
completed_at timestamptz null
updated_at timestamptz not null
```

Statuses:

```text
pending
processing
completed
failed
skipped
```

---

## PostgreSQL / pgvector

Enable `pgvector`.

Migration should include:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

Create vector index after enough data exists:

```sql
CREATE INDEX IF NOT EXISTS idx_photo_embeddings_embedding
ON photo_embeddings
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);
```

For very small datasets, exact search is fine without an index.

---

## Model Choice

MVP model:

```text
OpenCLIP ViT-B-32
```

Reasons:

- open-source
- good enough for semantic image search
- lightweight
- works for both image embeddings and text query embeddings
- can run locally
- avoids paid APIs

Possible pretrained weights:

```text
laion2b_s34b_b79k
```

Later upgrade options:

```text
ViT-L-14
SigLIP
BLIP captioning
local LLaVA-style captioning
```

---

## Local GPU Plan

The user has an AMD RX 6600 XT.

MVP should support two execution modes:

### Mode 1: VPS CPU worker

Simpler deployment.

Pros:

- runs where the app already lives
- no local machine needed
- easy operational model

Cons:

- slower
- may be too heavy during imports

Useful for small batches.

---

### Mode 2: Local GPU batch worker

Preferred for big Messenger imports.

Pros:

- uses local GPU
- avoids VPS resource pressure
- no paid services
- good for one-off historical imports

Cons:

- requires local setup
- needs access to imported image files or exported batch
- results must sync back to VPS/database

The architecture should allow this without changing the main app.

---

## Recommended MVP Flow

### Messenger import

When Messenger importer finds an image attachment:

1. Copy image into app storage.
2. Create `photos` row.
3. Link `photos.message_id`.
4. Create `photo_embedding_jobs` row with `pending` status.

The importer should not run the model directly.

---

### Embedding worker

Worker loop:

1. Claim pending job.
2. Mark as `processing`.
3. Load image from `storage_path`.
4. Generate image embedding.
5. Store row in `photo_embeddings`.
6. Mark job as `completed`.

On failure:

1. Increment `attempt_count`.
2. Save `last_error`.
3. Mark as `failed` after max retries.
4. Otherwise return to `pending`.

---

## Backend Modules

Suggested structure:

```text
backend/app/photos/
  models.py
  schemas.py
  repository.py
  service.py
  routes.py

backend/app/image_embeddings/
  clip_model.py
  embedding_service.py
  embedding_repository.py
  job_repository.py
  worker.py
  routes.py

backend/app/messenger_importer/
  importer.py
  attachment_service.py
```

The Messenger importer should only depend on the photo service and job creation.

It should not depend on CLIP/OpenCLIP directly.

---

## API Endpoints

### Search photos

```http
GET /api/v1/photos/search?q=camping&limit=30
```

Local example:

```bash
curl -H "Authorization: Bearer $FRIEND_HUB_TOKEN" \
  "http://localhost:8000/api/v1/photos/search?q=camping&limit=12"
```

Returns:

```json
{
  "query": "camping",
  "limit": 30,
  "results": [
    {
      "photo_id": "...",
      "score": 0.83,
      "image_url": "...",
      "caption": null,
      "tags": [],
      "message_id": "...",
      "conversation_id": "...",
      "import_batch_id": "...",
      "created_at": "..."
    }
  ]
}
```

Production similarity search requires `pgvector` and a vector-backed
`photo_embeddings.embedding` column. Development/test environments without
pgvector should return an explicit “vector search unavailable” service error
rather than silently returning misleading results.

The first implementation exposes the backend API only. A frontend photo-search
tab can be added to the existing Search page later, reusing this endpoint.

Frontend MVP status:

- The existing Search page has a Photos tab that calls `/api/v1/photos/search`.
- Users can search by natural language, filter by date range and source type,
  view results in a responsive grid, and open a photo preview modal.
- Source message/chat context is shown when the backend provides it.
- Current limitations: no conversation picker yet, no import batch picker, no
  screenshot fixtures, and no combined “All” search that automatically runs
  CLIP photo search for every text query.

Next frontend phase suggestions:

- Add a conversation/import-batch filter backed by real metadata.
- Show embedding-job health near the Photos tab for admins.
- Add image-search screenshots to the project docs once sample data exists.

---

### Requeue failed jobs

Admin-only/dev-only:

```http
POST /api/v1/image-embeddings/jobs/requeue-failed
```

---

### Job status

```http
GET /api/v1/image-embeddings/jobs/status
```

Returns:

```json
{
  "pending": 120,
  "processing": 1,
  "completed": 5320,
  "failed": 12,
  "skipped": 3
}
```

---

## Search Logic

Text query search:

1. Embed the user query with the same CLIP model.
2. Compare against stored image embeddings.
3. Return nearest photos by cosine distance.

Example SQL:

```sql
SELECT
    p.id,
    p.storage_path,
    pe.caption,
    pe.tags,
    1 - (pe.embedding <=> :query_embedding) AS score
FROM photo_embeddings pe
JOIN photos p ON p.id = pe.photo_id
ORDER BY pe.embedding <=> :query_embedding
LIMIT :limit;
```

---

## MVP Frontend

Add a photo search page or extend existing search.

Suggested UI:

```text
Search input:
  "camping in Wales"

Filters:
  conversation
  date range
  sender/import source

Results:
  responsive photo grid
  similarity score hidden by default
  click opens image modal
  modal links to source message
```

---

## Privacy / Safety

For MVP:

- Do not identify people by name from image content.
- Do not run face recognition.
- Do not infer sensitive attributes.
- Do not send images to third-party APIs.
- Keep all processing local.
- Make it clear that search is approximate.

Allowed examples:

```text
group photo
dog
camping
beer
beach
mountains
food
```

Avoid:

```text
identify this person
is this person drunk
is this person ill
what ethnicity is this person
```

---

## Storage Notes

For MVP, image files can live on the VPS filesystem.

Suggested path:

```text
/storage/photos/{source_type}/{import_batch_id}/{photo_id}.jpg
```

Later this can move to S3/R2-compatible storage without changing the embedding model.

---

## Configuration

Example environment variables:

```env
IMAGE_EMBEDDINGS_ENABLED=true
IMAGE_EMBEDDINGS_MODEL_NAME=ViT-B-32
IMAGE_EMBEDDINGS_MODEL_VERSION=laion2b_s34b_b79k
IMAGE_EMBEDDINGS_DEVICE=auto
IMAGE_EMBEDDINGS_BATCH_SIZE=16
IMAGE_EMBEDDINGS_MAX_RETRIES=3
```

Device options:

```text
auto
cpu
cuda
```

For ROCm PyTorch, AMD GPUs may still appear as `cuda` to PyTorch.

---

## Implementation Steps

### Step 1: Database foundation

Add migrations for:

- `photos`
- `photo_embeddings`
- `photo_embedding_jobs`
- `pgvector` extension

---

### Step 2: Photo records from Messenger import

Update Messenger importer so image attachments create `photos` rows and pending embedding jobs.

---

### Step 3: Local embedding service

Add OpenCLIP wrapper:

```text
clip_model.py
embedding_service.py
```

Responsibilities:

- load model once
- preprocess image
- generate image embedding
- generate text embedding
- normalise vectors

---

### Step 4: Worker

Add a worker command:

```bash
python -m app.image_embeddings.worker
```

Worker should:

- process pending jobs
- handle retries
- log progress
- not crash the main app

---

### Step 5: Search endpoint

Add:

```http
GET /api/v1/photos/search
```

The endpoint should:

- validate query
- embed text
- run pgvector search
- return photo result cards

---

### Step 6: Frontend search UI

Add photo search to the existing search area.

MVP can be simple:

- search bar
- grid of images
- click-to-open modal
- link to source message

---

### Step 7: Admin/dev tools

Add basic job visibility:

- pending count
- failed count
- requeue failed jobs
- requeue missing embeddings

---

## Testing

Backend tests:

- photo row creation
- embedding job creation
- failed job retry
- search endpoint validates empty query
- search endpoint returns ranked results
- Messenger importer creates jobs for image attachments
- non-image attachments do not create image embedding jobs

Model tests should be light.

Do not require OpenCLIP in normal unit tests. Mock the embedding service.

---

## Deployment Notes

MVP deployment should avoid putting heavy model inference inside the web process.

Use either:

```text
backend
postgres
frontend
image-embedding-worker
```

or run the worker manually for imported batches.

For early testing, manual worker is acceptable:

```bash
docker compose exec backend python -m app.image_embeddings.worker
```

Later, add a dedicated worker service.

### Phase 3/4 Worker Command

The local embedding worker is optional and separate from the web app/importer:

```bash
cd backend
IMAGE_EMBEDDINGS_ENABLED=true \
IMAGE_EMBEDDINGS_DEVICE=cpu \
python -m app.domains.image_embeddings.worker --once --limit 100
```

Optional worker-only dependencies:

```bash
pip install torch open_clip_torch Pillow
```

The normal backend startup and unit tests should not require `torch` or
`open_clip_torch`; those imports are lazy and happen only when the worker
actually embeds an image.

For local GPU runs:

```bash
IMAGE_EMBEDDINGS_ENABLED=true \
IMAGE_EMBEDDINGS_DEVICE=cuda \
python -m app.domains.image_embeddings.worker --once --limit 500
```

With ROCm PyTorch, AMD GPUs may still be exposed to PyTorch as `cuda`. Keep the
web process and embedding worker as separate processes or services so imports
and normal API requests never run model inference inline.

---

## Success Criteria

This phase is complete when:

- Messenger image imports create photo records.
- Each image gets a pending embedding job.
- Worker can process jobs locally with OpenCLIP.
- Embeddings are stored in Postgres using pgvector.
- User can search photos using text.
- Search results link back to source messages.
- No paid external APIs are required.
- Main chat/import flow remains responsive.

---

## Future Enhancements

After MVP:

- local captioning model
- automatic album/event grouping
- image-to-image search
- duplicate photo detection
- “photos from this event” smart collections
- group memory from selected photos
- AI-generated recap cards
- background batch import progress UI
- R2/S3 image storage
- thumbnail generation
- NSFW/moderation model if needed
