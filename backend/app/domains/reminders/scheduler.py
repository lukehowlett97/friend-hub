"""
Reminder scheduler — fires due reminders via Hub Bot.

Runs as a single asyncio background task started at app startup.
Every 60 seconds it queries for due reminders, fires them, and advances
recurring reminders to their next due_at without marking them complete.
"""
import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hub_item import HubItem
from app.models.planning import Reminder, ReminderAssignee
from app.models.message import User

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 60


async def _advance_due_at(reminder: Reminder) -> datetime | None:
    """Return the next due_at for a recurring reminder, or None if the series is over."""
    if not reminder.due_at or not reminder.recurrence:
        return None

    now = datetime.utcnow()
    base = reminder.due_at if reminder.due_at.tzinfo is None else reminder.due_at.replace(tzinfo=None)

    if reminder.recurrence == "daily":
        delta = timedelta(days=1)
    elif reminder.recurrence == "weekly":
        delta = timedelta(weeks=1)
    elif reminder.recurrence == "every_N_days":
        days = reminder.recurrence_days or 1
        delta = timedelta(days=days)
    else:
        return None

    next_due = base + delta
    # Skip forward past any already-elapsed intervals (handles missed ticks)
    while next_due <= now:
        next_due += delta

    # Check whether the series has expired
    if reminder.recurrence_ends_at:
        ends = reminder.recurrence_ends_at
        if ends.tzinfo is not None:
            ends = ends.replace(tzinfo=None)
        if next_due > ends:
            return None

    return next_due


async def _fire_reminder(db: AsyncSession, reminder: Reminder) -> None:
    """Generate a Hub Bot chat message for a triggered reminder."""
    from app.ai.bot import hub_bot

    # Fetch assignee display names
    assignee_result = await db.execute(
        select(User.nickname)
        .join(ReminderAssignee, ReminderAssignee.user_id == User.id)
        .where(ReminderAssignee.reminder_id == reminder.id)
    )
    assignee_names = [row[0] for row in assignee_result.fetchall()]

    # Build the message via Hub Bot
    from app.models.database import async_session_factory
    from app.api.v1.router import get_connection_manager

    manager = get_connection_manager()
    if manager is None:
        logger.warning("Reminder scheduler: no connection manager, skipping fire for reminder %d", reminder.id)
        return

    room_id = reminder.room_id

    # Try LLM-generated message, fall back to simple format
    reply = await _generate_reminder_message(reminder, assignee_names)
    reply = _append_reminder_reference(reply, await _reminder_short_ref(db, reminder))

    async with async_session_factory() as post_db:
        await hub_bot._post_response(reply, post_db, manager, room_id=room_id)

    # In-app bell + real-time WS + push for assignees who have reminders enabled
    await _notify_reminder_assignees(db, reminder, manager)


async def _generate_reminder_message(reminder: Reminder, assignee_names: list[str]) -> str:
    """Ask the LLM to write a friendly reminder message, with a simple fallback."""
    from app.config import get_settings
    from app.domains.ai.summary_service import create_llm_client

    settings = get_settings()
    context = _reminder_context(reminder)
    if not settings.ai_api_key:
        return _simple_reminder_message(reminder, assignee_names)

    try:
        llm = create_llm_client()
        if not hasattr(llm, "_get_provider"):
            return _simple_reminder_message(reminder, assignee_names)

        recurrence_note = ""
        if reminder.recurrence:
            recurrence_note = f" (This is a {reminder.recurrence.replace('_', ' ')} reminder.)"

        system = (
            "You are Hub Bot inside Friend Hub. A scheduled reminder has just fired. "
            "Write a single short, friendly chat message to notify the group. "
            "Treat the reminder title as the thing to remember. "
            "If reminder context is provided, incorporate its useful details into the message; "
            "do not ignore it, and do not dump it verbatim unless the wording is already concise. "
            "Mention the assigned users by name if any are provided. "
            "Do not include the reminder reference tag; the system appends it. "
            "Do not use markdown. Do not start with 'Hub Bot:'. Keep it to 1-2 sentences."
        )
        user = (
            f"Reminder title: {reminder.text}{recurrence_note}\n"
            f"Reminder context (must influence the response when provided): {context or 'none provided'}\n"
            f"Assigned to: {', '.join(assignee_names) if assignee_names else 'the group'}"
        )
        provider = llm._get_provider()
        raw, _, _ = await provider.complete_chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            llm.model,
            temperature=0.4,
        )
        text = (raw or "").strip()
        if text:
            return text
    except Exception as exc:
        logger.warning("Reminder LLM generation failed, using fallback: %s", exc)

    return _simple_reminder_message(reminder, assignee_names)


async def _reminder_short_ref(db: AsyncSession, reminder: Reminder) -> str | None:
    """Resolve the clickable Hub Item reference for a reminder."""
    result = await db.execute(
        select(HubItem.short_id).where(
            HubItem.source_type == "reminder",
            HubItem.source_id == reminder.id,
        )
    )
    short_id = result.scalar_one_or_none()
    if short_id:
        return short_id
    if getattr(reminder, "id", None):
        return f"#R-{reminder.id}"
    return None


def _append_reminder_reference(message: str, short_ref: str | None) -> str:
    """Append the clickable reminder reference exactly once at the end."""
    text = (message or "").strip()
    ref = (short_ref or "").strip()
    if not text or not ref:
        return text
    if text.endswith(ref):
        return text
    return f"{text} {ref}"


def _reminder_context(reminder: Reminder) -> str:
    """Return normalized reminder context suitable for chat/LLM output."""
    return (reminder.context or "").strip()


def _simple_reminder_message(reminder: Reminder, assignee_names: list[str]) -> str:
    """Plain fallback when LLM is unavailable."""
    mentions = " ".join(f"@{n}" for n in assignee_names)
    prefix = f"{mentions} — " if mentions else ""
    context = _reminder_context(reminder)
    suffix = f" — {context}" if context else ""
    return f"⏰ {prefix}Reminder: {reminder.text}{suffix}"


async def _notify_reminder_assignees(
    db: AsyncSession,
    reminder: Reminder,
    manager,
) -> None:
    """Notify assigned users when a reminder fires.

    Creates an in-app bell row, sends a real-time WS event to live tabs, and
    fans out web push — all gated on the user's `reminders` preference.
    """
    try:
        from app.domains.chat.events import OutgoingNotification
        from app.domains.notifications.push_fanout import fanout_push_to_user_if_allowed
        from app.models.notification import Notification
        from app.models.notification_preference import NotificationPreference

        assignee_result = await db.execute(
            select(ReminderAssignee.user_id)
            .where(ReminderAssignee.reminder_id == reminder.id)
        )
        user_ids = [row[0] for row in assignee_result.fetchall()]
        if not user_ids:
            return

        title = "Reminder"
        body = reminder.text[:120]

        for user_id in user_ids:
            pref_result = await db.execute(
                select(NotificationPreference).where(NotificationPreference.user_id == user_id)
            )
            pref = pref_result.scalar_one_or_none()
            if pref and not pref.reminders:
                continue

            notif = Notification(
                user_id=user_id,
                type="reminder",
                title=title,
                body=body,
                target_type="reminder",
                target_id=reminder.id,
                room_id=reminder.room_id,
            )
            db.add(notif)
            await db.flush()

            if manager is not None:
                await manager.send_to_user_by_id(
                    str(user_id),
                    OutgoingNotification(
                        notification_id=notif.id,
                        notif_type="reminder",
                        title=title,
                        body=body,
                        target_type="reminder",
                        target_id=reminder.id,
                    ).dict(),
                )

            await fanout_push_to_user_if_allowed(
                db,
                user_id=user_id,
                notif_type="reminders",
                title=title,
                body=body,
                url="/reminders",
                data={"notif_type": "reminder", "target_type": "reminder", "target_id": reminder.id},
            )

        await db.commit()
    except Exception as exc:
        logger.warning("Reminder notification failed: %s", exc)


async def _tick(db: AsyncSession) -> None:
    """Single scheduler tick — find and fire all due reminders.

    Guard against double-firing:
    1. Query excludes any reminder where last_triggered_at is within the
       last POLL_INTERVAL_SECONDS seconds (already claimed this tick).
    2. We commit the state advance BEFORE posting the chat message, so a
       concurrent or slow tick cannot pick the same reminder up again.
    """
    now = datetime.utcnow()
    # Reminders triggered within the last poll window are skipped — they
    # are either being processed right now or already fired this cycle.
    claim_cutoff = now - timedelta(seconds=POLL_INTERVAL_SECONDS)

    result = await db.execute(
        select(Reminder).where(
            Reminder.due_at <= now,
            Reminder.is_completed.is_(False),
            Reminder.archived_at.is_(None),
            # Not already claimed in this window
            (Reminder.last_triggered_at.is_(None) | (Reminder.last_triggered_at < claim_cutoff)),
        )
    )
    due = result.scalars().all()

    for reminder in due:
        # ── Step 1: claim by advancing state in DB first ─────────────────
        next_due = await _advance_due_at(reminder)
        reminder.last_triggered_at = now

        if next_due is not None:
            reminder.due_at = next_due
        elif not reminder.recurrence:
            reminder.is_completed = True
            reminder.completed_at = now
        else:
            reminder.archived_at = now

        try:
            await db.commit()
        except Exception as exc:
            logger.error("Failed to claim reminder %d, skipping fire: %s", reminder.id, exc)
            await db.rollback()
            continue

        # ── Step 2: fire (LLM + chat post + push) ────────────────────────
        try:
            await _fire_reminder(db, reminder)
        except Exception as exc:
            logger.error("Failed to fire reminder %d: %s", reminder.id, exc)


async def run_reminder_scheduler() -> None:
    """Long-running background coroutine. Start once at app startup."""
    from app.models.database import async_session_factory

    logger.info("Reminder scheduler started (poll interval: %ds)", POLL_INTERVAL_SECONDS)
    while True:
        try:
            async with async_session_factory() as db:
                await _tick(db)
        except Exception as exc:
            logger.error("Reminder scheduler tick error: %s", exc)
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
