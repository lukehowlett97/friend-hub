"""Stats explorer API endpoints.

All endpoints require auth and use X-Room-Slug for room isolation.
Shared filter params: from, to, group_by, user_id, limit.
"""
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import get_db_session
from app.domains.stats.service import StatsService

AUTH_COOKIE_NAME = "friend_hub_session"

router = APIRouter(prefix="/api/v1/stats", tags=["stats-explorer"])


async def _resolve(
    authorization: Optional[str],
    session_cookie: Optional[str],
    x_room_slug: Optional[str],
    db: AsyncSession,
):
    """Shared auth + room resolution — mirrors the pattern in router.py."""
    from app.api.v1.router import _current_user_or_401, _request_room_id
    await _current_user_or_401(authorization, db, session_cookie)
    return await _request_room_id(
        db,
        authorization=authorization,
        session_cookie=session_cookie,
        x_room_slug=x_room_slug,
    )


@router.get("/activity")
async def stats_activity(
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    group_by: str = "day",
    metric: str = "messages",
    user_id: Optional[UUID] = None,
    authorization: Optional[str] = Header(default=None),
    x_room_slug: Optional[str] = Header(default=None, alias="X-Room-Slug"),
    session_cookie: Optional[str] = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    room_id = await _resolve(authorization, session_cookie, x_room_slug, db)
    svc = StatsService(db)
    return await svc.activity(
        room_id=room_id,
        date_from=date_from,
        date_to=date_to,
        group_by=group_by,
        user_id=user_id,
        metric=metric,
    )


@router.get("/leaderboard")
async def stats_leaderboard(
    metric: str = "messages",
    normalise: str = "absolute",
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    limit: int = 500,
    authorization: Optional[str] = Header(default=None),
    x_room_slug: Optional[str] = Header(default=None, alias="X-Room-Slug"),
    session_cookie: Optional[str] = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    room_id = await _resolve(authorization, session_cookie, x_room_slug, db)
    svc = StatsService(db)
    return await svc.leaderboard(
        room_id=room_id,
        metric=metric,
        normalise=normalise,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
    )


@router.get("/reactions/top")
async def stats_top_reactions(
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    limit: int = 20,
    authorization: Optional[str] = Header(default=None),
    x_room_slug: Optional[str] = Header(default=None, alias="X-Room-Slug"),
    session_cookie: Optional[str] = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    room_id = await _resolve(authorization, session_cookie, x_room_slug, db)
    svc = StatsService(db)
    return await svc.top_reactions(room_id=room_id, date_from=date_from, date_to=date_to, limit=limit)


@router.get("/reactions/signature")
async def stats_reaction_signature(
    direction: str = "given",
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    authorization: Optional[str] = Header(default=None),
    x_room_slug: Optional[str] = Header(default=None, alias="X-Room-Slug"),
    session_cookie: Optional[str] = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    room_id = await _resolve(authorization, session_cookie, x_room_slug, db)
    svc = StatsService(db)
    return await svc.reaction_signature(
        room_id=room_id, date_from=date_from, date_to=date_to, direction=direction
    )


@router.get("/reactions/dyadic")
async def stats_reaction_dyadic(
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    limit: int = 15,
    authorization: Optional[str] = Header(default=None),
    x_room_slug: Optional[str] = Header(default=None, alias="X-Room-Slug"),
    session_cookie: Optional[str] = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    room_id = await _resolve(authorization, session_cookie, x_room_slug, db)
    svc = StatsService(db)
    return await svc.reaction_dyadic(
        room_id=room_id, date_from=date_from, date_to=date_to, limit=limit
    )


@router.get("/reactions/trends")
async def stats_reaction_trends(
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    group_by: str = "month",
    top_n: int = 8,
    authorization: Optional[str] = Header(default=None),
    x_room_slug: Optional[str] = Header(default=None, alias="X-Room-Slug"),
    session_cookie: Optional[str] = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    room_id = await _resolve(authorization, session_cookie, x_room_slug, db)
    svc = StatsService(db)
    return await svc.reaction_trends(
        room_id=room_id, date_from=date_from, date_to=date_to, group_by=group_by, top_n=top_n
    )


@router.get("/reactions/by-sender")
async def stats_reactions_by_sender(
    emoji: Optional[str] = None,
    sort_by: str = "count",
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    limit: int = 500,
    authorization: Optional[str] = Header(default=None),
    x_room_slug: Optional[str] = Header(default=None, alias="X-Room-Slug"),
    session_cookie: Optional[str] = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    room_id = await _resolve(authorization, session_cookie, x_room_slug, db)
    svc = StatsService(db)
    return await svc.reactions_by_sender(
        room_id=room_id,
        emoji=emoji,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        sort_by=sort_by,
    )


@router.get("/messages/top-reacted")
async def stats_top_reacted_messages(
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    sender: Optional[str] = None,
    media_filter: str = "all",
    ignore_thumb_reactions: bool = False,
    limit: int = 10,
    offset: int = 0,
    authorization: Optional[str] = Header(default=None),
    x_room_slug: Optional[str] = Header(default=None, alias="X-Room-Slug"),
    session_cookie: Optional[str] = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    room_id = await _resolve(authorization, session_cookie, x_room_slug, db)
    svc = StatsService(db)
    images_only = media_filter == "images"
    return await svc.top_reacted_messages(
        room_id=room_id,
        date_from=date_from,
        date_to=date_to,
        sender=sender,
        limit=limit,
        offset=offset,
        images_only=images_only,
        ignore_thumb_reactions=ignore_thumb_reactions,
    )


@router.get("/messages/top-reacted-images")
async def stats_top_reacted_images(
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    sender: Optional[str] = None,
    limit: int = 10,
    authorization: Optional[str] = Header(default=None),
    x_room_slug: Optional[str] = Header(default=None, alias="X-Room-Slug"),
    session_cookie: Optional[str] = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    room_id = await _resolve(authorization, session_cookie, x_room_slug, db)
    svc = StatsService(db)
    return await svc.top_reacted_images(
        room_id=room_id, date_from=date_from, date_to=date_to, sender=sender, limit=limit
    )


@router.get("/overview")
async def stats_overview(
    authorization: Optional[str] = Header(default=None),
    x_room_slug: Optional[str] = Header(default=None, alias="X-Room-Slug"),
    session_cookie: Optional[str] = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    room_id = await _resolve(authorization, session_cookie, x_room_slug, db)
    svc = StatsService(db)
    return await svc.overview(room_id=room_id)


@router.get("/room-overview")
async def stats_room_overview(
    authorization: Optional[str] = Header(default=None),
    x_room_slug: Optional[str] = Header(default=None, alias="X-Room-Slug"),
    session_cookie: Optional[str] = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    """Compact summary powering the chat Room Overview drilldown sheet."""
    room_id = await _resolve(authorization, session_cookie, x_room_slug, db)
    svc = StatsService(db)
    return await svc.room_overview(room_id=room_id)
