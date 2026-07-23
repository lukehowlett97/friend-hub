import json
from datetime import datetime
from dataclasses import dataclass

from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.photo_embedding import PhotoEmbedding, PhotoEmbeddingJob


EMBEDDING_JOB_STATUSES = ("pending", "processing", "completed", "failed", "skipped")


class VectorSearchUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class PhotoSearchResult:
    photo_id: int
    storage_path: str | None
    original_filename: str | None
    content_type: str | None
    width: int | None
    height: int | None
    message_id: int | None
    conversation_id: str | None
    import_batch_id: int | None
    caption: str | None
    tags: list
    score: float
    created_at: datetime | None


class PhotoEmbeddingJobRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_for_photo(self, photo_id: int) -> PhotoEmbeddingJob | None:
        result = await self.db.execute(
            select(PhotoEmbeddingJob).where(PhotoEmbeddingJob.photo_id == photo_id)
        )
        return result.scalar_one_or_none()

    async def create_pending_job(self, photo_id: int) -> PhotoEmbeddingJob:
        existing = await self.get_for_photo(photo_id)
        if existing is not None:
            return existing

        job = PhotoEmbeddingJob(photo_id=photo_id, status="pending")
        self.db.add(job)
        await self.db.flush()
        return job

    async def claim_pending_jobs(self, *, limit: int, max_retries: int) -> list[PhotoEmbeddingJob]:
        if limit <= 0:
            return []
        result = await self.db.execute(
            select(PhotoEmbeddingJob)
            .where(
                PhotoEmbeddingJob.status == "pending",
                PhotoEmbeddingJob.attempt_count < max_retries,
            )
            .order_by(PhotoEmbeddingJob.created_at.asc(), PhotoEmbeddingJob.id.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        jobs = list(result.scalars().all())
        now = datetime.utcnow()
        for job in jobs:
            job.status = "processing"
            job.started_at = now
            job.updated_at = now
            job.last_error = None
        await self.db.flush()
        return jobs

    async def mark_processing(self, job: PhotoEmbeddingJob) -> PhotoEmbeddingJob:
        now = datetime.utcnow()
        job.status = "processing"
        job.started_at = now
        job.updated_at = now
        await self.db.flush()
        return job

    async def mark_completed(self, job: PhotoEmbeddingJob) -> PhotoEmbeddingJob:
        now = datetime.utcnow()
        job.status = "completed"
        job.completed_at = now
        job.updated_at = now
        job.last_error = None
        await self.db.flush()
        return job

    async def mark_failed(
        self,
        job: PhotoEmbeddingJob,
        error: str,
        *,
        max_retries: int,
        retryable: bool = True,
    ) -> PhotoEmbeddingJob:
        now = datetime.utcnow()
        job.attempt_count = (job.attempt_count or 0) + 1
        job.last_error = error[:2000]
        job.updated_at = now
        if retryable and job.attempt_count < max_retries:
            job.status = "pending"
            job.started_at = None
        else:
            job.status = "failed"
            job.completed_at = now
        await self.db.flush()
        return job

    async def mark_exhausted_pending_jobs(self, *, max_retries: int) -> int:
        result = await self.db.execute(
            select(PhotoEmbeddingJob).where(
                PhotoEmbeddingJob.status == "pending",
                PhotoEmbeddingJob.attempt_count >= max_retries,
            )
        )
        jobs = list(result.scalars().all())
        now = datetime.utcnow()
        for job in jobs:
            job.status = "failed"
            job.completed_at = now
            job.updated_at = now
            job.last_error = job.last_error or "Maximum retry count reached"
        await self.db.flush()
        return len(jobs)

    async def status_counts(self) -> dict[str, int]:
        result = await self.db.execute(
            select(PhotoEmbeddingJob.status, func.count(PhotoEmbeddingJob.id))
            .group_by(PhotoEmbeddingJob.status)
        )
        counts = {status: 0 for status in EMBEDDING_JOB_STATUSES}
        for status, count in result.all():
            if status in counts:
                counts[status] = int(count)
        return counts


class PhotoEmbeddingRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_embedding(
        self,
        *,
        photo_id: int,
        model_name: str,
        model_version: str,
    ) -> PhotoEmbedding | None:
        result = await self.db.execute(
            select(PhotoEmbedding).where(
                PhotoEmbedding.photo_id == photo_id,
                PhotoEmbedding.model_name == model_name,
                PhotoEmbedding.model_version == model_version,
            )
        )
        return result.scalar_one_or_none()

    async def upsert_embedding(
        self,
        *,
        photo_id: int,
        model_name: str,
        model_version: str,
        embedding: list[float],
        caption: str | None = None,
        tags: list | None = None,
    ) -> PhotoEmbedding:
        """Insert or update a photo embedding using explicit pgvector casting."""
        result = await self.db.execute(
            text(
                """
                INSERT INTO photo_embeddings (
                    photo_id,
                    model_name,
                    model_version,
                    embedding,
                    caption,
                    tags,
                    created_at,
                    updated_at
                )
                VALUES (
                    :photo_id,
                    :model_name,
                    :model_version,
                    CAST(:embedding AS vector),
                    :caption,
                    CAST(:tags AS jsonb),
                    :created_at,
                    :updated_at
                )
                ON CONFLICT (photo_id, model_name, model_version)
                DO UPDATE SET
                    embedding = EXCLUDED.embedding,
                    caption = EXCLUDED.caption,
                    tags = EXCLUDED.tags,
                    updated_at = EXCLUDED.updated_at
                RETURNING id
                """
            ),
            {
                "photo_id": photo_id,
                "model_name": model_name,
                "model_version": model_version,
                "embedding": _vector_literal(embedding),
                "caption": caption,
                "tags": json.dumps(tags or []),
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            },
        )

        embedding_id = result.scalar_one()

        row = await self.db.get(PhotoEmbedding, embedding_id)
        if row is None:
            raise RuntimeError(f"PhotoEmbedding {embedding_id} was not found after upsert")

        return row

    async def search_similar_photos(
        self,
        *,
        query_embedding: list[float],
        limit: int,
        conversation_id: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        source_type: str | None = None,
        import_batch_id: int | None = None,
    ) -> list[PhotoSearchResult]:
        where = []
        params = {
            "query_embedding": _vector_literal(query_embedding),
            "limit": limit,
        }
        if conversation_id:
            where.append("p.conversation_id = :conversation_id")
            params["conversation_id"] = conversation_id
        if date_from:
            where.append("p.created_at >= :date_from")
            params["date_from"] = date_from
        if date_to:
            where.append("p.created_at <= :date_to")
            params["date_to"] = date_to
        if source_type:
            where.append("p.source_type = :source_type")
            params["source_type"] = source_type
        if import_batch_id is not None:
            where.append("p.import_batch_id = :import_batch_id")
            params["import_batch_id"] = import_batch_id

        where_clause = f"WHERE {' AND '.join(where)}" if where else ""
        stmt = text(f"""
            SELECT
                p.id AS photo_id,
                p.storage_path,
                p.original_filename,
                p.content_type,
                p.width,
                p.height,
                p.message_id,
                p.conversation_id,
                p.import_batch_id,
                pe.caption,
                pe.tags,
                1 - (pe.embedding <=> CAST(:query_embedding AS vector)) AS score,
                p.created_at
            FROM photo_embeddings pe
            JOIN photos p ON p.id = pe.photo_id
            {where_clause}
            ORDER BY pe.embedding <=> CAST(:query_embedding AS vector)
            LIMIT :limit
        """)

        try:
            result = await self.db.execute(stmt, params)
        except SQLAlchemyError as exc:
            raise VectorSearchUnavailableError(
                "Vector photo search requires pgvector and vector-backed photo_embeddings.embedding"
            ) from exc
        except Exception as exc:
            message = str(exc).lower()
            if "vector" in message or "<=>" in message or "operator does not exist" in message:
                raise VectorSearchUnavailableError(
                    "Vector photo search requires pgvector and vector-backed photo_embeddings.embedding"
                ) from exc
            raise

        rows = result.mappings().all()
        return [
            PhotoSearchResult(
                photo_id=row["photo_id"],
                storage_path=row["storage_path"],
                original_filename=row["original_filename"],
                content_type=row["content_type"],
                width=row["width"],
                height=row["height"],
                message_id=row["message_id"],
                conversation_id=row["conversation_id"],
                import_batch_id=row["import_batch_id"],
                caption=row["caption"],
                tags=row["tags"] or [],
                score=float(row["score"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]


def _vector_literal(embedding: list[float]) -> str:
    """Convert an embedding list into pgvector literal format."""
    return "[" + ",".join(f"{value:.10g}" for value in embedding) + "]"
