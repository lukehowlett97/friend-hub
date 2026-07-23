"""
Context builders for Hub Bot — turns live DB state into compact text blocks
that can be injected into the LLM prompt so the bot stops hallucinating
hub item IDs, deadlines, options, and member identities.
"""
from datetime import datetime, timedelta

from sqlalchemy import and_, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.hub_items.references import find_hub_item_references
from app.models.event import Event
from app.models.hub_item import HubItem, HubItemStatus
from app.models.message import User
from app.models.planning import Poll, PollOption, PollStatus

UPCOMING_EVENT_DAYS = 14
ACTIVE_USER_DAYS = 30
OPEN_HUB_ITEM_LIMIT = 5


def _fmt_dt(value: datetime | None) -> str:
    if not value:
        return "—"
    return value.strftime("%Y-%m-%d %H:%M")


async def build_world_snapshot(db: AsyncSession) -> str:
    """One-line-per-item summary of currently relevant hub items."""
    now = datetime.utcnow()
    sections: list[str] = []

    poll_lines = await _live_poll_lines(db)
    if poll_lines:
        sections.append("Live / scheduled polls:\n" + "\n".join(poll_lines))

    event_lines = await _upcoming_event_lines(db, now)
    if event_lines:
        sections.append(
            f"Upcoming events (next {UPCOMING_EVENT_DAYS} days):\n" + "\n".join(event_lines)
        )

    idea_lines = await _open_hub_item_lines(db, "idea")
    if idea_lines:
        sections.append("Open ideas:\n" + "\n".join(idea_lines))

    reminder_lines = await _open_hub_item_lines(db, "reminder")
    if reminder_lines:
        sections.append("Open reminders:\n" + "\n".join(reminder_lines))

    if not sections:
        return "Active hub items: (none)"

    return "Active hub items:\n" + "\n\n".join(sections)


async def resolve_referenced_items(db: AsyncSession, prompt: str) -> str:
    """If the user's prompt mentions #X-N short IDs, return their full details."""
    refs = find_hub_item_references(prompt)
    if not refs:
        return ""

    short_ids = list({r["short_id"] for r in refs})
    result = await db.execute(
        select(HubItem).where(
            and_(HubItem.short_id.in_(short_ids), HubItem.archived_at.is_(None))
        )
    )
    items = result.scalars().all()
    if not items:
        return ""

    blocks: list[str] = []
    for item in items:
        blocks.append(await _detailed_item_block(db, item))

    return "Referenced items (use these exact details, do not invent):\n" + "\n\n".join(blocks)


async def build_member_context(db: AsyncSession) -> str:
    """Active human members with nicknames and display roles."""
    cutoff = datetime.utcnow() - timedelta(days=ACTIVE_USER_DAYS)
    result = await db.execute(
        select(User)
        .where(and_(User.is_bot.is_(False), User.last_seen >= cutoff))
        .order_by(User.nickname)
    )
    users = result.scalars().all()
    if not users:
        return ""

    lines = []
    for u in users:
        parts = [u.nickname]
        if u.display_role:
            parts.append(f"role: {u.display_role}")
        if u.bio:
            bio = u.bio.strip().replace("\n", " ")
            if len(bio) > 80:
                bio = bio[:77] + "..."
            parts.append(f"bio: {bio}")
        lines.append("- " + " · ".join(parts))

    return "Group members (active in last 30 days):\n" + "\n".join(lines)


# ── Internals ───────────────────────────────────────────────────────────────


async def _live_poll_lines(db: AsyncSession) -> list[str]:
    result = await db.execute(
        select(Poll, HubItem)
        .join(
            HubItem,
            and_(
                HubItem.source_type == "poll",
                HubItem.source_id == Poll.id,
                HubItem.archived_at.is_(None),
            ),
        )
        .where(
            and_(
                Poll.archived_at.is_(None),
                Poll.status.in_([PollStatus.live.value, PollStatus.scheduled.value]),
            )
        )
        .order_by(Poll.deadline_at.asc().nullslast())
    )
    rows = result.all()
    if not rows:
        return []

    poll_ids = [poll.id for poll, _ in rows]
    options_result = await db.execute(
        select(PollOption)
        .where(PollOption.poll_id.in_(poll_ids))
        .order_by(PollOption.poll_id, PollOption.position)
    )
    options_by_poll: dict[int, list[str]] = {}
    for opt in options_result.scalars().all():
        options_by_poll.setdefault(opt.poll_id, []).append(opt.label)

    lines = []
    for poll, hub_item in rows:
        opts = ", ".join(options_by_poll.get(poll.id, [])) or "(no options)"
        window = (
            f"voting {_fmt_dt(poll.voting_opens_at)} → {_fmt_dt(poll.deadline_at)}"
        )
        lines.append(
            f"- {hub_item.short_id} [{poll.status}] \"{hub_item.title}\" — "
            f"{window}; options: {opts}"
        )
    return lines


async def _upcoming_event_lines(db: AsyncSession, now: datetime) -> list[str]:
    horizon = now + timedelta(days=UPCOMING_EVENT_DAYS)
    result = await db.execute(
        select(Event, HubItem)
        .join(
            HubItem,
            and_(
                HubItem.source_type == "event",
                HubItem.source_id == Event.id,
                HubItem.archived_at.is_(None),
            ),
        )
        .where(
            and_(
                Event.archived_at.is_(None),
                Event.starts_at >= now,
                Event.starts_at < horizon,
            )
        )
        .order_by(Event.starts_at.asc())
    )
    lines = []
    for event, hub_item in result.all():
        loc = f" @ {event.location}" if event.location else ""
        lines.append(
            f"- {hub_item.short_id} \"{hub_item.title}\" — {_fmt_dt(event.starts_at)}{loc}"
        )
    return lines


async def _open_hub_item_lines(db: AsyncSession, item_type: str) -> list[str]:
    result = await db.execute(
        select(HubItem)
        .where(
            and_(
                HubItem.item_type == item_type,
                HubItem.status == HubItemStatus.open.value,
                HubItem.archived_at.is_(None),
            )
        )
        .order_by(desc(HubItem.created_at))
        .limit(OPEN_HUB_ITEM_LIMIT)
    )
    lines = []
    for item in result.scalars().all():
        due = f" (due {_fmt_dt(item.due_at)})" if item.due_at else ""
        lines.append(f"- {item.short_id} \"{item.title}\"{due}")
    return lines


async def _detailed_item_block(db: AsyncSession, item: HubItem) -> str:
    parts = [f"{item.short_id} [{item.item_type}] \"{item.title}\""]
    if item.body:
        body = item.body.strip()
        if len(body) > 600:
            body = body[:597] + "..."
        parts.append(f"description: {body}")

    if item.item_type == "poll" and item.source_id is not None:
        poll = await db.get(Poll, item.source_id)
        if poll:
            parts.append(f"status: {poll.status or 'unknown'}")
            parts.append(
                f"voting: {_fmt_dt(poll.voting_opens_at)} → {_fmt_dt(poll.deadline_at)}"
            )
            opt_result = await db.execute(
                select(PollOption)
                .where(PollOption.poll_id == poll.id)
                .order_by(PollOption.position)
            )
            opts = [o.label for o in opt_result.scalars().all()]
            if opts:
                parts.append("options: " + ", ".join(opts))

    elif item.item_type == "event" and item.source_id is not None:
        event = await db.get(Event, item.source_id)
        if event:
            parts.append(f"starts: {_fmt_dt(event.starts_at)}")
            if event.location:
                parts.append(f"location: {event.location}")

    elif item.due_at:
        parts.append(f"due: {_fmt_dt(item.due_at)}")

    return "\n".join(parts)
