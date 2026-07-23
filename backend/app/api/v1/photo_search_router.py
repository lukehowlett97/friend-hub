from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.router import AUTH_COOKIE_NAME, _current_user_or_401
from app.config import get_photo_upload_path
from app.domains.image_embeddings.service import ImageEmbeddingSearchError, ImageEmbeddingSearchService
from app.models.database import get_db_session


router = APIRouter(prefix="/api/v1/photos", tags=["photos"])


@router.get("/search")
async def search_photos(
    q: str = Query(...),
    limit: int = Query(default=30),
    conversation_id: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    source_type: str | None = None,
    import_batch_id: int | None = None,
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    await _current_user_or_401(authorization, db, session_cookie)
    query = q.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query must be non-empty")

    clamped_limit = max(1, min(limit, 100))
    try:
        results = await ImageEmbeddingSearchService(db).search_photos(
            query=query,
            limit=clamped_limit,
            conversation_id=conversation_id,
            date_from=date_from,
            date_to=date_to,
            source_type=source_type,
            import_batch_id=import_batch_id,
        )
    except ImageEmbeddingSearchError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {
        "query": query,
        "limit": clamped_limit,
        "results": [_photo_search_payload(result) for result in results],
    }


def _photo_search_payload(result) -> dict:
    return {
        "photo_id": str(result.photo_id),
        "score": result.score,
        "image_url": _safe_image_url(result.storage_path),
        "caption": result.caption,
        "tags": result.tags or [],
        "message_id": str(result.message_id) if result.message_id is not None else None,
        "conversation_id": result.conversation_id,
        "import_batch_id": str(result.import_batch_id) if result.import_batch_id is not None else None,
        "created_at": result.created_at.isoformat() if result.created_at else None,
    }


def _safe_image_url(storage_path: str | None) -> str | None:
    if not storage_path:
        return None
    value = storage_path.strip()
    if value.startswith("/uploads/photos/"):
        return value
    upload_dir = get_photo_upload_path().resolve()
    try:
        path = Path(value)
        if path.is_absolute():
            resolved = path.resolve()
            if resolved.is_relative_to(upload_dir):
                return f"/uploads/photos/{resolved.relative_to(upload_dir).as_posix()}"
            return None
    except (OSError, ValueError):
        return None
    if value.startswith("/"):
        return None
    return f"/uploads/photos/{value.removeprefix('photos/')}"
