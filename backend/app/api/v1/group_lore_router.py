"""Group Lore API endpoints — phase 1: search + phrase stats."""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.group_lore.service import GroupLoreService
from app.models.database import get_db_session

router = APIRouter(prefix="/api/v1/group-lore", tags=["group-lore"])


@router.get("/search")
async def search_group_lore(
    q: str = "",
    limit: int = 20,
    offset: int = 0,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    db: AsyncSession = Depends(get_db_session),
):
    """Exact phrase, case-insensitive message search.

    ``date_from`` is inclusive, ``date_to`` is exclusive. Blank queries return
    an empty result rather than 400 — keeps the frontend simple while the user
    is still typing.
    """
    service = GroupLoreService(db)
    return await service.search_messages(
        query=q,
        limit=limit,
        offset=offset,
        date_from=date_from,
        date_to=date_to,
    )


@router.get("/stats")
async def group_lore_stats(
    q: str = "",
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    db: AsyncSession = Depends(get_db_session),
):
    """Phrase occurrence counts grouped by sender."""
    service = GroupLoreService(db)
    return await service.phrase_stats(
        query=q,
        date_from=date_from,
        date_to=date_to,
    )
