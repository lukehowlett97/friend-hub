"""/catchup — summarise what a user missed since they last read the room.

Gap detection comes from chat_read_state; the narrative comes from the LLM
(over raw messages for small gaps, stored summaries for large ones); the
items appendix (polls, events, reminders) comes straight from hub queries so
short IDs are always real.
"""
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.ai.repository import AIMemoryRepository
from app.domains.chat.read_state_repository import ChatReadStateRepository
from app.domains.messages.repository import MessageRepository
from app.models.event import Event
from app.models.hub_item import HubItem
from app.models.planning import Poll, PollStatus, PollVote, Reminder

logger = logging.getLogger(__name__)

# Gaps up to this many messages are summarised from the raw messages;
# larger gaps use stored daily/weekly summaries plus a tail of recent chat.
CATCHUP_MAX_RAW_MESSAGES = 80
CATCHUP_TAIL_MESSAGES = 30
CATCHUP_MAX_CHARS = 40_000
APPENDIX_MAX_LINES_PER_SECTION = 5

CATCHUP_SYSTEM_PROMPT = (
    "You are Hub Bot catching a group-chat member up on what they missed.\n"
    "Use ONLY the supplied messages and summaries — never invent decisions, "
    "plans, facts, or item IDs like #E-1.\n"
    "Reply with 3-5 short bullet points (• ) covering the most important "
    "things that happened. Mention people by display name. No preamble."
)


@dataclass
class CatchupResult:
    reply: str
    message_count: int = 0
    used_llm: bool = False
    used_summaries: bool = False
    appendix_lines: List[str] = field(default_factory=list)


class CatchupService:
    def __init__(self, db: AsyncSession, llm_client=None):
        self.db = db
        self.llm_client = llm_client
        self.read_state_repo = ChatReadStateRepository(db)
        self.message_repo = MessageRepository(db)
        self.memory_repo = AIMemoryRepository(db)

    async def build_catchup(
        self,
        user_id: Optional[uuid.UUID],
        room_id: Optional[uuid.UUID],
        override_window: Optional[Tuple[datetime, datetime]] = None,
    ) -> CatchupResult:
        now = datetime.utcnow()
        after_id, gap_start = await self._resolve_gap(user_id, room_id, override_window, now)

        message_count = await self._count_gap_messages(room_id, after_id, gap_start)
        appendix_lines = await self._build_appendix(user_id, room_id, gap_start)

        if message_count == 0 and not appendix_lines:
            return CatchupResult(
                reply="You're all caught up — nothing new since you were last here 🎉",
                message_count=0,
            )

        header = f"Since you were last here ({gap_start:%a %H:%M}, {message_count} messages):"
        parts: List[str] = [header]
        used_llm = False
        used_summaries = False

        if message_count > 0:
            if message_count <= CATCHUP_MAX_RAW_MESSAGES:
                bullets = await self._summarise_messages(room_id, gap_start, now)
            else:
                bullets = await self._summarise_from_summaries(room_id, after_id, gap_start)
                used_summaries = True
            if bullets:
                parts.append(bullets)
                used_llm = True

        if appendix_lines:
            parts.extend(appendix_lines)

        parts.append(f"Want the full summary? /summarise since {gap_start:%H:%M}")

        return CatchupResult(
            reply="\n".join(parts),
            message_count=message_count,
            used_llm=used_llm,
            used_summaries=used_summaries,
            appendix_lines=appendix_lines,
        )

    # ── Gap detection ────────────────────────────────────────────────────────

    async def _resolve_gap(
        self,
        user_id: Optional[uuid.UUID],
        room_id: Optional[uuid.UUID],
        override_window: Optional[Tuple[datetime, datetime]],
        now: datetime,
    ) -> Tuple[Optional[int], datetime]:
        """Return (after_message_id, gap_start). after_message_id is None when
        the gap is purely time-based (explicit window or no read state)."""
        if override_window:
            start = override_window[0]
            if start.tzinfo is not None:
                start = start.astimezone(timezone.utc).replace(tzinfo=None)
            return None, start

        state = None
        if user_id is not None and room_id is not None:
            state = await self.read_state_repo.get(user_id, room_id)
        if state is None:
            return None, now - timedelta(hours=24)

        last_read = await self.message_repo.get_message_by_id(state.last_read_message_id)
        gap_start = last_read.created_at if last_read else now - timedelta(hours=24)
        return state.last_read_message_id, gap_start

    async def _count_gap_messages(
        self,
        room_id: Optional[uuid.UUID],
        after_id: Optional[int],
        gap_start: datetime,
    ) -> int:
        if after_id is not None:
            return await self.read_state_repo.count_messages_after(room_id, after_id)
        from sqlalchemy import func
        from app.models.message import Message

        query = select(func.count(Message.id)).where(
            Message.room_id == room_id,
            Message.is_deleted == False,  # noqa: E712
            Message.created_at >= gap_start,
        )
        result = await self.db.execute(query)
        return int(result.scalar() or 0)

    # ── LLM narrative ────────────────────────────────────────────────────────

    async def _summarise_messages(
        self,
        room_id: Optional[uuid.UUID],
        gap_start: datetime,
        now: datetime,
    ) -> str:
        from app.services.chat_service import ChatService

        chat_service = ChatService(self.db)
        messages = await chat_service.get_recent_messages(
            limit=CATCHUP_MAX_RAW_MESSAGES,
            start_at=gap_start,
            room_id=room_id,
        )
        messages_text = self._format_messages(messages)
        if not messages_text:
            return ""
        return await self._call_llm(
            f"The member was away from {gap_start:%a %H:%M} to {now:%a %H:%M} UTC. "
            f"Catch them up on these messages:\n\n{messages_text}"
        )

    async def _summarise_from_summaries(
        self,
        room_id: Optional[uuid.UUID],
        after_id: Optional[int],
        gap_start: datetime,
    ) -> str:
        summaries = await self.memory_repo.list_summaries_for_gap(
            room_id, after_id, gap_start
        )
        summaries_text = "\n\n".join(
            f"[{s.created_at:%a %d %b}] {s.title or s.memory_type}: {s.content}"
            for s in summaries
        )

        from app.services.chat_service import ChatService

        chat_service = ChatService(self.db)
        tail = await chat_service.get_recent_messages(
            limit=CATCHUP_TAIL_MESSAGES,
            room_id=room_id,
        )
        tail_text = self._format_messages(tail)

        prompt_parts = []
        if summaries_text:
            prompt_parts.append(f"STORED SUMMARIES:\n{summaries_text}")
        if tail_text:
            prompt_parts.append(f"MOST RECENT MESSAGES:\n{tail_text}")
        if not prompt_parts:
            return ""
        return await self._call_llm(
            "The member missed a long stretch of chat. Catch them up from these "
            "stored summaries and the most recent messages:\n\n"
            + "\n\n".join(prompt_parts)
        )

    def _format_messages(self, messages: List[dict]) -> str:
        lines: List[str] = []
        total = 0
        for m in messages:
            if m.get("is_deleted") or m.get("is_bot"):
                continue
            text = (m.get("content") or "").strip()
            if not text:
                continue
            ts = m.get("created_at")
            ts_label = ts.strftime("%H:%M") if hasattr(ts, "strftime") else str(ts or "")[:16]
            line = f"[{ts_label}] {m.get('nickname', '?')}: {text}"
            if total + len(line) > CATCHUP_MAX_CHARS:
                break
            lines.append(line)
            total += len(line) + 1
        return "\n".join(lines)

    async def _call_llm(self, user_prompt: str) -> str:
        from app.domains.ai.hub_agent_service import _call_llm_text

        return await _call_llm_text(self.llm_client, CATCHUP_SYSTEM_PROMPT, user_prompt)

    # ── Ground-truth items appendix (no LLM involved) ────────────────────────

    async def _build_appendix(
        self,
        user_id: Optional[uuid.UUID],
        room_id: Optional[uuid.UUID],
        gap_start: datetime,
    ) -> List[str]:
        lines: List[str] = []
        try:
            lines.extend(await self._open_polls_unvoted(user_id, room_id))
            lines.extend(await self._events_changed_in_gap(room_id, gap_start))
            lines.extend(await self._open_reminders(room_id))
        except Exception:
            logger.exception("Failed to build catchup items appendix")
        return lines

    async def _short_ref(self, room_id, source_type: str, source_id: int) -> str:
        from app.domains.ai.retrieval import short_ref

        return await short_ref(self.db, room_id, source_type, source_id)

    async def _open_polls_unvoted(self, user_id, room_id) -> List[str]:
        now = datetime.utcnow()
        query = (
            select(Poll)
            .where(
                Poll.room_id == room_id,
                Poll.archived_at.is_(None),
                or_(Poll.status.is_(None), Poll.status.notin_(
                    (PollStatus.closed.value, PollStatus.cancelled.value)
                )),
                or_(Poll.deadline_at.is_(None), Poll.deadline_at > now),
            )
            .order_by(Poll.created_at.desc())
            .limit(APPENDIX_MAX_LINES_PER_SECTION * 2)
        )
        if user_id is not None:
            query = query.where(
                ~Poll.id.in_(
                    select(PollVote.poll_id).where(PollVote.user_id == user_id)
                )
            )
        result = await self.db.execute(query)
        lines = []
        for poll in result.scalars().all()[:APPENDIX_MAX_LINES_PER_SECTION]:
            ref = await self._short_ref(room_id, "poll", poll.id)
            deadline = f" — closes {poll.deadline_at:%a %H:%M}" if poll.deadline_at else ""
            lines.append(f"• Poll {ref} \"{poll.question}\"{deadline} — you haven't voted.")
        return lines

    async def _events_changed_in_gap(self, room_id, gap_start: datetime) -> List[str]:
        query = (
            select(Event)
            .where(
                Event.room_id == room_id,
                Event.archived_at.is_(None),
                or_(Event.created_at >= gap_start, Event.updated_at >= gap_start),
            )
            .order_by(Event.created_at.desc())
            .limit(APPENDIX_MAX_LINES_PER_SECTION)
        )
        result = await self.db.execute(query)
        lines = []
        for event in result.scalars().all():
            ref = await self._short_ref(room_id, "event", event.id)
            verb = "created" if event.created_at >= gap_start else "updated"
            when = f" ({event.starts_at:%a %d %b %H:%M})" if event.starts_at else ""
            lines.append(f"• Event {ref} \"{event.title}\"{when} — {verb} while you were away.")
        return lines

    async def _open_reminders(self, room_id) -> List[str]:
        query = (
            select(Reminder)
            .where(
                Reminder.room_id == room_id,
                Reminder.is_completed == False,  # noqa: E712
                Reminder.archived_at.is_(None),
            )
            .order_by(Reminder.created_at.desc())
            .limit(APPENDIX_MAX_LINES_PER_SECTION)
        )
        result = await self.db.execute(query)
        lines = []
        for reminder in result.scalars().all():
            ref = await self._short_ref(room_id, "reminder", reminder.id)
            lines.append(f"• Reminder {ref} \"{reminder.text}\" is still open.")
        return lines
