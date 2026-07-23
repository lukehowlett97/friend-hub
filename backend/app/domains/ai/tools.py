"""
Shared Hub Bot Tool Layer — reusable service-layer helpers.

These tools provide safe, inspectable access to hub items, memories,
and suggestions. They return serialisable dicts, not ORM objects.

Tool Registry metadata allows future agent orchestration to discover
available tools with their safety levels.

Intended consumers:
- Hub Bot Lab
- existing Hub Bot chat
- future Hermes-style agent
- scheduled summary jobs
"""
import uuid
import re
from datetime import datetime
from typing import Any, Callable, Coroutine, List, Optional

from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.ai.repository import AIMemoryRepository, AISuggestionRepository
from app.domains.hub_items.references import find_hub_item_references
from app.models.ai_memory import AIMemoryEntry
from app.models.ai_memory import AISuggestion
from app.models.event import Event
from app.models.hub_item import HubItem
from app.models.message import User
from app.models.planning import DEFAULT_GROUP_SLUG, Group, Idea, IdeaStatus, Poll, PollOption, PollVoteMode, Reminder, ReminderAssignee
from app.models.room import DEFAULT_ROOM_ID


def _require_ctx(ctx: dict, *keys: str) -> None:
    """Raise ValueError if any required context key is missing or None."""
    missing = [k for k in keys if not ctx.get(k)]
    if missing:
        raise ValueError(f"Tool context missing required keys: {missing}")


HUB_ITEM_PREFIXES = {
    "poll": "P",
    "event": "E",
    "reminder": "R",
    "idea": "I",
    "note": "N",
}

_SHORT_ID_SAFE_CHARS_RE = re.compile(r"[^a-z0-9_-]+")


# ── Type Aliases ──────────────────────────────────────────────────────────────

ToolHandler = Callable[..., Coroutine[Any, Any, dict]]
ToolResult = dict


# ── Serialisation Helpers ─────────────────────────────────────────────────────


def _memory_to_dict(memory: AIMemoryEntry) -> dict:
    return {
        "id": str(memory.id),
        "type": memory.memory_type,
        "title": memory.title,
        "content": memory.content,
        "source_type": memory.source_type,
        "confidence": memory.confidence,
        "tags": memory.tags or [],
        "created_by": memory.created_by,
        "created_at": memory.created_at.isoformat() if memory.created_at else None,
    }


def _suggestion_to_dict(suggestion: AISuggestion) -> dict:
    return {
        "id": str(suggestion.id),
        "type": suggestion.suggestion_type,
        "title": suggestion.title,
        "body": suggestion.body,
        "status": suggestion.status,
        "proposed_hub_item_type": suggestion.proposed_hub_item_type,
        "source_memory_ids": suggestion.source_memory_ids or [],
        "created_at": suggestion.created_at.isoformat() if suggestion.created_at else None,
    }


def _hub_item_to_dict(item: HubItem) -> dict:
    return {
        "id": str(item.id),
        "short_id": item.short_id,
        "type": item.item_type,
        "title": item.title,
        "body": item.body,
        "tags": item.tags or [],
        "status": item.status,
        "due_at": item.due_at.isoformat() if item.due_at else None,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


def _slugify_short_ref(value: str) -> str:
    cleaned = _SHORT_ID_SAFE_CHARS_RE.sub("-", str(value or "").strip().lower())
    cleaned = re.sub(r"-+", "-", cleaned).strip("-_")
    return cleaned


async def _build_semantic_short_id(
    db: AsyncSession,
    *,
    group_id: int,
    room_id,
    item_type: str,
    source_id: int,
    title: str,
    reference_tag: str | None = None,
) -> str:
    """Build a unique semantic ref like #E-party, falling back to #E-1."""
    prefix = HUB_ITEM_PREFIXES[item_type]
    fallback = f"#{prefix}-{source_id}"
    seed = reference_tag or title
    slug = _slugify_short_ref(seed)
    if not slug:
        return fallback

    prefix_text = f"{prefix.lower()}-"
    if slug.startswith("#"):
        slug = slug[1:]
    if slug.startswith(prefix_text):
        slug = slug[len(prefix_text):]
    slug = slug[:17].strip("-_")
    if not slug:
        return fallback

    base_body = f"{prefix}-{slug}"
    candidates = [f"#{base_body}"]
    for index in range(2, 10):
        suffix = f"-{index}"
        candidates.append(f"#{base_body[:19 - len(suffix)]}{suffix}")

    for candidate in candidates:
        if not await _short_id_exists(db, group_id, candidate, room_id=room_id):
            return candidate

    return fallback


async def _short_id_exists(db: AsyncSession, group_id: int, short_id: str, room_id=None) -> bool:
    """Return whether a HubItem short_id already exists, with test-db support."""
    # Several unit tests use a small fake AsyncSession that stores HubItems in
    # memory rather than interpreting SQLAlchemy expressions.
    in_memory_store = getattr(db, "_hub_item_store", None)
    if isinstance(in_memory_store, dict):
        return any(
            getattr(item, "group_id", None) == group_id
            and (room_id is None or getattr(item, "room_id", None) == room_id)
            and (getattr(item, "short_id", "") or "").upper() == short_id.upper()
            for item in in_memory_store.values()
        )

    result = await db.execute(
        select(HubItem.id).where(
            HubItem.group_id == group_id,
            func.upper(HubItem.short_id) == short_id.upper(),
            *( [HubItem.room_id == room_id] if room_id is not None else [] ),
        )
    )
    return result.scalar_one_or_none() is not None


async def _create_hub_item_mirror(
    db: AsyncSession,
    *,
    group_id: int,
    item_type: str,
    source_id: int,
    title: str,
    body: str | None = None,
    tags: list | None = None,
    created_by_user_id=None,
    due_at: datetime | None = None,
    event_start_at: datetime | None = None,
    room_id=None,
    reference_tag: str | None = None,
) -> HubItem:
    short_id = await _build_semantic_short_id(
        db,
        group_id=group_id,
        room_id=room_id,
        item_type=item_type,
        source_id=source_id,
        title=title,
        reference_tag=reference_tag,
    )
    item = HubItem(
        group_id=group_id,
        room_id=room_id or DEFAULT_ROOM_ID,
        item_type=item_type,
        type_sequence=source_id,
        short_id=short_id,
        source_type=item_type,
        source_id=source_id,
        title=title[:220],
        body=body,
        tags=tags or [],
        created_by_user_id=created_by_user_id,
        due_at=due_at,
        event_start_at=event_start_at,
    )
    db.add(item)
    await db.flush()
    return item


# ── Tool Registry ─────────────────────────────────────────────────────────────


class ToolRegistry:
    """Registry of available tools with metadata for future agent orchestration.
    
    Each tool has:
    - name: Unique identifier
    - description: Human-readable description
    - safety: "read_only" | "safe_write" | "approval_required"
    - handler: Async function that accepts db session + kwargs
    """

    def __init__(self):
        self._tools: dict[str, dict] = {}

    def register(
        self,
        name: str,
        description: str,
        safety: str,
        handler: ToolHandler,
    ) -> None:
        """Register a tool."""
        self._tools[name] = {
            "name": name,
            "description": description,
            "safety": safety,
            "handler": handler,
        }

    def get(self, name: str) -> Optional[dict]:
        """Get tool metadata + handler by name."""
        return self._tools.get(name)

    def list_tools(self) -> List[dict]:
        """List all registered tools (without handlers)."""
        return [
            {"name": t["name"], "description": t["description"], "safety": t["safety"]}
            for t in self._tools.values()
        ]

    def get_handler(self, name: str) -> Optional[ToolHandler]:
        """Get a tool handler by name."""
        tool = self._tools.get(name)
        return tool["handler"] if tool else None

    async def call(
        self,
        name: str,
        db: AsyncSession,
        _ctx: Optional[dict] = None,
        **kwargs,
    ) -> ToolResult:
        """Call a tool by name.

        Args:
            name: Registered tool name.
            db: Async SQLAlchemy session.
            _ctx: Server-side context (group_id, created_by_user_id, …).
                  Passed to handlers that declare a ``_ctx`` keyword argument;
                  silently ignored by handlers that don't.
            **kwargs: LLM-supplied arguments forwarded to the handler.
        """
        handler = self.get_handler(name)
        if not handler:
            return {"error": f"Tool '{name}' not found", "success": False}

        import inspect
        sig = inspect.signature(handler)
        if "_ctx" in sig.parameters:
            return await handler(db, _ctx=_ctx or {}, **kwargs)
        return await handler(db, **kwargs)


# ── Read Tools ────────────────────────────────────────────────────────────────


async def get_item_by_reference(db: AsyncSession, ref: str, _ctx: dict | None = None) -> dict:
    """Look up a hub item by its short reference (e.g., #P-1, #I-3).
    
    Uses the existing find_hub_item_references parser from the Hub Bot.
    Returns the first match or an empty result.
    """
    refs = find_hub_item_references(ref)
    if not refs:
        return {"found": False, "item": None, "ref": ref, "error": "No reference found in input"}

    short_ids = list({r["short_id"] for r in refs})
    result = await db.execute(
        select(HubItem).where(
            HubItem.short_id.in_(short_ids),
            HubItem.archived_at.is_(None),
            *( [HubItem.room_id == (_ctx or {}).get("room_id")] if (_ctx or {}).get("room_id") else [] ),
        )
    )
    items = result.scalars().all()

    if not items:
        return {"found": False, "item": None, "ref": short_ids[0], "error": "Item not found"}

    return {"found": True, "item": _hub_item_to_dict(items[0]), "ref": short_ids[0]}


async def search_hub_items(db: AsyncSession, query: str, limit: int = 10, _ctx: dict | None = None) -> dict:
    """Search hub items by title or body text."""
    search_pattern = f"%{query}%"
    stmt = (
        select(HubItem)
        .where(
            HubItem.archived_at.is_(None),
            or_(
                HubItem.title.ilike(search_pattern),
                HubItem.body.ilike(search_pattern),
            ),
        )
        .order_by(desc(HubItem.created_at))
        .limit(limit)
    )
    if (_ctx or {}).get("room_id"):
        stmt = stmt.where(HubItem.room_id == (_ctx or {}).get("room_id"))
    result = await db.execute(stmt)
    items = result.scalars().all()
    return {
        "found": len(items) > 0,
        "count": len(items),
        "items": [_hub_item_to_dict(i) for i in items],
    }


async def list_recent_hub_items(db: AsyncSession, limit: int = 10, _ctx: dict | None = None) -> dict:
    """List most recent non-archived hub items."""
    stmt = (
        select(HubItem)
        .where(HubItem.archived_at.is_(None))
        .order_by(desc(HubItem.created_at))
        .limit(limit)
    )
    if (_ctx or {}).get("room_id"):
        stmt = stmt.where(HubItem.room_id == (_ctx or {}).get("room_id"))
    result = await db.execute(stmt)
    items = result.scalars().all()
    return {
        "count": len(items),
        "items": [_hub_item_to_dict(i) for i in items],
    }


async def search_memories(db: AsyncSession, query: str, limit: int = 10) -> dict:
    """Search AI memory entries by title or content."""
    search_pattern = f"%{query}%"
    result = await db.execute(
        select(AIMemoryEntry)
        .where(
            or_(
                AIMemoryEntry.title.ilike(search_pattern),
                AIMemoryEntry.content.ilike(search_pattern),
            ),
        )
        .order_by(desc(AIMemoryEntry.created_at))
        .limit(limit)
    )
    memories = result.scalars().all()
    return {
        "found": len(memories) > 0,
        "count": len(memories),
        "memories": [_memory_to_dict(m) for m in memories],
    }


async def list_recent_memories(db: AsyncSession, limit: int = 10) -> dict:
    """List most recent AI memory entries."""
    result = await db.execute(
        select(AIMemoryEntry)
        .order_by(desc(AIMemoryEntry.created_at))
        .limit(limit)
    )
    memories = result.scalars().all()
    return {
        "count": len(memories),
        "memories": [_memory_to_dict(m) for m in memories],
    }


async def list_pending_suggestions(db: AsyncSession, limit: int = 10) -> dict:
    """List pending (unprocessed) AI suggestions."""
    result = await db.execute(
        select(AISuggestion)
        .where(AISuggestion.status == "pending")
        .order_by(desc(AISuggestion.created_at))
        .limit(limit)
    )
    suggestions = result.scalars().all()
    return {
        "count": len(suggestions),
        "suggestions": [_suggestion_to_dict(s) for s in suggestions],
    }


# ── Safe Write Tools ──────────────────────────────────────────────────────────


async def create_memory_entry(
    db: AsyncSession,
    memory_type: str,
    content: str,
    title: Optional[str] = None,
    tags: Optional[List[str]] = None,
    confidence: Optional[float] = None,
    source_type: Optional[str] = None,
) -> dict:
    """Create a new AI memory entry.
    
    Returns serialised dict of the created entry.
    """
    repo = AIMemoryRepository(db)
    entry = await repo.create(
        memory_type=memory_type,
        content=content,
        title=title,
        tags=tags or [],
        confidence=confidence,
        source_type=source_type or "manual",
    )
    return {"success": True, "memory": _memory_to_dict(entry)}


async def create_ai_suggestion(
    db: AsyncSession,
    suggestion_type: str,
    title: str,
    body: Optional[str] = None,
    proposed_hub_item_type: Optional[str] = None,
    proposed_payload: Optional[dict] = None,
    source_memory_ids: Optional[List[str]] = None,
) -> dict:
    """Create a new AI suggestion.
    
    Returns serialised dict of the created suggestion.
    """
    repo = AISuggestionRepository(db)
    suggestion = await repo.create(
        suggestion_type=suggestion_type,
        title=title,
        body=body,
        proposed_hub_item_type=proposed_hub_item_type,
        proposed_payload=proposed_payload,
        source_memory_ids=source_memory_ids or [],
    )
    return {"success": True, "suggestion": _suggestion_to_dict(suggestion)}


# ── Planning Write Tools ──────────────────────────────────────────────────────
#
# These tools create canonical Poll, Event, and Reminder rows immediately,
# plus their hub_items mirror rows. They intentionally do not create
# ai_draft_actions rows.
#
# Context requirements (from _ctx, NOT from LLM args):
#   group_id          int   — which group this draft belongs to
#   created_by_user_id uuid — the human who triggered the agent run
#   agent_run_id      uuid  — optional, links draft to the observability run
#   source            str   — "hub_lab" | "chat" | "scheduled_job"
#   dry_run           bool  — if True, return preview without persisting


def _created_item_to_tool_dict(
    *,
    item_type: str,
    title: str,
    source_id: int,
    hub_item: HubItem,
    extra: dict | None = None,
) -> dict:
    payload = {
        "item_type": item_type,
        "title": title,
        "status": "created",
        "source_id": source_id,
        "created_hub_item_id": str(hub_item.id),
        "short_id": hub_item.short_id,
        "route": f"/{item_type}s" if item_type != "poll" else "/polls",
    }
    if item_type == "event":
        payload["created_event_id"] = source_id
        payload["route"] = f"/events/{source_id}"
    elif item_type == "poll":
        payload["created_poll_id"] = source_id
    elif item_type == "reminder":
        payload["created_reminder_id"] = source_id
    if extra:
        payload.update(extra)
    return payload


def _dry_run_tool_dict(item_type: str, title: str, payload: dict) -> dict:
    return {
        "success": True,
        "dry_run": True,
        "item_type": item_type,
        "title": title,
        "status": "created",
        "payload": payload,
    }


async def propose_poll(
    db: AsyncSession,
    _ctx: dict,
    question: str,
    options: List[str],
    closes_at: Optional[str] = None,
    allow_multiple: bool = False,
    tags: Optional[List[str]] = None,
    reference_tag: Optional[str] = None,
) -> dict:
    """Create a poll immediately and mirror it as a hub item."""
    _require_ctx(_ctx, "group_id", "created_by_user_id")

    clean_options = [str(option).strip() for option in options if str(option).strip()]
    if len(clean_options) < 2:
        raise ValueError("Poll requires at least two non-empty options")

    from app.domains.ai.draft_action_service import _parse_datetime

    closes_at_dt = _parse_datetime(closes_at, "closes_at") if closes_at is not None else None
    payload: dict = {
        "question": question,
        "options": clean_options,
        "vote_mode": "multiple" if allow_multiple else "single",
        "tags": tags or [],
        "reference_tag": reference_tag,
    }
    if closes_at is not None:
        payload["closes_at"] = closes_at

    if _ctx.get("dry_run"):
        return _dry_run_tool_dict("poll", question, payload)

    poll = Poll(
        group_id=_ctx["group_id"],
        room_id=_ctx.get("room_id") or DEFAULT_ROOM_ID,
        question=str(question).strip()[:220],
        created_by_user_id=_ctx["created_by_user_id"],
        vote_mode=PollVoteMode.multiple if allow_multiple else PollVoteMode.single,
        deadline_at=closes_at_dt,
    )
    db.add(poll)
    await db.flush()
    for index, label in enumerate(clean_options):
        db.add(PollOption(poll_id=poll.id, label=label[:160], position=index))
    hub_item = await _create_hub_item_mirror(
        db,
        group_id=_ctx["group_id"],
        item_type="poll",
        source_id=poll.id,
        title=str(question).strip(),
        tags=tags or [],
        created_by_user_id=_ctx["created_by_user_id"],
        due_at=closes_at_dt,
        room_id=_ctx.get("room_id"),
        reference_tag=reference_tag,
    )
    await db.commit()
    return {"success": True, "dry_run": False, **_created_item_to_tool_dict(item_type="poll", title=poll.question, source_id=poll.id, hub_item=hub_item)}


async def propose_event(
    db: AsyncSession,
    _ctx: dict,
    title: str,
    starts_at: str,
    ends_at: Optional[str] = None,
    location: Optional[str] = None,
    description: Optional[str] = None,
    tags: Optional[List[str]] = None,
    reference_tag: Optional[str] = None,
) -> dict:
    """Create an event immediately and mirror it as a hub item."""
    _require_ctx(_ctx, "group_id", "created_by_user_id")

    if not title or not str(title).strip():
        raise ValueError("Event title must not be blank")
    from app.domains.ai.draft_action_service import _parse_datetime

    starts_at_dt = _parse_datetime(starts_at, "starts_at")
    if starts_at_dt is None:
        raise ValueError("Event requires starts_at")
    ends_at_dt = _parse_datetime(ends_at, "ends_at") if ends_at is not None else None
    payload: dict = {
        "title": title,
        "starts_at": starts_at,
        "tags": tags or [],
        "reference_tag": reference_tag,
    }
    if ends_at is not None:
        payload["ends_at"] = ends_at
    if location is not None:
        payload["location"] = location
    if description is not None:
        payload["description"] = description

    if _ctx.get("dry_run"):
        return _dry_run_tool_dict("event", title, payload)

    creator = await db.get(User, _ctx["created_by_user_id"])
    event = Event(
        group_id=_ctx["group_id"],
        room_id=_ctx.get("room_id") or DEFAULT_ROOM_ID,
        title=str(title).strip()[:120],
        description=str(description)[:2000] if description else None,
        location=str(location)[:160] if location else None,
        starts_at=starts_at_dt,
        created_by_session_id=creator.session_id if creator else None,
    )
    db.add(event)
    await db.flush()
    hub_item = await _create_hub_item_mirror(
        db,
        group_id=_ctx["group_id"],
        item_type="event",
        source_id=event.id,
        title=str(title).strip(),
        body=description,
        tags=tags or [],
        created_by_user_id=_ctx["created_by_user_id"],
        event_start_at=starts_at_dt,
        room_id=_ctx.get("room_id"),
        reference_tag=reference_tag,
    )
    if ends_at_dt is not None:
        hub_item.event_end_at = ends_at_dt
    if event.photo_tag_id is None:
        event.photo_tag_id = hub_item.short_id
    await db.commit()
    return {
        "success": True, "dry_run": False,
        **_created_item_to_tool_dict(item_type="event", title=event.title, source_id=event.id, hub_item=hub_item),
        "starts_at": starts_at,
        "ends_at": ends_at,
        "location": location,
    }


async def propose_reminder(
    db: AsyncSession,
    _ctx: dict,
    text: Optional[str] = None,
    title: Optional[str] = None,
    remind_at: Optional[str] = None,
    context: Optional[str] = None,
    target_user_ids: Optional[List[str]] = None,
    group_wide: bool = False,
    tags: Optional[List[str]] = None,
    recurrence: Optional[str] = None,      # None | 'daily' | 'weekly' | 'every_N_days'
    recurrence_days: Optional[int] = None, # N when recurrence='every_N_days'
    recurrence_ends_at: Optional[str] = None,
    reference_tag: Optional[str] = None,
) -> dict:
    """Create a reminder immediately and mirror it as a hub item."""
    _require_ctx(_ctx, "group_id", "created_by_user_id")

    reminder_title = title if title is not None else text
    if not reminder_title or not str(reminder_title).strip():
        raise ValueError("Reminder title must not be blank")
    from app.domains.ai.draft_action_service import _parse_datetime

    if not remind_at:
        raise ValueError("Reminder remind_at must include a date and time")
    remind_at_dt = _parse_datetime(remind_at, "remind_at")
    recurrence_ends_at_dt = _parse_datetime(recurrence_ends_at, "recurrence_ends_at") if recurrence_ends_at else None
    valid_recurrences = {"daily", "weekly", "every_N_days"}
    clean_recurrence = recurrence if recurrence in valid_recurrences else None
    payload: dict = {
        "title": str(reminder_title).strip(),
        "text": str(reminder_title).strip(),
        "context": context,
        "group_wide": group_wide,
        "target_user_ids": target_user_ids or [],
        "tags": tags or [],
        "recurrence": clean_recurrence,
        "recurrence_ends_at": recurrence_ends_at,
        "reference_tag": reference_tag,
    }
    if remind_at is not None:
        payload["remind_at"] = remind_at

    if _ctx.get("dry_run"):
        return _dry_run_tool_dict("reminder", str(reminder_title).strip(), payload)

    reminder = Reminder(
        group_id=_ctx["group_id"],
        room_id=_ctx.get("room_id") or DEFAULT_ROOM_ID,
        text=str(reminder_title).strip()[:1000],
        context=(context or "").strip()[:2000] or None,
        due_at=remind_at_dt,
        recurrence=clean_recurrence,
        recurrence_days=recurrence_days if clean_recurrence == "every_N_days" else None,
        recurrence_ends_at=recurrence_ends_at_dt if clean_recurrence else None,
        created_by_user_id=_ctx["created_by_user_id"],
    )
    db.add(reminder)
    await db.flush()
    if target_user_ids:
        clean_ids = list(dict.fromkeys(str(uid) for uid in target_user_ids if uid))
        if clean_ids:
            valid_result = await db.execute(select(User.id).where(User.id.in_(clean_ids)))
            for (uid,) in valid_result.fetchall():
                db.add(ReminderAssignee(reminder_id=reminder.id, user_id=uid))
    hub_item = await _create_hub_item_mirror(
        db,
        group_id=_ctx["group_id"],
        item_type="reminder",
        source_id=reminder.id,
        title=reminder.text[:220],
        body=reminder.context,
        tags=tags or [],
        created_by_user_id=_ctx["created_by_user_id"],
        due_at=remind_at_dt,
        room_id=_ctx.get("room_id"),
        reference_tag=reference_tag,
    )
    await db.commit()
    return {"success": True, "dry_run": False, **_created_item_to_tool_dict(item_type="reminder", title=reminder.text, source_id=reminder.id, hub_item=hub_item)}


async def propose_idea(
    db: AsyncSession,
    _ctx: dict,
    title: str,
    description: Optional[str] = None,
    category: Optional[str] = None,
    tags: Optional[List[str]] = None,
    reference_tag: Optional[str] = None,
) -> dict:
    """Create an idea immediately and mirror it as a hub item."""
    _require_ctx(_ctx, "group_id", "created_by_user_id")

    if not title or not str(title).strip():
        raise ValueError("Idea title must not be blank")

    if _ctx.get("dry_run"):
        return _dry_run_tool_dict("idea", title, {"title": title, "description": description, "category": category or "general", "reference_tag": reference_tag})

    clean_category = (category or "general").strip().lower()[:60]
    idea = Idea(
        group_id=_ctx["group_id"],
        room_id=_ctx.get("room_id") or DEFAULT_ROOM_ID,
        title=str(title).strip()[:160],
        description=str(description)[:2000] if description else None,
        category=clean_category,
        status=IdeaStatus.maybe,
        created_by_user_id=_ctx["created_by_user_id"],
    )
    db.add(idea)
    await db.flush()
    hub_item = await _create_hub_item_mirror(
        db,
        group_id=_ctx["group_id"],
        item_type="idea",
        source_id=idea.id,
        title=str(title).strip(),
        body=description,
        tags=tags or [clean_category],
        created_by_user_id=_ctx["created_by_user_id"],
        room_id=_ctx.get("room_id"),
        reference_tag=reference_tag,
    )
    await db.commit()
    return {
        "success": True, "dry_run": False,
        **_created_item_to_tool_dict(item_type="idea", title=idea.title, source_id=idea.id, hub_item=hub_item),
    }


# ── Build Default Registry ────────────────────────────────────────────────────


def build_default_registry() -> ToolRegistry:
    """Create and populate a ToolRegistry with all available tools."""
    registry = ToolRegistry()

    # Read tools
    registry.register(
        name="get_item_by_reference",
        description="Look up a hub item by its short reference (e.g., #P-1, #I-3)",
        safety="read_only",
        handler=get_item_by_reference,
    )
    registry.register(
        name="search_hub_items",
        description="Search hub items by title or body text",
        safety="read_only",
        handler=search_hub_items,
    )
    registry.register(
        name="list_recent_hub_items",
        description="List most recent non-archived hub items",
        safety="read_only",
        handler=list_recent_hub_items,
    )
    registry.register(
        name="search_memories",
        description="Search AI memory entries by title or content",
        safety="read_only",
        handler=search_memories,
    )
    registry.register(
        name="list_recent_memories",
        description="List most recent AI memory entries",
        safety="read_only",
        handler=list_recent_memories,
    )
    registry.register(
        name="list_pending_suggestions",
        description="List pending (unprocessed) AI suggestions",
        safety="read_only",
        handler=list_pending_suggestions,
    )

    # Safe write tools
    registry.register(
        name="create_memory_entry",
        description="Create a new AI memory entry",
        safety="safe_write",
        handler=create_memory_entry,
    )
    registry.register(
        name="create_ai_suggestion",
        description="Create a new AI suggestion",
        safety="safe_write",
        handler=create_ai_suggestion,
    )

    # Planning write tools — create final records immediately.
    registry.register(
        name="propose_poll",
        description=(
            "Create a poll immediately. "
            "Requires: question (str), options (list of at least 2 strings). "
            "Optional: closes_at (ISO-8601), allow_multiple (bool), tags (list), "
            "reference_tag (short semantic slug, e.g. 'dinner-vote'; system prefixes it as #P-*)."
        ),
        safety="safe_write",
        handler=propose_poll,
    )
    registry.register(
        name="propose_event",
        description=(
            "Create an event immediately. "
            "Requires: title (str), starts_at (ISO-8601). "
            "Optional: ends_at, location, description, tags, "
            "reference_tag (short semantic slug, e.g. 'party'; system prefixes it as #E-*)."
        ),
        safety="safe_write",
        handler=propose_event,
    )
    registry.register(
        name="propose_reminder",
        description=(
            "Create a reminder immediately. "
            "Requires: title (str, short subject ≤5 words), remind_at (ISO-8601 date and time). "
            "ALWAYS set context to a full sentence explaining the purpose of the reminder using any "
            "detail from the user's message — e.g. 'Remind the group to book taxis for Friday night.' "
            "Optional: target_user_ids (list of user IDs to assign), group_wide (bool), tags, "
            "recurrence ('daily'|'weekly'|'every_N_days'), recurrence_days (int, required when every_N_days)."
            " Optional: recurrence_ends_at (ISO-8601 date/time), reference_tag "
            "(short semantic slug, e.g. 'book-taxis'; system prefixes it as #R-*)."
        ),
        safety="safe_write",
        handler=propose_reminder,
    )
    registry.register(
        name="propose_idea",
        description=(
            "Create an idea immediately. "
            "Requires: title (str). "
            "Optional: description, category (str, default 'general'), tags, "
            "reference_tag (short semantic slug, e.g. 'venue-idea'; system prefixes it as #I-*)."
        ),
        safety="safe_write",
        handler=propose_idea,
    )

    return registry
