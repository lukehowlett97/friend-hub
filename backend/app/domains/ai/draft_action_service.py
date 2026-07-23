"""Service layer for AI Draft Actions.

Owns validation, lifecycle transitions, and — on accept — the creation of the
real canonical domain rows (Poll + PollOptions, Event, or Reminder) plus their
hub_items mirror row.

The creation logic mirrors the router handlers (create_poll / create_event /
create_reminder in api/v1/router.py) but lives here so it can be called without
a FastAPI request context and without broadcasting notifications (those remain a
caller responsibility, e.g. an API endpoint can fire a background task after this
service returns).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.ai.draft_action_repository import AIDraftActionRepository
from app.models.ai_draft_action import AIDraftAction
from app.models.event import Event
from app.models.hub_item import HubItem, HubItemStatus
from app.models.note import Note
from app.models.planning import Poll, PollOption, PollVoteMode, Reminder, ReminderAssignee
from app.models.message import User
from app.models.room import DEFAULT_ROOM_ID

# ── Domain exceptions ─────────────────────────────────────────────────────────


class DraftActionError(Exception):
    """Base class for draft action domain errors."""
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


class DraftActionNotFoundError(DraftActionError):
    def __init__(self, draft_id=None):
        msg = f"Draft action not found" if draft_id is None else f"Draft action {draft_id} not found"
        super().__init__(msg, status_code=404)


class DraftActionInvalidStatusError(DraftActionError):
    """Raised when a lifecycle transition is not permitted for the current status."""
    def __init__(self, current_status: str, attempted: str):
        super().__init__(
            f"Cannot {attempted} a draft action with status '{current_status}'",
            status_code=409,
        )


class DraftActionValidationError(DraftActionError):
    """Raised when payload or field validation fails."""
    def __init__(self, message: str):
        super().__init__(message, status_code=422)


# ── Constants ─────────────────────────────────────────────────────────────────

VALID_ITEM_TYPES = {"event", "poll", "reminder", "note"}

HUB_ITEM_PREFIXES = {
    "poll": "P",
    "event": "E",
    "reminder": "R",
    "note": "N",
}

# ── Helpers ───────────────────────────────────────────────────────────────────


def _parse_datetime(value: str | datetime | None, field: str) -> datetime | None:
    """Parse an ISO-8601 string or passthrough a datetime. Returns None for None input."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            raise DraftActionValidationError(f"'{field}' is not a valid ISO-8601 datetime: {value!r}")
    # Normalise to naive UTC (matches existing router convention via _to_utc_naive)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


async def _next_hub_item_sequence(db: AsyncSession, item_type: str) -> int:
    """Return the next type_sequence value for a given hub item type."""
    result = await db.execute(
        select(func.max(HubItem.type_sequence)).where(HubItem.item_type == item_type)
    )
    return (result.scalar() or 0) + 1


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
) -> HubItem:
    """Create the hub_items mirror row for a newly created canonical domain row.

    Uses source_id as type_sequence (matching the existing convention in router.py
    _hub_item_for_source), so the short_id is deterministic and stable.
    """
    item = HubItem(
        group_id=group_id,
        room_id=DEFAULT_ROOM_ID,
        item_type=item_type,
        type_sequence=source_id,
        short_id=f"#{HUB_ITEM_PREFIXES[item_type]}-{source_id}",
        source_type=item_type,
        source_id=source_id,
        title=title[:220],
        body=body,
        tags=tags or [],
        status=HubItemStatus.open.value,
        created_by_user_id=created_by_user_id,
        due_at=due_at,
        event_start_at=event_start_at,
    )
    db.add(item)
    return item


# ── Payload validators ────────────────────────────────────────────────────────


def _validate_poll_payload(payload: dict) -> None:
    question = payload.get("question") or payload.get("title")
    if not question or not str(question).strip():
        raise DraftActionValidationError("Poll payload must include a non-empty 'question'")

    options = payload.get("options")
    if not isinstance(options, list):
        raise DraftActionValidationError("Poll payload 'options' must be a list")

    clean_options = [str(o).strip() for o in options if str(o).strip()]
    if len(clean_options) < 2:
        raise DraftActionValidationError(
            f"Poll payload requires at least 2 non-empty options, got {len(clean_options)}"
        )

    closes_at = payload.get("closes_at")
    if closes_at is not None:
        _parse_datetime(closes_at, "closes_at")  # validates format; result discarded here


def _validate_event_payload(payload: dict) -> None:
    title = payload.get("title")
    if not title or not str(title).strip():
        raise DraftActionValidationError("Event payload must include a non-empty 'title'")

    starts_at = payload.get("starts_at")
    if not starts_at:
        raise DraftActionValidationError("Event payload must include 'starts_at'")
    _parse_datetime(starts_at, "starts_at")  # validates format


def _validate_reminder_payload(payload: dict) -> None:
    title = payload.get("title") or payload.get("text")
    if not title or not str(title).strip():
        raise DraftActionValidationError("Reminder payload must include a non-empty 'title'")

    remind_at = payload.get("remind_at")
    if not remind_at:
        raise DraftActionValidationError("Reminder payload must include 'remind_at'")
    _parse_datetime(remind_at, "remind_at")  # validates format


def _validate_note_payload(payload: dict) -> None:
    title = payload.get("title")
    if not title or not str(title).strip():
        raise DraftActionValidationError("Note payload must include a non-empty 'title'")
    edit_mode = str(payload.get("edit_mode") or "owner_only").strip().lower()
    if edit_mode not in {"owner_only", "collaborative", "append_only"}:
        raise DraftActionValidationError("Note payload edit_mode is invalid")
    note_type = str(payload.get("note_type") or "general").strip().lower()
    if note_type not in {"general", "idea", "memory", "story", "plan", "recommendation", "rule"}:
        raise DraftActionValidationError("Note payload note_type is invalid")


_PAYLOAD_VALIDATORS = {
    "poll": _validate_poll_payload,
    "event": _validate_event_payload,
    "reminder": _validate_reminder_payload,
    "note": _validate_note_payload,
}


# ── Service ───────────────────────────────────────────────────────────────────


class DraftActionService:
    """Service layer for AI Draft Actions.

    All public methods receive an AsyncSession and coordinate through
    AIDraftActionRepository. The session is NOT committed here — callers own
    the transaction boundary.
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = AIDraftActionRepository(db)

    # ── Validation ────────────────────────────────────────────────────────────

    def _validate_generic(self, item_type: str, title: str, payload_json: dict) -> None:
        if item_type not in VALID_ITEM_TYPES:
            raise DraftActionValidationError(
                f"item_type must be one of {sorted(VALID_ITEM_TYPES)}, got {item_type!r}"
            )
        if not title or not str(title).strip():
            raise DraftActionValidationError("title must not be blank")
        if not isinstance(payload_json, dict):
            raise DraftActionValidationError("payload_json must be a dict")

    def _validate_payload(self, item_type: str, payload_json: dict) -> None:
        _PAYLOAD_VALIDATORS[item_type](payload_json)

    # ── CRUD ──────────────────────────────────────────────────────────────────

    async def create_draft_action(
        self,
        group_id: int,
        created_by_user_id: uuid.UUID,
        item_type: str,
        title: str,
        payload_json: dict,
        summary: Optional[str] = None,
        source: str = "hub_lab",
        source_message_id: Optional[int] = None,
        agent_run_id: Optional[uuid.UUID] = None,
        proposed_by: str = "ai",
    ) -> AIDraftAction:
        """Validate and persist a new draft action. Status is always 'draft'."""
        self._validate_generic(item_type, title, payload_json)
        self._validate_payload(item_type, payload_json)

        return await self.repo.create(
            group_id=group_id,
            created_by_user_id=created_by_user_id,
            item_type=item_type,
            title=str(title).strip(),
            payload_json=payload_json,
            proposed_by=proposed_by,
            action_type="create_hub_item",
            summary=summary,
            source=source,
            source_message_id=source_message_id,
            agent_run_id=agent_run_id,
        )

    async def get_draft_action(
        self,
        draft_id: uuid.UUID,
        group_id: Optional[int] = None,
    ) -> Optional[AIDraftAction]:
        """Fetch a draft by id. Returns None if not found."""
        return await self.repo.get_by_id(draft_id, group_id=group_id)

    async def list_draft_actions(
        self,
        group_id: int,
        status: Optional[str] = None,
        item_type: Optional[str] = None,
        source: Optional[str] = None,
        limit: int = 20,
    ) -> List[AIDraftAction]:
        """List draft actions for a group with optional filters."""
        return await self.repo.list_by_group(
            group_id=group_id,
            status=status,
            item_type=item_type,
            source=source,
            limit=limit,
        )

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def reject_draft_action(
        self,
        draft_id: uuid.UUID,
        resolved_by_user_id: uuid.UUID,
        group_id: Optional[int] = None,
    ) -> AIDraftAction:
        """Reject a draft. Only drafts with status='draft' may be rejected.

        Does not create any canonical domain row.
        Raises DraftActionNotFoundError or DraftActionInvalidStatusError on failure.
        """
        draft = await self.repo.get_by_id(draft_id, group_id=group_id)
        if draft is None:
            raise DraftActionNotFoundError(draft_id)
        if draft.status != "draft":
            raise DraftActionInvalidStatusError(draft.status, "reject")

        updated = await self.repo.mark_rejected(draft_id, resolved_by_user_id=resolved_by_user_id)
        return updated

    async def accept_draft_action(
        self,
        draft_id: uuid.UUID,
        resolved_by_user_id: uuid.UUID,
        group_id: Optional[int] = None,
    ) -> AIDraftAction:
        """Accept a draft by creating the real canonical domain row(s).

        Fetches the draft, re-validates the payload, then dispatches to the
        appropriate type-specific creation method. Marks the draft as accepted
        only after the canonical rows are successfully created.

        Raises:
            DraftActionNotFoundError — draft does not exist
            DraftActionInvalidStatusError — draft is not in 'draft' status
            DraftActionValidationError — payload fails re-validation
        """
        draft = await self.repo.get_by_id(draft_id, group_id=group_id)
        if draft is None:
            raise DraftActionNotFoundError(draft_id)
        if draft.status != "draft":
            raise DraftActionInvalidStatusError(draft.status, "accept")

        # Re-validate payload before any writes
        self._validate_payload(draft.item_type, draft.payload_json)

        if draft.item_type == "poll":
            return await self._accept_poll(draft, resolved_by_user_id)
        if draft.item_type == "event":
            return await self._accept_event(draft, resolved_by_user_id)
        if draft.item_type == "reminder":
            return await self._accept_reminder(draft, resolved_by_user_id)
        if draft.item_type == "note":
            return await self._accept_note(draft, resolved_by_user_id)

        # Guard: schema CHECK constraint makes this unreachable in practice
        raise DraftActionValidationError(f"Unknown item_type: {draft.item_type!r}")

    # ── Type-specific accept handlers ─────────────────────────────────────────

    async def _accept_poll(
        self, draft: AIDraftAction, resolved_by_user_id: uuid.UUID
    ) -> AIDraftAction:
        payload = draft.payload_json
        question = str(draft.title or payload.get("question") or payload.get("title")).strip()
        raw_options = payload.get("options", [])
        clean_options = list(dict.fromkeys(str(o).strip() for o in raw_options if str(o).strip()))

        vote_mode_raw = str(payload.get("vote_mode", "single")).strip().lower()
        try:
            vote_mode = PollVoteMode(vote_mode_raw)
        except ValueError:
            vote_mode = PollVoteMode.single

        closes_at = _parse_datetime(payload.get("closes_at"), "closes_at")

        poll = Poll(
            group_id=draft.group_id,
            room_id=DEFAULT_ROOM_ID,
            question=question[:220],
            vote_mode=vote_mode,
            deadline_at=closes_at,
            created_by_user_id=resolved_by_user_id,
        )
        self.db.add(poll)
        await self.db.flush()  # assigns poll.id

        for index, label in enumerate(clean_options):
            self.db.add(PollOption(poll_id=poll.id, label=label[:160], position=index))

        hub_item = await _create_hub_item_mirror(
            self.db,
            group_id=draft.group_id,
            item_type="poll",
            source_id=poll.id,
            title=question,
            tags=payload.get("tags") or [],
            created_by_user_id=resolved_by_user_id,
            due_at=closes_at,
        )
        await self.db.flush()

        return await self.repo.mark_accepted(
            draft.id,
            resolved_by_user_id=resolved_by_user_id,
            created_hub_item_id=hub_item.id,
            created_poll_id=poll.id,
        )

    async def _accept_event(
        self, draft: AIDraftAction, resolved_by_user_id: uuid.UUID
    ) -> AIDraftAction:
        payload = draft.payload_json
        title = str(draft.title or payload.get("title")).strip()
        starts_at = _parse_datetime(payload.get("starts_at"), "starts_at")
        description = payload.get("description") or None
        location = payload.get("location") or None

        event = Event(
            group_id=draft.group_id,
            room_id=DEFAULT_ROOM_ID,
            title=title[:120],
            description=str(description)[:2000] if description else None,
            location=str(location)[:160] if location else None,
            starts_at=starts_at,
            created_by_session_id=None,
        )
        self.db.add(event)
        await self.db.flush()  # assigns event.id

        hub_item = await _create_hub_item_mirror(
            self.db,
            group_id=draft.group_id,
            item_type="event",
            source_id=event.id,
            title=title,
            body=description,
            tags=payload.get("tags") or [],
            created_by_user_id=resolved_by_user_id,
            event_start_at=starts_at,
        )
        await self.db.flush()

        return await self.repo.mark_accepted(
            draft.id,
            resolved_by_user_id=resolved_by_user_id,
            created_hub_item_id=hub_item.id,
            created_event_id=event.id,
        )

    async def _accept_reminder(
        self, draft: AIDraftAction, resolved_by_user_id: uuid.UUID
    ) -> AIDraftAction:
        payload = draft.payload_json
        text = str(draft.title or payload.get("title") or payload.get("text")).strip()
        context = str(payload.get("context") or "").strip()[:2000] or None
        remind_at = _parse_datetime(payload.get("remind_at"), "remind_at")
        target_user_ids: list = payload.get("target_user_ids") or []

        reminder = Reminder(
            group_id=draft.group_id,
            room_id=DEFAULT_ROOM_ID,
            text=text[:1000],
            context=context,
            due_at=remind_at,
            created_by_user_id=resolved_by_user_id,
        )
        self.db.add(reminder)
        await self.db.flush()  # assigns reminder.id

        # Add assignees: validate against users table then insert
        if target_user_ids:
            clean_ids = list(dict.fromkeys(str(uid) for uid in target_user_ids if uid))
            if clean_ids:
                valid_result = await self.db.execute(
                    select(User.id).where(User.id.in_(clean_ids))
                )
                for (uid,) in valid_result.fetchall():
                    self.db.add(ReminderAssignee(reminder_id=reminder.id, user_id=uid))

        hub_item = await _create_hub_item_mirror(
            self.db,
            group_id=draft.group_id,
            item_type="reminder",
            source_id=reminder.id,
            title=text[:220],
            body=context,
            tags=payload.get("tags") or [],
            created_by_user_id=resolved_by_user_id,
            due_at=remind_at,
        )
        await self.db.flush()

        return await self.repo.mark_accepted(
            draft.id,
            resolved_by_user_id=resolved_by_user_id,
            created_hub_item_id=hub_item.id,
            created_reminder_id=reminder.id,
        )

    async def _accept_note(
        self, draft: AIDraftAction, resolved_by_user_id: uuid.UUID
    ) -> AIDraftAction:
        from app.domains.notes.repository import NoteRepository

        payload = draft.payload_json
        title = str(draft.title or payload.get("title")).strip()
        body = str(payload.get("body") or "").strip()[:20000]
        note_type = str(payload.get("note_type") or "general").strip().lower()
        edit_mode = str(payload.get("edit_mode") or "owner_only").strip().lower()
        room_id = getattr(draft, "room_id", None) or DEFAULT_ROOM_ID
        sequence = await NoteRepository(self.db).next_room_sequence(room_id)
        note = Note(
            group_id=draft.group_id,
            room_id=room_id,
            room_sequence=sequence,
            title=title[:220],
            body=body,
            note_type=note_type,
            edit_mode=edit_mode,
            created_by_user_id=resolved_by_user_id,
        )
        self.db.add(note)
        await self.db.flush()
        hub_item = HubItem(
            group_id=draft.group_id,
            room_id=room_id,
            item_type="note",
            source_type="note",
            source_id=note.id,
            type_sequence=note.room_sequence,
            short_id=f"#N-{note.room_sequence}",
            title=note.title,
            body=note.body,
            tags=[note.note_type] if note.note_type != "general" else [],
            status=HubItemStatus.open.value,
            created_by_user_id=resolved_by_user_id,
        )
        self.db.add(hub_item)
        await self.db.flush()
        return await self.repo.mark_accepted(
            draft.id,
            resolved_by_user_id=resolved_by_user_id,
            created_hub_item_id=hub_item.id,
        )
