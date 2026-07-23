"""Guest-session limits, demo simulation, and cleanup."""

import asyncio
import logging
import random
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta

from sqlalchemy import delete, select

from app.config import get_settings
from app.models.database import async_session_factory
from app.models.message import Message, User
from app.models.room import Room
from app.models.user_session import UserSession

logger = logging.getLogger(__name__)
DEMO_ROOM_SLUG = "demo"
_session_attempts: dict[str, deque[float]] = defaultdict(deque)
_DEMO_MESSAGES = (
    "Welcome to the Friend Hub demo — this room is live and safe to explore.",
    "The real app supports rooms, events, photos, notes, polls, and chat history.",
    "A visitor can join this room with a temporary name and no account.",
    "Try sending a message and watch it appear for everyone currently visiting.",
    "This conversation is simulated; private rooms are kept separate.",
)


def allow_demo_session_request(ip_address: str) -> bool:
    """Allow a small number of guest sessions per IP in each hour."""
    now = time.monotonic()
    bucket = _session_attempts[ip_address or "unknown"]
    while bucket and bucket[0] < now - 3600:
        bucket.popleft()
    if len(bucket) >= 12:
        return False
    bucket.append(now)
    return True


async def cleanup_demo_data() -> None:
    cutoff = datetime.utcnow() - timedelta(hours=get_settings().demo_guest_retention_hours)
    async with async_session_factory() as db:
        guest_ids = (await db.execute(
            select(User.id).where(User.user_type == "guest", User.last_seen < cutoff)
        )).scalars().all()
        if guest_ids:
            await db.execute(delete(UserSession).where(UserSession.user_id.in_(guest_ids)))
            await db.execute(delete(User).where(User.id.in_(guest_ids)))
        await db.commit()


async def run_demo_scheduler(connection_manager) -> None:
    """Post deterministic demo messages while visitors are connected."""
    settings = get_settings()
    while True:
        await asyncio.sleep(settings.demo_simulation_interval_seconds)
        try:
            if not connection_manager.has_room_connections_by_slug(DEMO_ROOM_SLUG):
                await cleanup_demo_data()
                continue
            async with async_session_factory() as db:
                room = (await db.execute(select(Room).where(Room.slug == DEMO_ROOM_SLUG))).scalar_one_or_none()
                bot = (await db.execute(
                    select(User).where(User.user_type == "demo_bot").order_by(User.created_at)
                )).scalars().first()
                if not room or not bot:
                    continue
                message = Message(
                    user_session_id=bot.session_id,
                    user_id=bot.id,
                    content=random.choice(_DEMO_MESSAGES),
                    room_id=room.id,
                )
                db.add(message)
                await db.commit()
                await db.refresh(message)
                from app.domains.chat.events import OutgoingChatMessage
                await connection_manager.broadcast_to_room(room.id, OutgoingChatMessage(
                    session_id=str(bot.session_id),
                    nickname=bot.nickname,
                    username=bot.username,
                    avatar_emoji=bot.avatar_emoji,
                    display_role=bot.display_role,
                    role="member",
                    is_bot=True,
                    content=message.content,
                    timestamp=message.created_at,
                    message_id=message.id,
                ).dict())
            await cleanup_demo_data()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Demo scheduler iteration failed")
