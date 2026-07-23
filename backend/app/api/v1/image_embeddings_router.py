from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.router import _current_user_or_401, _is_owner_user
from app.domains.image_embeddings.service import PhotoEmbeddingJobService
from app.models.database import get_db_session


router = APIRouter(prefix="/api/v1/image-embeddings", tags=["image-embeddings"])


@router.get("/jobs/status")
async def image_embedding_job_status(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db_session),
):
    current_user = await _current_user_or_401(authorization, db)
    if not _is_owner_user(current_user):
        raise HTTPException(status_code=403, detail="Owner access required")
    return await PhotoEmbeddingJobService(db).status_counts()
