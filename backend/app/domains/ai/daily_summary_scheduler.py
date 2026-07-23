"""
Daily summary scheduler — generates one daily_summary memory per room per day.

Runs as a single asyncio background task started at app startup, like the
reminder scheduler. Each tick it summarises yesterday's chat for any active
room that has messages but no daily_summary covering them yet, so the job is
idempotent per (room, day) and retries naturally after failures: the memory
row itself is the "already done" marker.
"""
import asyncio
import logging
from datetime import datetime, time as dtime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.message import Message
from app.models.room import Room

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 1800  # daily job — a 30 min poll is plenty


async def _summarize_room_day(
    db: AsyncSession,
    room: Room,
    day_start: datetime,
    day_end: datetime,
) -> bool:
    """Summarise one room's messages for [day_start, day_end). Returns True if a summary ran."""
    from app.domains.ai.repository import AIMemoryRepository
    from app.domains.ai.summary_service import HubSummaryService, create_llm_client

    range_result = await db.execute(
        select(func.min(Message.id), func.max(Message.id)).where(
            Message.room_id == room.id,
            Message.created_at >= day_start,
            Message.created_at < day_end,
            Message.is_deleted == False,  # noqa: E712
        )
    )
    min_id, max_id = range_result.one()
    if min_id is None:
        return False

    memory_repo = AIMemoryRepository(db)
    if await memory_repo.exists_daily_summary_overlapping(room.id, min_id, max_id):
        return False

    service = HubSummaryService(db, create_llm_client())
    await service.summarize_chat(
        room_id=room.id,
        start_at=day_start,
        end_at=day_end,
        created_by="daily_summary_job",
        user_message=f"scheduled daily summary {day_start:%Y-%m-%d} for room {room.slug}",
    )
    await db.commit()
    logger.info(
        "Daily summary created for room %s (%s, messages %s–%s)",
        room.slug, day_start.date(), min_id, max_id,
    )
    return True


async def _run_once(db: AsyncSession) -> int:
    """Summarise yesterday for every active room that still needs it."""
    from app.config import get_settings

    settings = get_settings()
    if not settings.ai_daily_summary_enabled or not settings.ai_api_key:
        return 0

    today_midnight = datetime.combine(datetime.utcnow().date(), dtime.min)
    day_start = today_midnight - timedelta(days=1)
    day_end = today_midnight

    rooms_result = await db.execute(select(Room).where(Room.status == "active"))
    rooms = list(rooms_result.scalars().all())

    summarised = 0
    for room in rooms:
        try:
            if await _summarize_room_day(db, room, day_start, day_end):
                summarised += 1
        except Exception:
            logger.exception("Daily summary failed for room %s", room.slug)
            await db.rollback()
    return summarised


async def run_daily_summary_scheduler() -> None:
    """Long-running background coroutine. Start once at app startup."""
    from app.models.database import async_session_factory

    logger.info("Daily summary scheduler started (poll interval: %ds)", POLL_INTERVAL_SECONDS)
    while True:
        try:
            async with async_session_factory() as db:
                await _run_once(db)
        except Exception as exc:
            logger.error("Daily summary scheduler tick error: %s", exc)
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
