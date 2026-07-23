"""Admin visibility into the chat embeddings pipeline."""
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.router import _current_user_or_401, _is_owner_user
from app.config import get_settings
from app.domains.chat_embeddings.repository import ChatEmbeddingJobRepository
from app.models.chat_embedding import ChatEmbedding, ChatEmbeddingJob
from app.models.database import get_db_session

router = APIRouter(prefix="/api/v1/admin/chat-embeddings", tags=["chat-embeddings"])


@router.get("/status")
async def chat_embedding_status(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db_session),
):
    """One-call health check: job counts, totals, last activity, config."""
    current_user = await _current_user_or_401(authorization, db)
    if not _is_owner_user(current_user):
        raise HTTPException(status_code=403, detail="Owner access required")

    settings = get_settings()
    job_counts = await ChatEmbeddingJobRepository(db).status_counts()

    totals = await db.execute(
        select(
            func.count(ChatEmbedding.id),
            func.max(ChatEmbedding.updated_at),
        ).where(
            ChatEmbedding.model_name == settings.ai_embedding_model,
            ChatEmbedding.model_version == settings.ai_embedding_provider,
        )
    )
    total_embeddings, last_embedded_at = totals.one()

    last_processed = await db.execute(
        select(func.max(ChatEmbeddingJob.completed_at)).where(
            ChatEmbeddingJob.status == "completed"
        )
    )
    last_processed_at = last_processed.scalar()

    return {
        "enabled": settings.ai_enable_chat_embeddings,
        "provider": settings.ai_embedding_provider,
        "model": settings.ai_embedding_model,
        "similarity_floor": settings.ai_retrieval_similarity_floor,
        "total_embeddings": int(total_embeddings or 0),
        "jobs": job_counts,
        "last_processed_at": last_processed_at.isoformat() if last_processed_at else None,
        "last_embedded_at": last_embedded_at.isoformat() if last_embedded_at else None,
    }
