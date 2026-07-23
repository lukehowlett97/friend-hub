from pathlib import Path
from types import SimpleNamespace
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_photo_upload_path, get_settings
from app.domains.image_embeddings.clip_model import OpenCLIPConfig, OpenCLIPEmbedder, OpenCLIPRuntimeError
from app.domains.image_embeddings.repository import (
    PhotoEmbeddingJobRepository,
    PhotoEmbeddingRepository,
    PhotoSearchResult,
    VectorSearchUnavailableError,
)
from app.models.photo import Photo
from app.models.photo_embedding import PhotoEmbedding, PhotoEmbeddingJob


class PhotoEmbeddingJobService:
    def __init__(
        self,
        db: AsyncSession,
        *,
        job_repository: PhotoEmbeddingJobRepository | None = None,
        embedding_repository: PhotoEmbeddingRepository | None = None,
        embedder=None,
        settings=None,
    ):
        self.db = db
        self.settings = settings or get_settings()
        self.repository = job_repository or PhotoEmbeddingJobRepository(db)
        self.embedding_repository = embedding_repository or PhotoEmbeddingRepository(db)
        self.embedder = embedder or OpenCLIPEmbedder(
            OpenCLIPConfig(
                model_name=self.settings.image_embeddings_model_name,
                model_version=self.settings.image_embeddings_model_version,
                device=self.settings.image_embeddings_device,
            )
        )

    async def create_pending_embedding_job(self, photo_id: int) -> PhotoEmbeddingJob:
        return await self.repository.create_pending_job(photo_id)

    async def status_counts(self) -> dict[str, int]:
        return await self.repository.status_counts()

    async def claim_pending_jobs(self, *, limit: int | None = None) -> list[PhotoEmbeddingJob]:
        batch_size = limit or self.settings.image_embeddings_batch_size
        return await self.repository.claim_pending_jobs(
            limit=batch_size,
            max_retries=self.settings.image_embeddings_max_retries,
        )

    async def mark_exhausted_pending_jobs(self) -> int:
        return await self.repository.mark_exhausted_pending_jobs(
            max_retries=self.settings.image_embeddings_max_retries,
        )

    async def process_job(self, job: PhotoEmbeddingJob) -> PhotoEmbedding | None:
        try:
            photo = await self.get_photo(job.photo_id)
            if photo is None:
                await self.repository.mark_failed(
                    job,
                    f"Photo not found: {job.photo_id}",
                    max_retries=self.settings.image_embeddings_max_retries,
                    retryable=False,
                )
                return None

            image_path = self.resolve_photo_path(photo)
            if not image_path.exists():
                await self.repository.mark_failed(
                    job,
                    f"Image file not found: {image_path}",
                    max_retries=self.settings.image_embeddings_max_retries,
                    retryable=False,
                )
                return None

            embedding = self.embedder.embed_image(image_path)
            row = await self.embedding_repository.upsert_embedding(
                photo_id=photo.id,
                model_name=self.embedder.model_name,
                model_version=self.embedder.model_version,
                embedding=embedding,
                tags=[],
            )
            await self.repository.mark_completed(job)
            return row
        except Exception as exc:
            await self.repository.mark_failed(
                job,
                str(exc),
                max_retries=self.settings.image_embeddings_max_retries,
                retryable=True,
            )
            return None

    async def get_photo(self, photo_id: int) -> Photo | None:
        result = await self.db.execute(select(Photo).where(Photo.id == photo_id))
        return result.scalar_one_or_none()

    def resolve_photo_path(self, photo: Photo) -> Path:
        storage_path = (photo.storage_path or "").strip()
        if storage_path:
            candidate = Path(storage_path)
            if candidate.is_absolute() and candidate.exists():
                return candidate
            uploads_prefix = "/uploads/photos/"
            if storage_path.startswith(uploads_prefix):
                return get_photo_upload_path() / storage_path.removeprefix(uploads_prefix)
            if not storage_path.startswith("/"):
                return get_photo_upload_path().parent / storage_path
        return get_photo_upload_path() / photo.filename

    async def search_photos(
        self,
        *,
        query: str,
        limit: int,
        conversation_id: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        source_type: str | None = None,
        import_batch_id: int | None = None,
    ) -> list[PhotoSearchResult]:
        clean_query = query.strip()
        if not clean_query:
            raise ValueError("Query must be non-empty")
        try:
            query_embedding = self.embedder.embed_text(clean_query)
        except OpenCLIPRuntimeError:
            raise
        except ImportError as exc:
            raise OpenCLIPRuntimeError(
                "Photo search requires optional ML dependencies in this process"
            ) from exc

        return await self.embedding_repository.search_similar_photos(
            query_embedding=query_embedding,
            limit=max(1, min(limit, 100)),
            conversation_id=conversation_id,
            date_from=date_from,
            date_to=date_to,
            source_type=source_type,
            import_batch_id=import_batch_id,
        )


class ImageEmbeddingSearchError(RuntimeError):
    pass


class ImageEmbeddingSearchService(PhotoEmbeddingJobService):
    async def search_photos(self, **kwargs) -> list[PhotoSearchResult]:
        try:
            return await super().search_photos(**kwargs)
        except OpenCLIPRuntimeError as exc:
            raise ImageEmbeddingSearchError(str(exc)) from exc
        except VectorSearchUnavailableError as exc:
            raise ImageEmbeddingSearchError(str(exc)) from exc


def embedding_settings(
    *,
    enabled: bool = True,
    model_name: str = "ViT-B-32",
    model_version: str = "laion2b_s34b_b79k",
    device: str = "auto",
    batch_size: int = 8,
    max_retries: int = 3,
):
    return SimpleNamespace(
        image_embeddings_enabled=enabled,
        image_embeddings_model_name=model_name,
        image_embeddings_model_version=model_version,
        image_embeddings_device=device,
        image_embeddings_batch_size=batch_size,
        image_embeddings_max_retries=max_retries,
    )
