import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ["DEBUG"] = "false"

from fastapi import HTTPException

from app.api.v1.photo_search_router import _safe_image_url, search_photos
from app.domains.image_embeddings.clip_model import OpenCLIPRuntimeError
from app.domains.image_embeddings.repository import PhotoEmbeddingJobRepository
from app.domains.image_embeddings.repository import PhotoSearchResult, VectorSearchUnavailableError
from app.domains.image_embeddings.service import ImageEmbeddingSearchError, ImageEmbeddingSearchService, PhotoEmbeddingJobService, embedding_settings
from app.domains.image_embeddings.worker import run_once
from app.models.photo import Photo
from app.models.photo_embedding import PhotoEmbedding, PhotoEmbeddingJob


class TestImageEmbeddingJobs(unittest.IsolatedAsyncioTestCase):
    async def test_status_counts_includes_empty_supported_statuses(self):
        repository = PhotoEmbeddingJobRepository(FakeStatusSession([
            ("pending", 2),
            ("failed", 1),
            ("unknown", 9),
        ]))

        counts = await repository.status_counts()

        self.assertEqual(counts, {
            "pending": 2,
            "processing": 0,
            "completed": 0,
            "failed": 1,
            "skipped": 0,
        })

    async def test_service_processes_pending_job_and_creates_embedding(self):
        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "photo.jpg"
            image_path.write_bytes(b"fake")
            db = FakeEmbeddingSession()
            photo = Photo(
                id=1,
                filename="photo.jpg",
                original_filename="photo.jpg",
                content_type="image/jpeg",
                storage_path=str(image_path),
            )
            job = PhotoEmbeddingJob(id=1, photo_id=1, status="processing", attempt_count=0)
            db.photos.append(photo)
            db.jobs.append(job)

            service = PhotoEmbeddingJobService(
                db,
                embedder=FakeEmbedder([0.1, 0.2, 0.3]),
                settings=embedding_settings(max_retries=3),
            )
            embedding = await service.process_job(job)

            self.assertIsNotNone(embedding)
            self.assertEqual(len(db.embeddings), 1)
            self.assertEqual(db.embeddings[0].embedding, "[0.1,0.2,0.3]")
            self.assertEqual(job.status, "completed")
            self.assertIsNone(job.last_error)

    async def test_service_updates_existing_embedding(self):
        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "photo.jpg"
            image_path.write_bytes(b"fake")
            db = FakeEmbeddingSession()
            db.photos.append(Photo(
                id=1,
                filename="photo.jpg",
                original_filename="photo.jpg",
                content_type="image/jpeg",
                storage_path=str(image_path),
            ))
            existing = PhotoEmbedding(
                id=1,
                photo_id=1,
                model_name="ViT-B-32",
                model_version="test",
                embedding="[0]",
                tags=[],
            )
            db.embeddings.append(existing)
            job = PhotoEmbeddingJob(id=1, photo_id=1, status="processing", attempt_count=0)
            db.jobs.append(job)

            service = PhotoEmbeddingJobService(
                db,
                embedder=FakeEmbedder([0.4, 0.5]),
                settings=embedding_settings(model_version="test", max_retries=3),
            )
            embedding = await service.process_job(job)

            self.assertIsNotNone(embedding)
            self.assertEqual(embedding.photo_id, 1)
            self.assertEqual(embedding.model_name, "ViT-B-32")
            self.assertEqual(embedding.model_version, "test")
            self.assertEqual(embedding.embedding, "[0.4,0.5]")
            self.assertEqual(len(db.embeddings), 1)
            self.assertEqual(job.status, "completed")

    async def test_missing_image_marks_job_failed_without_retry(self):
        db = FakeEmbeddingSession()
        db.photos.append(Photo(
            id=1,
            filename="missing.jpg",
            original_filename="missing.jpg",
            content_type="image/jpeg",
            storage_path="/tmp/does-not-exist-friend-hub.jpg",
        ))
        job = PhotoEmbeddingJob(id=1, photo_id=1, status="processing", attempt_count=0)
        db.jobs.append(job)

        service = PhotoEmbeddingJobService(
            db,
            embedder=FakeEmbedder([0.1]),
            settings=embedding_settings(max_retries=3),
        )
        result = await service.process_job(job)

        self.assertIsNone(result)
        self.assertEqual(job.status, "failed")
        self.assertEqual(job.attempt_count, 1)
        self.assertIn("Image file not found", job.last_error)

    async def test_retryable_failure_increments_attempt_and_requeues(self):
        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "photo.jpg"
            image_path.write_bytes(b"fake")
            db = FakeEmbeddingSession()
            db.photos.append(Photo(
                id=1,
                filename="photo.jpg",
                original_filename="photo.jpg",
                content_type="image/jpeg",
                storage_path=str(image_path),
            ))
            job = PhotoEmbeddingJob(id=1, photo_id=1, status="processing", attempt_count=0)
            db.jobs.append(job)

            service = PhotoEmbeddingJobService(
                db,
                embedder=FailingEmbedder("model failed"),
                settings=embedding_settings(max_retries=3),
            )
            result = await service.process_job(job)

            self.assertIsNone(result)
            self.assertEqual(job.status, "pending")
            self.assertEqual(job.attempt_count, 1)
            self.assertIn("model failed", job.last_error)

    async def test_jobs_at_max_retry_are_marked_failed_and_not_claimed(self):
        db = FakeEmbeddingSession()
        db.jobs.append(PhotoEmbeddingJob(id=1, photo_id=1, status="pending", attempt_count=3))
        service = PhotoEmbeddingJobService(db, embedder=FakeEmbedder([0.1]), settings=embedding_settings(max_retries=3))

        exhausted = await service.mark_exhausted_pending_jobs()
        claimed = await service.claim_pending_jobs(limit=10)

        self.assertEqual(exhausted, 1)
        self.assertEqual(claimed, [])
        self.assertEqual(db.jobs[0].status, "failed")

    async def test_worker_run_once_processes_pending_job_with_mocked_embedder(self):
        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "photo.jpg"
            image_path.write_bytes(b"fake")
            db = FakeEmbeddingSession()
            db.photos.append(Photo(
                id=1,
                filename="photo.jpg",
                original_filename="photo.jpg",
                content_type="image/jpeg",
                storage_path=str(image_path),
            ))
            db.jobs.append(PhotoEmbeddingJob(id=1, photo_id=1, status="pending", attempt_count=0))

            with patch("app.domains.image_embeddings.worker.async_session_factory", return_value=FakeSessionContext(db)), \
                 patch("app.domains.image_embeddings.service.get_settings", return_value=embedding_settings()), \
                 patch("app.domains.image_embeddings.service.OpenCLIPEmbedder", return_value=FakeEmbedder([0.6, 0.8])):
                processed = await run_once(limit=5)

            self.assertEqual(processed, 1)
            self.assertEqual(db.jobs[0].status, "completed")
            self.assertEqual(len(db.embeddings), 1)
            self.assertEqual(db.commit_count, 1)

    def test_clip_model_import_does_not_require_openclip(self):
        sys.modules.pop("open_clip", None)

        from app.domains.image_embeddings.clip_model import OpenCLIPConfig, OpenCLIPEmbedder

        embedder = OpenCLIPEmbedder(OpenCLIPConfig(model_name="ViT-B-32", model_version="test", device="cpu"))
        self.assertEqual(embedder.model_name, "ViT-B-32")
        self.assertNotIn("open_clip", sys.modules)

    def test_image_embedding_migration_has_safe_pgvector_fallback(self):
        migration = Path(__file__).resolve().parents[1] / "migrations" / "034_add_image_embedding_foundation.sql"
        content = migration.read_text(encoding="utf-8")

        self.assertIn("feature_not_supported", content)
        self.assertIn("insufficient_privilege", content)
        self.assertIn("WHEN OTHERS", content)
        self.assertIn("EXECUTE $ddl$", content)
        self.assertIn("embedding TEXT NOT NULL", content)

    async def test_photo_search_calls_text_embedding_and_returns_ranked_results(self):
        repository = FakeSearchRepository([
            PhotoSearchResult(
                photo_id=1,
                storage_path="/uploads/photos/a.jpg",
                original_filename="a.jpg",
                content_type="image/jpeg",
                width=100,
                height=80,
                message_id=10,
                conversation_id="main",
                import_batch_id=2,
                caption=None,
                tags=["camping"],
                score=0.91,
                created_at=None,
            )
        ])
        embedder = FakeEmbedder([0.2, 0.8])
        service = ImageEmbeddingSearchService(
            FakeEmbeddingSession(),
            embedder=embedder,
            embedding_repository=repository,
            settings=embedding_settings(),
        )

        results = await service.search_photos(query=" camping ", limit=30)

        self.assertEqual(embedder.text_queries, ["camping"])
        self.assertEqual(results[0].photo_id, 1)
        self.assertEqual(repository.last_query_embedding, [0.2, 0.8])

    async def test_photo_search_passes_optional_filters_and_clamps_limit(self):
        repository = FakeSearchRepository([])
        service = ImageEmbeddingSearchService(
            FakeEmbeddingSession(),
            embedder=FakeEmbedder([0.1]),
            embedding_repository=repository,
            settings=embedding_settings(),
        )

        await service.search_photos(
            query="snow",
            limit=500,
            conversation_id="main",
            source_type="messenger_import",
            import_batch_id=7,
        )

        self.assertEqual(repository.last_limit, 100)
        self.assertEqual(repository.last_filters["conversation_id"], "main")
        self.assertEqual(repository.last_filters["source_type"], "messenger_import")
        self.assertEqual(repository.last_filters["import_batch_id"], 7)

    async def test_photo_search_missing_ml_dependencies_returns_service_error(self):
        service = ImageEmbeddingSearchService(
            FakeEmbeddingSession(),
            embedder=TextFailingEmbedder(OpenCLIPRuntimeError("missing optional ML dependencies")),
            embedding_repository=FakeSearchRepository([]),
            settings=embedding_settings(),
        )

        with self.assertRaises(ImageEmbeddingSearchError) as raised:
            await service.search_photos(query="beach", limit=10)

        self.assertIn("missing optional ML dependencies", str(raised.exception))

    async def test_photo_search_vector_unavailable_is_explicit(self):
        service = ImageEmbeddingSearchService(
            FakeEmbeddingSession(),
            embedder=FakeEmbedder([0.1]),
            embedding_repository=VectorUnavailableRepository(),
            settings=embedding_settings(),
        )

        with self.assertRaises(ImageEmbeddingSearchError) as raised:
            await service.search_photos(query="beach", limit=10)

        self.assertIn("pgvector", str(raised.exception))

    async def test_photo_search_route_rejects_empty_query(self):
        with patch("app.api.v1.photo_search_router._current_user_or_401", return_value=object()):
            with self.assertRaises(HTTPException) as raised:
                await search_photos(q="   ", authorization="Bearer token", db=FakeEmbeddingSession())

        self.assertEqual(raised.exception.status_code, 400)

    async def test_photo_search_route_payload_and_limit_clamp(self):
        result = PhotoSearchResult(
            photo_id=1,
            storage_path="/uploads/photos/a.jpg",
            original_filename="a.jpg",
            content_type="image/jpeg",
            width=100,
            height=80,
            message_id=10,
            conversation_id="main",
            import_batch_id=2,
            caption=None,
            tags=[],
            score=0.83,
            created_at=None,
        )

        with patch("app.api.v1.photo_search_router._current_user_or_401", return_value=object()), \
             patch("app.api.v1.photo_search_router.ImageEmbeddingSearchService", return_value=FakeRouteSearchService([result])) as service_cls:
            payload = await search_photos(q="camping", limit=500, authorization="Bearer token", db=FakeEmbeddingSession())

        self.assertEqual(payload["limit"], 100)
        self.assertEqual(payload["results"][0]["image_url"], "/uploads/photos/a.jpg")
        self.assertEqual(payload["results"][0]["message_id"], "10")
        self.assertEqual(service_cls.return_value.last_kwargs["limit"], 100)

    async def test_photo_search_route_returns_503_for_service_error(self):
        with patch("app.api.v1.photo_search_router._current_user_or_401", return_value=object()), \
             patch("app.api.v1.photo_search_router.ImageEmbeddingSearchService", return_value=FailingRouteSearchService("Vector search unavailable")):
            with self.assertRaises(HTTPException) as raised:
                await search_photos(q="camping", limit=30, authorization="Bearer token", db=FakeEmbeddingSession())

        self.assertEqual(raised.exception.status_code, 503)
        self.assertIn("Vector search unavailable", raised.exception.detail)

    def test_raw_local_filesystem_paths_are_not_leaked(self):
        self.assertIsNone(_safe_image_url("/private/storage/a.jpg"))
        self.assertEqual(_safe_image_url("/uploads/photos/a.jpg"), "/uploads/photos/a.jpg")


class FakeStatusSession:
    def __init__(self, rows):
        self.rows = rows

    async def execute(self, stmt):
        return FakeRows(self.rows)


class FakeRows:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows

    def scalar_one_or_none(self):
        return self.rows[0] if self.rows else None

    def scalar_one(self):
        return self.rows[0]

    def scalars(self):
        return self

    def mappings(self):
        return self

    def keys(self):
        return []


class FakeEmbeddingSession:
    def __init__(self):
        self.photos = []
        self.jobs = []
        self.embeddings = []
        self.added = []
        self.flush_count = 0
        self.commit_count = 0
        self._next_embedding_id = 1

    def add(self, obj):
        self.added.append(obj)
        if isinstance(obj, PhotoEmbedding):
            obj.id = self._next_embedding_id
            self._next_embedding_id += 1
            self.embeddings.append(obj)

    async def flush(self):
        self.flush_count += 1

    async def commit(self):
        self.commit_count += 1

    async def execute(self, stmt, params=None):
        # Handle raw text() SQL used by upsert_embedding
        if not hasattr(stmt, "column_descriptions"):
            # text() call — handle INSERT INTO photo_embeddings ... ON CONFLICT ... RETURNING id
            embedding = PhotoEmbedding(
                id=self._next_embedding_id,
                photo_id=params.get("photo_id"),
                model_name=params.get("model_name"),
                model_version=params.get("model_version"),
                embedding=params.get("embedding"),
                caption=params.get("caption"),
                tags=params.get("tags") or [],
            )
            self._next_embedding_id += 1
            # Remove any existing embedding with same (photo_id, model_name, model_version)
            self.embeddings = [
                e for e in self.embeddings
                if not (
                    e.photo_id == embedding.photo_id
                    and e.model_name == embedding.model_name
                    and e.model_version == embedding.model_version
                )
            ]
            self.embeddings.append(embedding)
            return FakeRows([embedding.id])

        entity = stmt.column_descriptions[0].get("entity")
        filters = _filters(stmt)

        if entity is Photo:
            row = next((photo for photo in self.photos if photo.id == filters.get("id")), None)
            return FakeRows([row] if row else [])

        if entity is PhotoEmbeddingJob:
            if filters.get("status") == "pending":
                max_retries = filters.get("attempt_count", 999999)
                if _attempt_count_operator(stmt) == "ge":
                    rows = [
                        job for job in self.jobs
                        if job.status == "pending" and (job.attempt_count or 0) >= max_retries
                    ]
                else:
                    rows = [
                        job for job in self.jobs
                        if job.status == "pending" and (job.attempt_count or 0) < max_retries
                    ]
            elif "photo_id" in filters:
                rows = [job for job in self.jobs if job.photo_id == filters["photo_id"]]
            else:
                rows = list(self.jobs)
            return FakeRows(rows)

        if entity is PhotoEmbedding:
            row = next((
                embedding for embedding in self.embeddings
                if embedding.photo_id == filters.get("photo_id")
                and embedding.model_name == filters.get("model_name")
                and embedding.model_version == filters.get("model_version")
            ), None)
            return FakeRows([row] if row else [])

        return FakeRows([])

    async def get(self, model, ident):
        return next((e for e in self.embeddings if e.id == ident), None)

    async def rollback(self):
        pass


class FakeSessionContext:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeEmbedder:
    model_name = "ViT-B-32"
    model_version = "test"

    def __init__(self, embedding):
        self.embedding = embedding
        self.text_queries = []

    def embed_image(self, image_path):
        return self.embedding

    def embed_text(self, text):
        self.text_queries.append(text)
        return self.embedding


class FailingEmbedder(FakeEmbedder):
    def __init__(self, message):
        self.message = message

    def embed_image(self, image_path):
        raise RuntimeError(self.message)


class TextFailingEmbedder(FakeEmbedder):
    model_name = "ViT-B-32"
    model_version = "test"

    def __init__(self, exc):
        self.exc = exc
        self.text_queries = []

    def embed_text(self, text):
        self.text_queries.append(text)
        raise self.exc


class FakeSearchRepository:
    def __init__(self, results):
        self.results = results
        self.last_query_embedding = None
        self.last_limit = None
        self.last_filters = {}

    async def search_similar_photos(self, *, query_embedding, limit, **filters):
        self.last_query_embedding = query_embedding
        self.last_limit = limit
        self.last_filters = filters
        return self.results


class VectorUnavailableRepository(FakeSearchRepository):
    def __init__(self):
        super().__init__([])

    async def search_similar_photos(self, **kwargs):
        raise VectorSearchUnavailableError("Vector photo search requires pgvector")


class FakeRouteSearchService:
    def __init__(self, results):
        self.results = results
        self.last_kwargs = None

    async def search_photos(self, **kwargs):
        self.last_kwargs = kwargs
        return self.results


class FailingRouteSearchService:
    def __init__(self, message):
        self.message = message

    async def search_photos(self, **kwargs):
        raise ImageEmbeddingSearchError(self.message)


def _filters(stmt):
    values = {}
    for criterion in getattr(stmt, "_where_criteria", ()):
        left = getattr(criterion, "left", None)
        right = getattr(criterion, "right", None)
        key = getattr(left, "key", None)
        if key:
            values[key] = getattr(right, "value", None)
    return values


def _attempt_count_operator(stmt):
    for criterion in getattr(stmt, "_where_criteria", ()):
        left = getattr(criterion, "left", None)
        if getattr(left, "key", None) == "attempt_count":
            return getattr(getattr(criterion, "operator", None), "__name__", None)
    return None
