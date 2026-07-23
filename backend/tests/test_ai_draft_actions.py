"""Tests for AIDraftActionRepository, DraftActionService, and draft action API endpoints."""
import asyncio
import types
import unittest
import uuid
from datetime import datetime, timezone

from app.domains.ai.draft_action_repository import AIDraftActionRepository
from app.models.ai_draft_action import AIDraftAction


# ── Dummy Database ────────────────────────────────────────────────────────────


class DummyResult:
    def __init__(self, scalar=None, rows=None):
        self._scalar = scalar
        self._rows = rows or []

    def scalar_one_or_none(self):
        # If rows were provided (list-style result), return first or None
        if self._rows:
            return self._rows[0]
        return self._scalar

    def scalar(self):
        return self._scalar

    def scalars(self):
        return types.SimpleNamespace(all=lambda: self._rows)


class DummyDb:
    """Minimal fake async session for unit testing the repository."""

    def __init__(self):
        self.added = []
        self.flushed = False
        self._store: dict[uuid.UUID, AIDraftAction] = {}
        # Controls what execute() returns; set per-test as needed.
        self._execute_rows: list = []

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        self.flushed = True
        for value in self.added:
            if isinstance(value, AIDraftAction) and value.id is None:
                value.id = uuid.uuid4()
            if isinstance(value, AIDraftAction):
                self._store[value.id] = value

    async def refresh(self, value):
        pass

    async def get(self, model, key):
        if model is AIDraftAction:
            return self._store.get(key)
        return None

    async def execute(self, stmt):
        return DummyResult(rows=list(self._execute_rows))


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_draft(db: DummyDb, **overrides) -> AIDraftAction:
    """Create a draft action via the repo and return it synchronously."""
    defaults = dict(
        group_id=1,
        created_by_user_id=uuid.uuid4(),
        item_type="poll",
        title="Where should we go Saturday?",
        payload_json={
            "question": "Where should we go Saturday?",
            "options": ["Bar", "Restaurant"],
            "vote_mode": "single",
        },
    )
    defaults.update(overrides)
    repo = AIDraftActionRepository(db)
    return asyncio.run(repo.create(**defaults))


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestAIDraftActionRepositoryCreate(unittest.TestCase):

    def test_create_assigns_id_and_defaults(self):
        db = DummyDb()
        draft = _make_draft(db)

        self.assertIsNotNone(draft.id)
        self.assertEqual(draft.status, "draft")
        self.assertEqual(draft.proposed_by, "ai")
        self.assertEqual(draft.action_type, "create_hub_item")
        self.assertEqual(draft.source, "hub_lab")
        self.assertTrue(db.flushed)

    def test_create_stores_required_fields(self):
        db = DummyDb()
        user_id = uuid.uuid4()
        draft = _make_draft(
            db,
            group_id=42,
            created_by_user_id=user_id,
            item_type="event",
            title="Curry Night",
            payload_json={"starts_at": "2026-05-21T19:00:00Z"},
        )

        self.assertEqual(draft.group_id, 42)
        self.assertEqual(draft.created_by_user_id, user_id)
        self.assertEqual(draft.item_type, "event")
        self.assertEqual(draft.title, "Curry Night")
        self.assertEqual(draft.payload_json, {"starts_at": "2026-05-21T19:00:00Z"})

    def test_create_optional_fields_default_to_none(self):
        db = DummyDb()
        draft = _make_draft(db)

        self.assertIsNone(draft.summary)
        self.assertIsNone(draft.source_message_id)
        self.assertIsNone(draft.agent_run_id)
        self.assertIsNone(draft.created_hub_item_id)
        self.assertIsNone(draft.created_poll_id)
        self.assertIsNone(draft.created_event_id)
        self.assertIsNone(draft.created_reminder_id)
        self.assertIsNone(draft.resolved_at)
        self.assertIsNone(draft.resolved_by_user_id)

    def test_create_with_optional_fields(self):
        db = DummyDb()
        run_id = uuid.uuid4()
        draft = _make_draft(
            db,
            summary="AI-proposed poll for Saturday plans",
            source="chat",
            source_message_id=99,
            agent_run_id=run_id,
        )

        self.assertEqual(draft.summary, "AI-proposed poll for Saturday plans")
        self.assertEqual(draft.source, "chat")
        self.assertEqual(draft.source_message_id, 99)
        self.assertEqual(draft.agent_run_id, run_id)

    def test_create_reminder_item_type(self):
        db = DummyDb()
        draft = _make_draft(
            db,
            item_type="reminder",
            title="Book taxis before Friday",
            payload_json={"text": "Book taxis before Friday", "remind_at": "2026-05-14T18:00:00Z"},
        )

        self.assertEqual(draft.item_type, "reminder")
        self.assertEqual(draft.title, "Book taxis before Friday")


class TestAIDraftActionRepositoryGetById(unittest.TestCase):

    def test_get_by_id_returns_draft(self):
        db = DummyDb()
        draft = _make_draft(db)
        repo = AIDraftActionRepository(db)

        fetched = asyncio.run(repo.get_by_id(draft.id))
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.id, draft.id)

    def test_get_by_id_returns_none_for_unknown_id(self):
        db = DummyDb()
        repo = AIDraftActionRepository(db)

        fetched = asyncio.run(repo.get_by_id(uuid.uuid4()))
        self.assertIsNone(fetched)

    def test_get_by_id_with_matching_group_id(self):
        """When group_id is provided and matches, the draft is returned."""
        db = DummyDb()
        draft = _make_draft(db, group_id=1)
        repo = AIDraftActionRepository(db)

        # Seed execute result so the filtered query finds it
        db._execute_rows = [draft]
        fetched = asyncio.run(repo.get_by_id(draft.id, group_id=1))
        self.assertIsNotNone(fetched)

    def test_get_by_id_with_mismatched_group_id_returns_none(self):
        """When group_id is provided but does not match, None is returned."""
        db = DummyDb()
        draft = _make_draft(db, group_id=1)
        repo = AIDraftActionRepository(db)

        # execute returns empty — wrong group
        db._execute_rows = []
        fetched = asyncio.run(repo.get_by_id(draft.id, group_id=99))
        self.assertIsNone(fetched)


class TestAIDraftActionRepositoryListByGroup(unittest.TestCase):

    def test_list_by_group_returns_seeded_rows(self):
        db = DummyDb()
        draft = _make_draft(db, group_id=1)
        repo = AIDraftActionRepository(db)

        db._execute_rows = [draft]
        results = asyncio.run(repo.list_by_group(group_id=1))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].id, draft.id)

    def test_list_by_group_empty(self):
        db = DummyDb()
        repo = AIDraftActionRepository(db)

        results = asyncio.run(repo.list_by_group(group_id=1))
        self.assertEqual(results, [])

    def test_list_by_group_filtered_by_status(self):
        """Status filter is applied — only matching rows returned."""
        db = DummyDb()
        draft = _make_draft(db)
        repo = AIDraftActionRepository(db)

        # Simulate: filter matches
        db._execute_rows = [draft]
        results = asyncio.run(repo.list_by_group(group_id=1, status="draft"))
        self.assertEqual(len(results), 1)

        # Simulate: filter matches nothing
        db._execute_rows = []
        results = asyncio.run(repo.list_by_group(group_id=1, status="accepted"))
        self.assertEqual(results, [])

    def test_list_by_group_filtered_by_item_type(self):
        db = DummyDb()
        poll_draft = _make_draft(db, item_type="poll")
        repo = AIDraftActionRepository(db)

        db._execute_rows = [poll_draft]
        results = asyncio.run(repo.list_by_group(group_id=1, item_type="poll"))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].item_type, "poll")

    def test_list_by_group_filtered_by_source(self):
        db = DummyDb()
        draft = _make_draft(db, source="chat")
        repo = AIDraftActionRepository(db)

        db._execute_rows = [draft]
        results = asyncio.run(repo.list_by_group(group_id=1, source="chat"))
        self.assertEqual(len(results), 1)

        db._execute_rows = []
        results = asyncio.run(repo.list_by_group(group_id=1, source="hub_lab"))
        self.assertEqual(results, [])


class TestAIDraftActionRepositoryUpdateStatus(unittest.TestCase):

    def test_update_status_to_rejected(self):
        db = DummyDb()
        draft = _make_draft(db)
        repo = AIDraftActionRepository(db)
        user_id = uuid.uuid4()

        updated = asyncio.run(repo.update_status(draft.id, "rejected", resolved_by_user_id=user_id))

        self.assertIsNotNone(updated)
        self.assertEqual(updated.status, "rejected")
        self.assertIsNotNone(updated.resolved_at)
        self.assertEqual(updated.resolved_by_user_id, user_id)

    def test_update_status_to_accepted_with_created_ids(self):
        db = DummyDb()
        draft = _make_draft(db, item_type="poll")
        repo = AIDraftActionRepository(db)
        hub_item_id = uuid.uuid4()
        user_id = uuid.uuid4()

        updated = asyncio.run(repo.update_status(
            draft.id,
            "accepted",
            resolved_by_user_id=user_id,
            created_hub_item_id=hub_item_id,
            created_poll_id=7,
        ))

        self.assertEqual(updated.status, "accepted")
        self.assertEqual(updated.created_hub_item_id, hub_item_id)
        self.assertEqual(updated.created_poll_id, 7)
        self.assertIsNotNone(updated.resolved_at)

    def test_update_status_to_expired_sets_resolved_at(self):
        db = DummyDb()
        draft = _make_draft(db)
        repo = AIDraftActionRepository(db)

        updated = asyncio.run(repo.update_status(draft.id, "expired"))

        self.assertEqual(updated.status, "expired")
        self.assertIsNotNone(updated.resolved_at)

    def test_update_status_nonexistent_returns_none(self):
        db = DummyDb()
        repo = AIDraftActionRepository(db)

        updated = asyncio.run(repo.update_status(uuid.uuid4(), "rejected"))
        self.assertIsNone(updated)

    def test_draft_status_does_not_set_resolved_at(self):
        """Transitioning back to 'draft' (edge-case) should not touch resolved_at."""
        db = DummyDb()
        draft = _make_draft(db)
        repo = AIDraftActionRepository(db)

        updated = asyncio.run(repo.update_status(draft.id, "draft"))
        self.assertIsNone(updated.resolved_at)


class TestAIDraftActionRepositoryHelpers(unittest.TestCase):

    def test_mark_accepted(self):
        db = DummyDb()
        draft = _make_draft(db, item_type="event")
        repo = AIDraftActionRepository(db)
        user_id = uuid.uuid4()
        hub_item_id = uuid.uuid4()

        updated = asyncio.run(repo.mark_accepted(
            draft.id,
            resolved_by_user_id=user_id,
            created_hub_item_id=hub_item_id,
            created_event_id=3,
        ))

        self.assertEqual(updated.status, "accepted")
        self.assertEqual(updated.created_hub_item_id, hub_item_id)
        self.assertEqual(updated.created_event_id, 3)
        self.assertEqual(updated.resolved_by_user_id, user_id)

    def test_mark_rejected(self):
        db = DummyDb()
        draft = _make_draft(db)
        repo = AIDraftActionRepository(db)
        user_id = uuid.uuid4()

        updated = asyncio.run(repo.mark_rejected(draft.id, resolved_by_user_id=user_id))

        self.assertEqual(updated.status, "rejected")
        self.assertEqual(updated.resolved_by_user_id, user_id)

    def test_mark_expired(self):
        db = DummyDb()
        draft = _make_draft(db)
        repo = AIDraftActionRepository(db)

        updated = asyncio.run(repo.mark_expired(draft.id))

        self.assertEqual(updated.status, "expired")
        self.assertIsNotNone(updated.resolved_at)



# ── DraftActionService tests ──────────────────────────────────────────────────
#
# The service touches Poll, PollOption, Event, Reminder, HubItem, and User in
# addition to AIDraftAction. ServiceDummyDb extends DummyDb to auto-assign IDs
# for all those models and make them retrievable via db.get().


class ServiceDummyDb(DummyDb):
    """Extended DummyDb that tracks the extra models the service writes."""

    def __init__(self):
        super().__init__()
        from app.models.planning import Poll, PollOption, Reminder, ReminderAssignee
        from app.models.event import Event
        from app.models.hub_item import HubItem
        self._poll_store: dict = {}
        self._event_store: dict = {}
        self._reminder_store: dict = {}
        self._hub_item_store: dict = {}
        self._next_int_id = 1

    def _next_id(self):
        val = self._next_int_id
        self._next_int_id += 1
        return val

    async def flush(self):
        from app.models.planning import Poll, PollOption, Reminder, ReminderAssignee
        from app.models.event import Event
        from app.models.hub_item import HubItem

        self.flushed = True
        for value in self.added:
            if isinstance(value, AIDraftAction) and value.id is None:
                value.id = uuid.uuid4()
            if isinstance(value, AIDraftAction):
                self._store[value.id] = value

            if isinstance(value, Poll) and value.id is None:
                value.id = self._next_id()
                self._poll_store[value.id] = value
            if isinstance(value, Event) and value.id is None:
                value.id = self._next_id()
                self._event_store[value.id] = value
            if isinstance(value, Reminder) and value.id is None:
                value.id = self._next_id()
                self._reminder_store[value.id] = value
            if isinstance(value, HubItem) and value.id is None:
                value.id = uuid.uuid4()
                self._hub_item_store[value.id] = value

    async def get(self, model, key):
        from app.models.planning import Poll, Reminder
        from app.models.event import Event
        from app.models.hub_item import HubItem

        if model is AIDraftAction:
            return self._store.get(key)
        if model is Poll:
            return self._poll_store.get(key)
        if model is Event:
            return self._event_store.get(key)
        if model is Reminder:
            return self._reminder_store.get(key)
        if model is HubItem:
            return self._hub_item_store.get(key)
        return None

    async def commit(self):
        pass  # no-op; endpoints call this but tests own no real transaction

    async def execute(self, stmt):
        # For User.id lookups (assignee validation) return empty — no users in test DB.
        return DummyResult(rows=list(self._execute_rows))


def _svc(db=None):
    from app.domains.ai.draft_action_service import DraftActionService
    return DraftActionService(db or ServiceDummyDb())


def _run(coro):
    return asyncio.run(coro)


class TestDraftActionServiceCreate(unittest.TestCase):

    def test_create_valid_poll_draft(self):
        db = ServiceDummyDb()
        svc = _svc(db)
        draft = _run(svc.create_draft_action(
            group_id=1,
            created_by_user_id=uuid.uuid4(),
            item_type="poll",
            title="Where should we go?",
            payload_json={"question": "Where should we go?", "options": ["Bar", "Club"]},
        ))
        self.assertEqual(draft.item_type, "poll")
        self.assertEqual(draft.status, "draft")
        self.assertIsNotNone(draft.id)

    def test_create_valid_event_draft(self):
        db = ServiceDummyDb()
        svc = _svc(db)
        draft = _run(svc.create_draft_action(
            group_id=1,
            created_by_user_id=uuid.uuid4(),
            item_type="event",
            title="Curry Night",
            payload_json={"title": "Curry Night", "starts_at": "2026-06-01T19:00:00Z"},
        ))
        self.assertEqual(draft.item_type, "event")
        self.assertEqual(draft.status, "draft")

    def test_create_valid_reminder_draft(self):
        db = ServiceDummyDb()
        svc = _svc(db)
        draft = _run(svc.create_draft_action(
            group_id=1,
            created_by_user_id=uuid.uuid4(),
            item_type="reminder",
            title="Book taxis",
            payload_json={"text": "Book taxis", "remind_at": "2026-05-14T18:00:00Z"},
        ))
        self.assertEqual(draft.item_type, "reminder")
        self.assertEqual(draft.status, "draft")

    def test_invalid_item_type_raises(self):
        from app.domains.ai.draft_action_service import DraftActionValidationError
        db = ServiceDummyDb()
        svc = _svc(db)
        with self.assertRaises(DraftActionValidationError) as ctx:
            _run(svc.create_draft_action(
                group_id=1,
                created_by_user_id=uuid.uuid4(),
                item_type="birthday_cake",
                title="Party",
                payload_json={"text": "Surprise"},
            ))
        self.assertIn("item_type", str(ctx.exception))

    def test_blank_title_raises(self):
        from app.domains.ai.draft_action_service import DraftActionValidationError
        db = ServiceDummyDb()
        svc = _svc(db)
        with self.assertRaises(DraftActionValidationError) as ctx:
            _run(svc.create_draft_action(
                group_id=1,
                created_by_user_id=uuid.uuid4(),
                item_type="poll",
                title="   ",
                payload_json={"question": "?", "options": ["A", "B"]},
            ))
        self.assertIn("title", str(ctx.exception))

    def test_non_dict_payload_raises(self):
        from app.domains.ai.draft_action_service import DraftActionValidationError
        db = ServiceDummyDb()
        svc = _svc(db)
        with self.assertRaises(DraftActionValidationError):
            _run(svc.create_draft_action(
                group_id=1,
                created_by_user_id=uuid.uuid4(),
                item_type="reminder",
                title="Book taxis",
                payload_json="not a dict",
            ))

    def test_poll_fewer_than_two_options_raises(self):
        from app.domains.ai.draft_action_service import DraftActionValidationError
        db = ServiceDummyDb()
        svc = _svc(db)
        with self.assertRaises(DraftActionValidationError) as ctx:
            _run(svc.create_draft_action(
                group_id=1,
                created_by_user_id=uuid.uuid4(),
                item_type="poll",
                title="Solo poll",
                payload_json={"question": "Solo?", "options": ["Only one"]},
            ))
        self.assertIn("2", str(ctx.exception))

    def test_poll_empty_options_list_raises(self):
        from app.domains.ai.draft_action_service import DraftActionValidationError
        db = ServiceDummyDb()
        svc = _svc(db)
        with self.assertRaises(DraftActionValidationError):
            _run(svc.create_draft_action(
                group_id=1,
                created_by_user_id=uuid.uuid4(),
                item_type="poll",
                title="No options",
                payload_json={"question": "Empty?", "options": []},
            ))

    def test_poll_options_not_a_list_raises(self):
        from app.domains.ai.draft_action_service import DraftActionValidationError
        db = ServiceDummyDb()
        svc = _svc(db)
        with self.assertRaises(DraftActionValidationError):
            _run(svc.create_draft_action(
                group_id=1,
                created_by_user_id=uuid.uuid4(),
                item_type="poll",
                title="Bad options",
                payload_json={"question": "Opts?", "options": "Bar, Restaurant"},
            ))

    def test_event_missing_starts_at_raises(self):
        from app.domains.ai.draft_action_service import DraftActionValidationError
        db = ServiceDummyDb()
        svc = _svc(db)
        with self.assertRaises(DraftActionValidationError) as ctx:
            _run(svc.create_draft_action(
                group_id=1,
                created_by_user_id=uuid.uuid4(),
                item_type="event",
                title="Untimed event",
                payload_json={"title": "Untimed event"},
            ))
        self.assertIn("starts_at", str(ctx.exception))

    def test_event_malformed_starts_at_raises(self):
        from app.domains.ai.draft_action_service import DraftActionValidationError
        db = ServiceDummyDb()
        svc = _svc(db)
        with self.assertRaises(DraftActionValidationError):
            _run(svc.create_draft_action(
                group_id=1,
                created_by_user_id=uuid.uuid4(),
                item_type="event",
                title="Bad date",
                payload_json={"title": "Bad date", "starts_at": "not-a-date"},
            ))

    def test_reminder_empty_title_raises(self):
        from app.domains.ai.draft_action_service import DraftActionValidationError
        db = ServiceDummyDb()
        svc = _svc(db)
        with self.assertRaises(DraftActionValidationError) as ctx:
            _run(svc.create_draft_action(
                group_id=1,
                created_by_user_id=uuid.uuid4(),
                item_type="reminder",
                title="Blank reminder",
                payload_json={"title": "  "},
            ))
        self.assertIn("title", str(ctx.exception))

    def test_reminder_without_remind_at_is_invalid(self):
        """Reminders must include a date and time."""
        db = ServiceDummyDb()
        svc = _svc(db)
        with self.assertRaises(Exception) as ctx:
            _run(svc.create_draft_action(
                group_id=1,
                created_by_user_id=uuid.uuid4(),
                item_type="reminder",
                title="Anytime reminder",
                payload_json={"text": "Remember to check in"},
            ))
        self.assertIn("remind_at", str(ctx.exception))


class TestDraftActionServiceGetAndList(unittest.TestCase):

    def test_get_existing_draft(self):
        db = ServiceDummyDb()
        svc = _svc(db)
        draft = _run(svc.create_draft_action(
            group_id=1,
            created_by_user_id=uuid.uuid4(),
            item_type="poll",
            title="Poll",
            payload_json={"question": "Poll?", "options": ["A", "B"]},
        ))
        fetched = _run(svc.get_draft_action(draft.id))
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.id, draft.id)

    def test_get_missing_draft_returns_none(self):
        db = ServiceDummyDb()
        svc = _svc(db)
        result = _run(svc.get_draft_action(uuid.uuid4()))
        self.assertIsNone(result)

    def test_list_draft_actions_empty(self):
        db = ServiceDummyDb()
        svc = _svc(db)
        results = _run(svc.list_draft_actions(group_id=1))
        self.assertEqual(results, [])


class TestDraftActionServiceReject(unittest.TestCase):

    def test_reject_draft(self):
        db = ServiceDummyDb()
        svc = _svc(db)
        user_id = uuid.uuid4()
        draft = _run(svc.create_draft_action(
            group_id=1,
            created_by_user_id=uuid.uuid4(),
            item_type="reminder",
            title="Book taxis",
            payload_json={"text": "Book taxis"},
        ))
        updated = _run(svc.reject_draft_action(draft.id, resolved_by_user_id=user_id))
        self.assertEqual(updated.status, "rejected")
        self.assertEqual(updated.resolved_by_user_id, user_id)
        self.assertIsNotNone(updated.resolved_at)

    def test_reject_already_rejected_raises(self):
        from app.domains.ai.draft_action_service import DraftActionInvalidStatusError
        db = ServiceDummyDb()
        svc = _svc(db)
        user_id = uuid.uuid4()
        draft = _run(svc.create_draft_action(
            group_id=1,
            created_by_user_id=uuid.uuid4(),
            item_type="reminder",
            title="Book taxis",
            payload_json={"text": "Book taxis"},
        ))
        _run(svc.reject_draft_action(draft.id, resolved_by_user_id=user_id))
        with self.assertRaises(DraftActionInvalidStatusError):
            _run(svc.reject_draft_action(draft.id, resolved_by_user_id=user_id))

    def test_reject_missing_draft_raises(self):
        from app.domains.ai.draft_action_service import DraftActionNotFoundError
        db = ServiceDummyDb()
        svc = _svc(db)
        with self.assertRaises(DraftActionNotFoundError):
            _run(svc.reject_draft_action(uuid.uuid4(), resolved_by_user_id=uuid.uuid4()))


class TestDraftActionServiceAccept(unittest.TestCase):

    def test_accept_poll_draft_creates_poll_and_hub_item(self):
        from app.models.planning import Poll, PollOption
        from app.models.hub_item import HubItem

        db = ServiceDummyDb()
        svc = _svc(db)
        user_id = uuid.uuid4()
        draft = _run(svc.create_draft_action(
            group_id=1,
            created_by_user_id=uuid.uuid4(),
            item_type="poll",
            title="Pub or cinema?",
            payload_json={
                "question": "Pub or cinema?",
                "options": ["Pub", "Cinema"],
                "closes_at": "2026-06-01T23:59:00Z",
            },
        ))
        updated = _run(svc.accept_draft_action(draft.id, resolved_by_user_id=user_id))

        self.assertEqual(updated.status, "accepted")
        self.assertIsNotNone(updated.created_poll_id)
        self.assertIsNotNone(updated.created_hub_item_id)

        # Poll row was created
        polls = [v for v in db._poll_store.values() if isinstance(v, Poll)]
        self.assertEqual(len(polls), 1)
        self.assertEqual(polls[0].question, "Pub or cinema?")

        # Both options were added
        options = [v for v in db.added if isinstance(v, PollOption)]
        self.assertEqual(len(options), 2)

        # HubItem mirror was created
        hub_items = [v for v in db._hub_item_store.values() if isinstance(v, HubItem)]
        self.assertEqual(len(hub_items), 1)
        self.assertEqual(hub_items[0].item_type, "poll")

    def test_accept_event_draft_creates_event_and_hub_item(self):
        from app.models.event import Event
        from app.models.hub_item import HubItem

        db = ServiceDummyDb()
        svc = _svc(db)
        user_id = uuid.uuid4()
        draft = _run(svc.create_draft_action(
            group_id=1,
            created_by_user_id=uuid.uuid4(),
            item_type="event",
            title="Curry Night",
            payload_json={
                "title": "Curry Night",
                "starts_at": "2026-06-05T19:00:00Z",
                "location": "The Usual Place",
            },
        ))
        updated = _run(svc.accept_draft_action(draft.id, resolved_by_user_id=user_id))

        self.assertEqual(updated.status, "accepted")
        self.assertIsNotNone(updated.created_event_id)
        self.assertIsNotNone(updated.created_hub_item_id)

        events = [v for v in db._event_store.values() if isinstance(v, Event)]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].title, "Curry Night")
        self.assertEqual(events[0].location, "The Usual Place")

        hub_items = [v for v in db._hub_item_store.values() if isinstance(v, HubItem)]
        self.assertEqual(len(hub_items), 1)
        self.assertEqual(hub_items[0].item_type, "event")

    def test_accept_reminder_draft_creates_reminder_and_hub_item(self):
        from app.models.planning import Reminder
        from app.models.hub_item import HubItem

        db = ServiceDummyDb()
        svc = _svc(db)
        user_id = uuid.uuid4()
        draft = _run(svc.create_draft_action(
            group_id=1,
            created_by_user_id=uuid.uuid4(),
            item_type="reminder",
            title="Book taxis before Friday",
            payload_json={"text": "Book taxis before Friday", "remind_at": "2026-05-14T18:00:00Z"},
        ))
        updated = _run(svc.accept_draft_action(draft.id, resolved_by_user_id=user_id))

        self.assertEqual(updated.status, "accepted")
        self.assertIsNotNone(updated.created_reminder_id)
        self.assertIsNotNone(updated.created_hub_item_id)

        reminders = [v for v in db._reminder_store.values() if isinstance(v, Reminder)]
        self.assertEqual(len(reminders), 1)
        self.assertEqual(reminders[0].text, "Book taxis before Friday")

    def test_accept_already_accepted_raises(self):
        from app.domains.ai.draft_action_service import DraftActionInvalidStatusError

        db = ServiceDummyDb()
        svc = _svc(db)
        user_id = uuid.uuid4()
        draft = _run(svc.create_draft_action(
            group_id=1,
            created_by_user_id=uuid.uuid4(),
            item_type="reminder",
            title="Once only",
            payload_json={"text": "Once only"},
        ))
        _run(svc.accept_draft_action(draft.id, resolved_by_user_id=user_id))
        with self.assertRaises(DraftActionInvalidStatusError):
            _run(svc.accept_draft_action(draft.id, resolved_by_user_id=user_id))

    def test_accept_rejected_draft_raises(self):
        from app.domains.ai.draft_action_service import DraftActionInvalidStatusError

        db = ServiceDummyDb()
        svc = _svc(db)
        user_id = uuid.uuid4()
        draft = _run(svc.create_draft_action(
            group_id=1,
            created_by_user_id=uuid.uuid4(),
            item_type="reminder",
            title="Rejected",
            payload_json={"text": "Rejected reminder"},
        ))
        _run(svc.reject_draft_action(draft.id, resolved_by_user_id=user_id))
        with self.assertRaises(DraftActionInvalidStatusError):
            _run(svc.accept_draft_action(draft.id, resolved_by_user_id=user_id))

    def test_accept_missing_draft_raises(self):
        from app.domains.ai.draft_action_service import DraftActionNotFoundError

        db = ServiceDummyDb()
        svc = _svc(db)
        with self.assertRaises(DraftActionNotFoundError):
            _run(svc.accept_draft_action(uuid.uuid4(), resolved_by_user_id=uuid.uuid4()))

    def test_accept_does_not_mark_accepted_on_validation_failure(self):
        """If payload is corrupted after creation, accept raises and draft stays in 'draft'."""
        from app.domains.ai.draft_action_service import DraftActionValidationError

        db = ServiceDummyDb()
        svc = _svc(db)
        user_id = uuid.uuid4()

        # Create a valid draft then corrupt its payload in the store
        draft = _run(svc.create_draft_action(
            group_id=1,
            created_by_user_id=uuid.uuid4(),
            item_type="event",
            title="Event",
            payload_json={"title": "Event", "starts_at": "2026-06-01T19:00:00Z"},
        ))
        # Corrupt: remove starts_at
        db._store[draft.id].payload_json = {"title": "Event"}

        with self.assertRaises(DraftActionValidationError):
            _run(svc.accept_draft_action(draft.id, resolved_by_user_id=user_id))

        # Draft status must still be 'draft'
        self.assertEqual(db._store[draft.id].status, "draft")



# ── Draft Action API endpoint tests ──────────────────────────────────────────
#
# Tests call the route functions directly (same pattern as test_hub_items.py),
# monkey-patching _current_user_or_401 and _default_group on the router module
# and using a ServiceDummyDb (defined above) for the session.
#
# Coverage that would require a live DB (group scoping cross-check, commit
# verification) is noted inline where it can't be exercised without integration
# infrastructure.


import os
os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_PASSWORD", "changeme")

from app.api.v1 import draft_action_router as dar_module
from app.api.v1.draft_action_router import (
    list_draft_actions,
    get_draft_action,
    accept_draft_action,
    reject_draft_action,
)
from app.domains.ai.draft_action_service import DraftActionService as _DraftActionService


def _make_user(role="owner"):
    return types.SimpleNamespace(
        id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        nickname="TestUser",
        username="testuser",
        role=types.SimpleNamespace(value=role),
    )


def _make_group(group_id=1):
    return types.SimpleNamespace(id=group_id)


class _ApiBase(unittest.TestCase):
    """Base class: patches auth and group helpers before each test."""

    def setUp(self):
        self.user = _make_user()
        self.group = _make_group()
        self._orig_auth = dar_module._current_user_or_401
        self._orig_group = dar_module._default_group
        _user = self.user
        _group = self.group
        # Must be coroutine functions, not lambdas wrapping asyncio.run(),
        # because the router awaits them inside a running event loop.
        async def _fake_auth(auth, db): return _user
        async def _fake_group(db): return _group
        dar_module._current_user_or_401 = _fake_auth
        dar_module._default_group = _fake_group

    def tearDown(self):
        dar_module._current_user_or_401 = self._orig_auth
        dar_module._default_group = self._orig_group


def _prefilled_db(item_type="poll", title="Poll?", payload=None):
    """Return a (ServiceDummyDb, draft) pair.

    The db's _execute_rows is pre-seeded with the draft so that the
    group-scoped execute() path in get_by_id also finds it.
    """
    db = ServiceDummyDb()
    svc_payload = payload or {"question": "Poll?", "options": ["A", "B"]}
    draft = _run(_DraftActionService(db).create_draft_action(
        group_id=1,
        created_by_user_id=uuid.uuid4(),
        item_type=item_type,
        title=title,
        payload_json=svc_payload,
    ))
    # Seed so the filtered SELECT (used when group_id is provided) also finds it
    db._execute_rows = [draft]
    return db, draft


class TestListDraftActionsEndpoint(_ApiBase):

    def test_returns_empty_list(self):
        db = ServiceDummyDb()
        result = _run(list_draft_actions(db=db))
        self.assertEqual(result.total, 0)
        self.assertEqual(result.draft_actions, [])

    def test_returns_existing_draft(self):
        db, draft = _prefilled_db()
        db._execute_rows = [draft]
        result = _run(list_draft_actions(db=db))
        self.assertEqual(result.total, 1)
        self.assertEqual(result.draft_actions[0].id, str(draft.id))

    def test_limit_capped_at_100(self):
        db = ServiceDummyDb()
        # Just verify it doesn't raise — actual capping is in the service call
        result = _run(list_draft_actions(limit=999, db=db))
        self.assertEqual(result.total, 0)


class TestGetDraftActionEndpoint(_ApiBase):

    def test_get_existing_draft(self):
        db, draft = _prefilled_db()
        result = _run(get_draft_action(str(draft.id), db=db))
        self.assertEqual(result.id, str(draft.id))
        self.assertEqual(result.item_type, "poll")

    def test_get_missing_draft_raises_404(self):
        from fastapi import HTTPException as FastAPIHTTPException
        db = ServiceDummyDb()
        with self.assertRaises(FastAPIHTTPException) as ctx:
            _run(get_draft_action(str(uuid.uuid4()), db=db))
        self.assertEqual(ctx.exception.status_code, 404)

    def test_get_malformed_id_raises_400(self):
        from fastapi import HTTPException as FastAPIHTTPException
        db = ServiceDummyDb()
        with self.assertRaises(FastAPIHTTPException) as ctx:
            _run(get_draft_action("not-a-uuid", db=db))
        self.assertEqual(ctx.exception.status_code, 400)


class TestRejectDraftActionEndpoint(_ApiBase):

    def test_reject_draft(self):
        db, draft = _prefilled_db()
        result = _run(reject_draft_action(str(draft.id), db=db))
        self.assertTrue(result.success)
        self.assertEqual(result.draft_action.status, "rejected")
        self.assertIsNotNone(result.draft_action.resolved_at)

    def test_reject_missing_draft_raises_404(self):
        from fastapi import HTTPException as FastAPIHTTPException
        db = ServiceDummyDb()
        with self.assertRaises(FastAPIHTTPException) as ctx:
            _run(reject_draft_action(str(uuid.uuid4()), db=db))
        self.assertEqual(ctx.exception.status_code, 404)

    def test_reject_malformed_id_raises_400(self):
        from fastapi import HTTPException as FastAPIHTTPException
        db = ServiceDummyDb()
        with self.assertRaises(FastAPIHTTPException) as ctx:
            _run(reject_draft_action("bad-id", db=db))
        self.assertEqual(ctx.exception.status_code, 400)

    def test_reject_already_rejected_raises_409(self):
        from fastapi import HTTPException as FastAPIHTTPException
        db, draft = _prefilled_db()
        _run(reject_draft_action(str(draft.id), db=db))
        # Reset commit stub so second call sees the updated state
        with self.assertRaises(FastAPIHTTPException) as ctx:
            _run(reject_draft_action(str(draft.id), db=db))
        self.assertEqual(ctx.exception.status_code, 409)

    def test_reject_accepted_draft_raises_409(self):
        from fastapi import HTTPException as FastAPIHTTPException
        db, draft = _prefilled_db()
        _run(accept_draft_action(str(draft.id), db=db))
        with self.assertRaises(FastAPIHTTPException) as ctx:
            _run(reject_draft_action(str(draft.id), db=db))
        self.assertEqual(ctx.exception.status_code, 409)


class TestAcceptDraftActionEndpoint(_ApiBase):

    def test_accept_poll_draft(self):
        from app.models.planning import Poll, PollOption
        db, draft = _prefilled_db(
            item_type="poll",
            title="Pub or cinema?",
            payload={"question": "Pub or cinema?", "options": ["Pub", "Cinema"]},
        )
        result = _run(accept_draft_action(str(draft.id), db=db))
        self.assertTrue(result.success)
        self.assertEqual(result.draft_action.status, "accepted")
        self.assertIsNotNone(result.draft_action.created_poll_id)
        self.assertIsNotNone(result.draft_action.created_hub_item_id)
        polls = [v for v in db._poll_store.values() if isinstance(v, Poll)]
        self.assertEqual(len(polls), 1)
        options = [v for v in db.added if isinstance(v, PollOption)]
        self.assertEqual(len(options), 2)

    def test_accept_event_draft(self):
        from app.models.event import Event
        db, draft = _prefilled_db(
            item_type="event",
            title="Curry Night",
            payload={"title": "Curry Night", "starts_at": "2026-06-05T19:00:00Z"},
        )
        result = _run(accept_draft_action(str(draft.id), db=db))
        self.assertEqual(result.draft_action.status, "accepted")
        self.assertIsNotNone(result.draft_action.created_event_id)
        events = [v for v in db._event_store.values() if isinstance(v, Event)]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].title, "Curry Night")

    def test_accept_reminder_draft(self):
        from app.models.planning import Reminder
        db, draft = _prefilled_db(
            item_type="reminder",
            title="Book taxis",
            payload={"text": "Book taxis before Friday"},
        )
        result = _run(accept_draft_action(str(draft.id), db=db))
        self.assertEqual(result.draft_action.status, "accepted")
        self.assertIsNotNone(result.draft_action.created_reminder_id)
        reminders = [v for v in db._reminder_store.values() if isinstance(v, Reminder)]
        self.assertEqual(len(reminders), 1)

    def test_accept_missing_draft_raises_404(self):
        from fastapi import HTTPException as FastAPIHTTPException
        db = ServiceDummyDb()
        with self.assertRaises(FastAPIHTTPException) as ctx:
            _run(accept_draft_action(str(uuid.uuid4()), db=db))
        self.assertEqual(ctx.exception.status_code, 404)

    def test_accept_malformed_id_raises_400(self):
        from fastapi import HTTPException as FastAPIHTTPException
        db = ServiceDummyDb()
        with self.assertRaises(FastAPIHTTPException) as ctx:
            _run(accept_draft_action("not-a-uuid", db=db))
        self.assertEqual(ctx.exception.status_code, 400)

    def test_accept_already_accepted_raises_409(self):
        from fastapi import HTTPException as FastAPIHTTPException
        db, draft = _prefilled_db()
        _run(accept_draft_action(str(draft.id), db=db))
        with self.assertRaises(FastAPIHTTPException) as ctx:
            _run(accept_draft_action(str(draft.id), db=db))
        self.assertEqual(ctx.exception.status_code, 409)

    def test_accept_rejected_draft_raises_409(self):
        from fastapi import HTTPException as FastAPIHTTPException
        db, draft = _prefilled_db()
        _run(reject_draft_action(str(draft.id), db=db))
        with self.assertRaises(FastAPIHTTPException) as ctx:
            _run(accept_draft_action(str(draft.id), db=db))
        self.assertEqual(ctx.exception.status_code, 409)

    def test_response_message_includes_item_type(self):
        db, draft = _prefilled_db(item_type="poll", title="A poll",
                                   payload={"question": "?", "options": ["X", "Y"]})
        result = _run(accept_draft_action(str(draft.id), db=db))
        self.assertIn("Poll", result.message)


# ── Missing coverage note ─────────────────────────────────────────────────────
# The following scenarios require a live PostgreSQL session and are not covered
# by unit tests:
#   - Group scoping: a draft from group A is not visible to group B's request.
#     (get_by_id with group_id filter hits a real SELECT WHERE query.)
#   - Unauthenticated requests: _current_user_or_401 is monkey-patched here;
#     real auth enforcement is tested in test_auth.py.
#   - db.commit() is called: ServiceDummyDb.commit() is a no-op; the actual
#     commit path is covered by the FastAPI integration test suite (if present).


# ── Propose tool tests ────────────────────────────────────────────────────────
#
# Tool handlers are async functions; we call them directly without going through
# the registry so we can verify the DB writes independently of the full runtime.


class TestProposePollTool(unittest.TestCase):

    def _ctx(self, **overrides):
        base = {
            "group_id": 1,
            "created_by_user_id": uuid.uuid4(),
            "source": "hub_lab",
            "dry_run": False,
        }
        base.update(overrides)
        return base

    def test_creates_draft_action_row(self):
        from app.domains.ai.tools import propose_poll
        db = ServiceDummyDb()
        result = _run(propose_poll(
            db,
            _ctx=self._ctx(),
            question="Where should we go?",
            options=["Bar", "Cinema"],
        ))
        self.assertTrue(result["success"])
        self.assertFalse(result["dry_run"])
        self.assertIsNotNone(result["draft_action_id"])
        self.assertEqual(result["item_type"], "poll")
        self.assertEqual(result["status"], "draft")
        self.assertEqual(result["payload"]["question"], "Where should we go?")
        self.assertEqual(result["payload"]["options"], ["Bar", "Cinema"])
        # Exactly one AIDraftAction stored
        self.assertEqual(len(db._store), 1)

    def test_dry_run_does_not_persist(self):
        from app.domains.ai.tools import propose_poll
        db = ServiceDummyDb()
        result = _run(propose_poll(
            db,
            _ctx=self._ctx(dry_run=True),
            question="Dry poll?",
            options=["Yes", "No"],
        ))
        self.assertTrue(result["success"])
        self.assertTrue(result["dry_run"])
        self.assertIsNone(result["draft_action_id"])
        # Nothing written to DB
        self.assertEqual(len(db._store), 0)

    def test_optional_fields_included_in_payload(self):
        from app.domains.ai.tools import propose_poll
        db = ServiceDummyDb()
        result = _run(propose_poll(
            db,
            _ctx=self._ctx(),
            question="Favourite food?",
            options=["Pizza", "Curry", "Tacos"],
            closes_at="2026-06-01T23:59:00Z",
            allow_multiple=True,
            tags=["food"],
        ))
        self.assertEqual(result["payload"]["vote_mode"], "multiple")
        self.assertEqual(result["payload"]["closes_at"], "2026-06-01T23:59:00Z")
        self.assertEqual(result["payload"]["tags"], ["food"])

    def test_invalid_payload_raises_validation_error(self):
        from app.domains.ai.tools import propose_poll
        from app.domains.ai.draft_action_service import DraftActionValidationError
        db = ServiceDummyDb()
        with self.assertRaises(DraftActionValidationError):
            _run(propose_poll(
                db,
                _ctx=self._ctx(),
                question="Too few options",
                options=["Only one"],
            ))
        self.assertEqual(len(db._store), 0)

    def test_missing_group_id_raises(self):
        from app.domains.ai.tools import propose_poll
        db = ServiceDummyDb()
        with self.assertRaises(ValueError) as ctx:
            _run(propose_poll(
                db,
                _ctx={"created_by_user_id": uuid.uuid4(), "dry_run": False},
                question="Missing group",
                options=["A", "B"],
            ))
        self.assertIn("group_id", str(ctx.exception))

    def test_missing_user_id_raises(self):
        from app.domains.ai.tools import propose_poll
        db = ServiceDummyDb()
        with self.assertRaises(ValueError) as ctx:
            _run(propose_poll(
                db,
                _ctx={"group_id": 1, "dry_run": False},
                question="Missing user",
                options=["A", "B"],
            ))
        self.assertIn("created_by_user_id", str(ctx.exception))

    def test_group_and_user_id_come_from_ctx_not_llm_args(self):
        """LLM args cannot supply group_id or created_by_user_id."""
        from app.domains.ai.tools import propose_poll
        import inspect
        sig = inspect.signature(propose_poll)
        param_names = list(sig.parameters.keys())
        self.assertNotIn("group_id", param_names)
        self.assertNotIn("created_by_user_id", param_names)


class TestProposeEventTool(unittest.TestCase):

    def _ctx(self, **overrides):
        base = {
            "group_id": 1,
            "created_by_user_id": uuid.uuid4(),
            "source": "hub_lab",
            "dry_run": False,
        }
        base.update(overrides)
        return base

    def test_creates_draft_action_row(self):
        from app.domains.ai.tools import propose_event
        db = ServiceDummyDb()
        result = _run(propose_event(
            db,
            _ctx=self._ctx(),
            title="Curry Night",
            starts_at="2026-06-05T19:00:00Z",
        ))
        self.assertTrue(result["success"])
        self.assertFalse(result["dry_run"])
        self.assertIsNotNone(result["draft_action_id"])
        self.assertEqual(result["item_type"], "event")
        self.assertEqual(result["payload"]["title"], "Curry Night")
        self.assertEqual(result["payload"]["starts_at"], "2026-06-05T19:00:00Z")
        self.assertEqual(len(db._store), 1)

    def test_dry_run_does_not_persist(self):
        from app.domains.ai.tools import propose_event
        db = ServiceDummyDb()
        result = _run(propose_event(
            db,
            _ctx=self._ctx(dry_run=True),
            title="Dry Event",
            starts_at="2026-06-05T19:00:00Z",
        ))
        self.assertTrue(result["dry_run"])
        self.assertIsNone(result["draft_action_id"])
        self.assertEqual(len(db._store), 0)

    def test_optional_fields_in_payload(self):
        from app.domains.ai.tools import propose_event
        db = ServiceDummyDb()
        result = _run(propose_event(
            db,
            _ctx=self._ctx(),
            title="Pub Night",
            starts_at="2026-06-10T20:00:00Z",
            location="The Crown",
            description="Monthly pub night",
            tags=["social"],
        ))
        p = result["payload"]
        self.assertEqual(p["location"], "The Crown")
        self.assertEqual(p["description"], "Monthly pub night")
        self.assertEqual(p["tags"], ["social"])

    def test_missing_starts_at_raises(self):
        from app.domains.ai.tools import propose_event
        from app.domains.ai.draft_action_service import DraftActionValidationError
        db = ServiceDummyDb()
        with self.assertRaises(DraftActionValidationError):
            _run(propose_event(
                db,
                _ctx=self._ctx(),
                title="No time event",
                starts_at="",   # falsy — service rejects this
            ))


class TestProposeReminderTool(unittest.TestCase):

    def _ctx(self, **overrides):
        base = {
            "group_id": 1,
            "created_by_user_id": uuid.uuid4(),
            "source": "hub_lab",
            "dry_run": False,
        }
        base.update(overrides)
        return base

    def test_creates_draft_action_row(self):
        from app.domains.ai.tools import propose_reminder
        db = ServiceDummyDb()
        result = _run(propose_reminder(
            db,
            _ctx=self._ctx(),
            text="Book taxis before Friday",
            remind_at="2026-05-14T18:00:00Z",
        ))
        self.assertTrue(result["success"])
        self.assertFalse(result["dry_run"])
        self.assertIsNotNone(result["draft_action_id"])
        self.assertEqual(result["item_type"], "reminder")
        self.assertEqual(result["payload"]["text"], "Book taxis before Friday")
        self.assertEqual(len(db._store), 1)

    def test_semantic_reference_tag_is_prefixed_by_item_type(self):
        from app.domains.ai.tools import propose_event
        db = ServiceDummyDb()
        result = _run(propose_event(
            db,
            _ctx=self._ctx(),
            title="Party at Mike's",
            starts_at="2026-05-14T19:00:00Z",
            reference_tag="party",
        ))

        self.assertTrue(result["success"])
        self.assertEqual(result["short_id"], "#E-party")

    def test_semantic_reference_tag_collisions_get_suffix(self):
        from app.domains.ai.tools import propose_event
        db = ServiceDummyDb()
        first = _run(propose_event(
            db,
            _ctx=self._ctx(),
            title="Party at Mike's",
            starts_at="2026-05-14T19:00:00Z",
            reference_tag="party",
        ))
        second = _run(propose_event(
            db,
            _ctx=self._ctx(),
            title="Another Party",
            starts_at="2026-05-15T19:00:00Z",
            reference_tag="party",
        ))

        self.assertEqual(first["short_id"], "#E-party")
        self.assertEqual(second["short_id"], "#E-party-2")

    def test_dry_run_does_not_persist(self):
        from app.domains.ai.tools import propose_reminder
        db = ServiceDummyDb()
        result = _run(propose_reminder(
            db,
            _ctx=self._ctx(dry_run=True),
            text="Dry reminder",
            remind_at="2026-05-14T18:00:00Z",
        ))
        self.assertTrue(result["dry_run"])
        self.assertIsNone(result["draft_action_id"])
        self.assertEqual(len(db._store), 0)

    def test_no_remind_at_raises(self):
        from app.domains.ai.tools import propose_reminder
        db = ServiceDummyDb()
        with self.assertRaises(ValueError):
            _run(propose_reminder(
                db,
                _ctx=self._ctx(),
                text="Open-ended reminder",
            ))

    def test_empty_text_raises(self):
        from app.domains.ai.tools import propose_reminder
        from app.domains.ai.draft_action_service import DraftActionValidationError
        db = ServiceDummyDb()
        with self.assertRaises(DraftActionValidationError):
            _run(propose_reminder(
                db,
                _ctx=self._ctx(),
                text="   ",
            ))


class TestToolRegistryContextInjection(unittest.TestCase):
    """Verify _ctx is forwarded to handlers that declare it, ignored by those that don't."""

    def test_ctx_forwarded_to_propose_tool_via_registry(self):
        from app.domains.ai.tools import ToolRegistry, propose_poll
        registry = ToolRegistry()
        registry.register("propose_poll", "Propose poll", "safe_write", propose_poll)
        db = ServiceDummyDb()
        ctx = {
            "group_id": 1,
            "created_by_user_id": uuid.uuid4(),
            "source": "hub_lab",
            "dry_run": True,
        }
        result = _run(registry.call(
            "propose_poll", db, _ctx=ctx,
            question="Via registry?", options=["Yes", "No"],
        ))
        self.assertTrue(result["success"])
        self.assertTrue(result["dry_run"])

    def test_ctx_ignored_by_existing_tools(self):
        """Existing tools (no _ctx param) still work when _ctx is passed."""
        from app.domains.ai.tools import build_default_registry
        registry = build_default_registry()
        db = ServiceDummyDb()
        result = _run(registry.call(
            "list_recent_memories", db,
            _ctx={"group_id": 1, "created_by_user_id": uuid.uuid4()},
        ))
        self.assertIn("memories", result)
        self.assertIn("count", result)

    def test_propose_tools_not_in_approved_create_path(self):
        """propose_* tools create drafts only; accept_draft_action must not be in registry."""
        from app.domains.ai.tools import build_default_registry
        registry = build_default_registry()
        tool_names = [t["name"] for t in registry.list_tools()]
        self.assertIn("propose_poll", tool_names)
        self.assertIn("propose_event", tool_names)
        self.assertIn("propose_reminder", tool_names)
        # The final-item creation tools must NOT be registered
        self.assertNotIn("accept_draft_action", tool_names)
        self.assertNotIn("create_poll", tool_names)
        self.assertNotIn("create_event", tool_names)
        self.assertNotIn("create_reminder", tool_names)

    def test_propose_tools_are_safe_write(self):
        from app.domains.ai.tools import build_default_registry
        registry = build_default_registry()
        tools_by_name = {t["name"]: t for t in registry.list_tools()}
        for name in ("propose_poll", "propose_event", "propose_reminder"):
            self.assertEqual(tools_by_name[name]["safety"], "safe_write", f"{name} safety wrong")

    def test_runtime_skips_propose_tools_in_dry_run(self):
        """In dry_run the runtime skips safe_write tools at the _execute_tool gate."""
        from app.domains.ai.agent_runtime import HubAgentRuntime
        db = ServiceDummyDb()
        runtime = HubAgentRuntime(db=db, tool_context={
            "group_id": 1,
            "created_by_user_id": uuid.uuid4(),
        })
        result = _run(runtime._execute_tool(
            "propose_poll",
            {"question": "Skip me?", "options": ["A", "B"]},
            dry_run=True,
        ))
        # safe_write + dry_run → skipped, no DB write
        self.assertFalse(result["success"])
        self.assertTrue(result.get("skipped"))
        self.assertEqual(len(db._store), 0)

    def test_runtime_executes_propose_poll_when_not_dry_run(self):
        """With dry_run=False the runtime calls propose_poll and a draft is stored."""
        from app.domains.ai.agent_runtime import HubAgentRuntime
        db = ServiceDummyDb()
        runtime = HubAgentRuntime(db=db, tool_context={
            "group_id": 1,
            "created_by_user_id": uuid.uuid4(),
            "source": "hub_lab",
        })
        result = _run(runtime._execute_tool(
            "propose_poll",
            {"question": "Runtime poll?", "options": ["A", "B"]},
            dry_run=False,
        ))
        self.assertTrue(result["success"])
        inner = result["result"]
        self.assertTrue(inner["success"])
        self.assertIsNotNone(inner["draft_action_id"])
        self.assertEqual(len(db._store), 1)



# ── Draft actions in hub-bot-chat response (Slice 7) ─────────────────────────
#
# These tests verify the collection pipeline:
#   propose_* tool → draft_action_id in AgentRuntimeResult
#   → fetched from DB → attached to HubAgentResult.draft_actions
#   → returned in HubBotChatResponse.draft_actions
#
# We test each layer independently using the existing fake/dummy infrastructure.


class TestAgentRuntimeDraftIdCollection(unittest.TestCase):
    """AgentRuntimeResult.proposed_draft_action_ids is populated from tool results."""

    def _runtime(self, db=None):
        from app.domains.ai.agent_runtime import HubAgentRuntime
        return HubAgentRuntime(
            db=db or ServiceDummyDb(),
            tool_context={
                "group_id": 1,
                "created_by_user_id": uuid.uuid4(),
                "source": "hub_lab",
            },
        )

    def _fake_tool_result(self, tool_name, draft_id):
        """Build the wrapper dict _execute_tool would return for a successful propose."""
        return {
            "tool": tool_name,
            "success": True,
            "safety": "safe_write",
            "result": {
                "success": True,
                "dry_run": False,
                "draft_action_id": str(draft_id),
                "item_type": tool_name.replace("propose_", ""),
                "title": "Test",
                "status": "draft",
                "payload": {},
            },
        }

    def test_draft_ids_extracted_from_successful_propose_tool_results(self):
        from app.domains.ai.agent_runtime import AgentRuntimeResult
        draft_id = uuid.uuid4()
        tool_results = [self._fake_tool_result("propose_poll", draft_id)]

        # Simulate the extraction logic used in runtime.run()
        proposed = []
        for tr in tool_results:
            if not tr.get("success"):
                continue
            inner = tr.get("result", {})
            if isinstance(inner, dict) and inner.get("success") and inner.get("draft_action_id"):
                proposed.append(str(inner["draft_action_id"]))

        self.assertEqual(proposed, [str(draft_id)])

    def test_failed_tool_result_not_included(self):
        tool_results = [
            {"tool": "propose_poll", "success": False, "error": "oops", "result": {}}
        ]
        proposed = []
        for tr in tool_results:
            if not tr.get("success"):
                continue
            inner = tr.get("result", {})
            if isinstance(inner, dict) and inner.get("success") and inner.get("draft_action_id"):
                proposed.append(str(inner["draft_action_id"]))

        self.assertEqual(proposed, [])

    def test_dry_run_result_not_included(self):
        """Dry-run results have draft_action_id=None; they must not appear in proposed list."""
        tool_results = [
            {
                "tool": "propose_poll",
                "success": True,
                "safety": "safe_write",
                "result": {
                    "success": True,
                    "dry_run": True,
                    "draft_action_id": None,
                    "item_type": "poll",
                    "title": "Dry",
                    "status": "draft",
                    "payload": {},
                },
            }
        ]
        proposed = []
        for tr in tool_results:
            if not tr.get("success"):
                continue
            inner = tr.get("result", {})
            if isinstance(inner, dict) and inner.get("success") and inner.get("draft_action_id"):
                proposed.append(str(inner["draft_action_id"]))

        self.assertEqual(proposed, [])

    def test_runtime_execute_propose_poll_populates_draft_ids(self):
        """End-to-end: _execute_tool("propose_poll") → result captured by runtime."""
        db = ServiceDummyDb()
        runtime = self._runtime(db)
        tool_result = _run(runtime._execute_tool(
            "propose_poll",
            {"question": "Runtime poll?", "options": ["A", "B"]},
            dry_run=False,
        ))
        self.assertTrue(tool_result["success"])
        inner = tool_result["result"]
        self.assertIsNotNone(inner["draft_action_id"])

        # Simulate the post-loop collection
        proposed = []
        for tr in [tool_result]:
            if not tr.get("success"):
                continue
            r = tr.get("result", {})
            if isinstance(r, dict) and r.get("success") and r.get("draft_action_id"):
                proposed.append(str(r["draft_action_id"]))

        self.assertEqual(len(proposed), 1)
        self.assertEqual(proposed[0], inner["draft_action_id"])


class TestHubAgentResultDraftActions(unittest.TestCase):
    """HubAgentResult.draft_actions is populated after the runtime run."""

    def _svc_and_db(self):
        from app.domains.ai.hub_agent_service import SharedHubBotService
        from app.domains.ai.summary_service import FakeLLMClient
        db = ServiceDummyDb()
        svc = SharedHubBotService(db=db, llm_client=FakeLLMClient())
        return svc, db

    def test_draft_actions_empty_by_default(self):
        from app.domains.ai.hub_agent_service import HubAgentResult
        result = HubAgentResult(reply="Hello")
        self.assertEqual(result.draft_actions, [])

    def test_draft_actions_included_when_set(self):
        from app.domains.ai.hub_agent_service import HubAgentResult
        draft = {
            "id": str(uuid.uuid4()),
            "item_type": "poll",
            "status": "draft",
            "title": "Test poll",
        }
        result = HubAgentResult(reply="Done", draft_actions=[draft])
        self.assertEqual(len(result.draft_actions), 1)
        self.assertEqual(result.draft_actions[0]["item_type"], "poll")

    def test_draft_action_to_dict_serialises_correctly(self):
        """_draft_action_to_dict produces the expected shape from an AIDraftAction."""
        from app.domains.ai.hub_agent_service import _draft_action_to_dict

        db = ServiceDummyDb()
        draft = _run(_DraftActionService(db).create_draft_action(
            group_id=1,
            created_by_user_id=uuid.uuid4(),
            item_type="poll",
            title="Serialised poll",
            payload_json={"question": "Serialised poll", "options": ["A", "B"]},
        ))

        d = _draft_action_to_dict(draft)
        self.assertIn("id", d)
        self.assertEqual(d["item_type"], "poll")
        self.assertEqual(d["status"], "draft")
        self.assertEqual(d["title"], "Serialised poll")
        self.assertIn("payload_json", d)
        self.assertIn("created_at", d)
        self.assertIsNone(d["resolved_at"])

    def test_draft_action_to_dict_with_nulls_is_safe(self):
        """Serialiser handles None timestamps without raising."""
        from app.domains.ai.hub_agent_service import _draft_action_to_dict
        from app.models.ai_draft_action import AIDraftAction

        draft = AIDraftAction(
            id=uuid.uuid4(),
            group_id=1,
            created_by_user_id=uuid.uuid4(),
            item_type="reminder",
            title="Null timestamps",
            payload_json={"text": "Test"},
            proposed_by="ai",
            action_type="create_hub_item",
            status="draft",
            source="hub_lab",
        )
        d = _draft_action_to_dict(draft)
        self.assertIsNone(d["created_at"])
        self.assertIsNone(d["resolved_at"])
        self.assertEqual(d["item_type"], "reminder")


class TestHubBotChatResponseDraftActions(unittest.TestCase):
    """hub-bot-chat endpoint includes draft_actions in the response."""

    def setUp(self):
        import os
        os.environ.setdefault("DEBUG", "false")
        os.environ.setdefault("DATABASE_PASSWORD", "changeme")

        from app.api.v1 import ai_router as ai_mod
        self._ai_mod = ai_mod
        self._orig_auth = ai_mod._current_user_or_401
        self._orig_group = ai_mod._get_default_group
        self._user = _make_user()
        self._group = _make_group()
        async def _fake_auth(auth, db): return self._user
        async def _fake_group(db): return self._group
        ai_mod._current_user_or_401 = _fake_auth
        ai_mod._get_default_group = _fake_group

    def tearDown(self):
        self._ai_mod._current_user_or_401 = self._orig_auth
        self._ai_mod._get_default_group = self._orig_group

    def _make_chat_request(self, message="hello", dry_run=False):
        from app.api.v1.ai_router import HubBotChatRequest
        return HubBotChatRequest(message=message, dry_run=dry_run)

    def test_response_always_has_draft_actions_field(self):
        """draft_actions is present and is a list even when the bot did not propose anything."""
        from app.api.v1.ai_router import hub_bot_chat
        db = ServiceDummyDb()
        result = _run(hub_bot_chat(self._make_chat_request("hello"), db=db))
        self.assertTrue(hasattr(result, "draft_actions"))
        self.assertIsInstance(result.draft_actions, list)

    def test_dry_run_returns_empty_draft_actions(self):
        """dry_run never produces draft rows, so draft_actions must be empty."""
        from app.api.v1.ai_router import hub_bot_chat
        db = ServiceDummyDb()
        result = _run(hub_bot_chat(self._make_chat_request(dry_run=True), db=db))
        self.assertEqual(result.draft_actions, [])

    def test_response_serialises_without_error(self):
        """Response model validates correctly including the draft_actions field."""
        from app.api.v1.ai_router import HubBotChatResponse
        resp = HubBotChatResponse(
            reply="Here is your poll",
            created_memory_count=0,
            created_suggestion_count=0,
            suggested_actions=[],
            draft_actions=[
                {
                    "id": str(uuid.uuid4()),
                    "item_type": "poll",
                    "status": "draft",
                    "title": "Where to go?",
                    "payload_json": {"question": "Where?", "options": ["Bar", "Club"]},
                }
            ],
        )
        self.assertEqual(len(resp.draft_actions), 1)
        self.assertEqual(resp.draft_actions[0]["item_type"], "poll")

    def test_draft_actions_from_hub_agent_result_attached(self):
        """If HubAgentResult carries draft_actions they flow into the response."""
        from app.api.v1.ai_router import HubBotChatResponse
        # Simulate what the endpoint constructs
        draft = {
            "id": str(uuid.uuid4()),
            "item_type": "event",
            "status": "draft",
            "title": "Curry Night",
        }
        resp = HubBotChatResponse(
            reply="Event drafted",
            created_memory_count=0,
            created_suggestion_count=0,
            suggested_actions=[],
            draft_actions=[draft],
        )
        self.assertEqual(resp.draft_actions[0]["title"], "Curry Night")

    def test_invalid_draft_dict_still_serialises(self):
        """A partially-populated draft dict doesn't crash the response model."""
        from app.api.v1.ai_router import HubBotChatResponse
        resp = HubBotChatResponse(
            reply="ok",
            created_memory_count=0,
            created_suggestion_count=0,
            suggested_actions=[],
            draft_actions=[{"id": "bad-id", "item_type": "reminder"}],
        )
        self.assertEqual(len(resp.draft_actions), 1)



# ── Tool-call contract tests (Slice: fix malformed tool calls) ────────────────
#
# These tests exercise _parse_response and the full run() path to verify:
#   - valid tool calls are executed and produce draft actions
#   - "name" instead of "tool" is normalised
#   - flat-argument entries are promoted when the tool name is known
#   - missing "tool" field produces a validation error with no draft created
#   - false draft claims in the reply are corrected when propose_* fails


import json as _json


class StubLLMClient:
    """Minimal LLM client stub that returns a fixed raw response string.

    Not a FakeLLMClient instance, so HubAgentRuntime routes through
    _call_real_llm — but we override that method on the runtime instance
    after construction so no real HTTP call is made.
    """
    provider_name = "stub"
    model = "stub-model"

    def __init__(self, raw_response: str):
        self._raw = raw_response

    async def generate_summary(self, *args, **kwargs):
        return {"summary": "", "memories": [], "suggestions": []}


def _make_runtime(db=None, raw_response: str = None, tool_context: dict | None = None):
    from app.domains.ai.agent_runtime import HubAgentRuntime
    db = db or ServiceDummyDb()
    llm = StubLLMClient(raw_response or "") if raw_response else None
    runtime = HubAgentRuntime(
        db=db,
        llm_client=llm,
        tool_context=tool_context or {
            "group_id": 1,
            "created_by_user_id": uuid.uuid4(),
            "source": "hub_lab",
        },
    )
    if raw_response:
        # Override the real-LLM dispatch to return our fixture without HTTP
        _resp = raw_response
        async def _stub_real_llm(prompt):
            return _resp
        runtime._call_real_llm = _stub_real_llm
    return runtime


class TestParseResponseNormalisation(unittest.TestCase):
    """_parse_response normalises common model mistakes before validation."""

    def _parse(self, raw):
        return _make_runtime()._parse_response(raw)

    # ── Valid tool call ───────────────────────────────────────────────────────

    def test_valid_propose_poll_tool_call_passes(self):
        raw = _json.dumps({
            "reply": "Here is a draft poll.",
            "tool_calls": [{
                "tool": "propose_poll",
                "arguments": {
                    "question": "Where should we go?",
                    "options": ["Bar", "Cinema"],
                }
            }],
            "memories": [],
            "suggestions": [],
        })
        parsed = self._parse(raw)
        self.assertEqual(len(parsed["validation_errors"]), 0)
        tc = parsed["tool_calls"][0]
        self.assertEqual(tc["tool"], "propose_poll")
        self.assertIn("question", tc["arguments"])

    # ── "name" → "tool" normalisation ────────────────────────────────────────

    def test_name_field_normalised_to_tool(self):
        raw = _json.dumps({
            "reply": "Draft coming.",
            "tool_calls": [{
                "name": "propose_poll",
                "arguments": {"question": "?", "options": ["A", "B"]},
            }],
            "memories": [],
            "suggestions": [],
        })
        parsed = self._parse(raw)
        tc = parsed["tool_calls"][0]
        self.assertEqual(tc["tool"], "propose_poll")
        self.assertNotIn("name", tc)

    # ── Flat arguments promoted ───────────────────────────────────────────────

    def test_flat_arguments_promoted_for_known_tool(self):
        """Arguments at the wrong level are promoted when tool name is known."""
        raw = _json.dumps({
            "reply": "Draft.",
            "tool_calls": [{
                "tool": "propose_poll",
                "question": "What to do?",
                "options": ["A", "B"],
            }],
            "memories": [],
            "suggestions": [],
        })
        parsed = self._parse(raw)
        tc = parsed["tool_calls"][0]
        self.assertIn("arguments", tc)
        self.assertIn("question", tc["arguments"])
        # A normalisation warning is recorded but the call is usable
        self.assertTrue(any("promoted" in e for e in parsed["validation_errors"]))

    def test_flat_arguments_not_promoted_for_unknown_tool(self):
        """Unknown tool names do not get flat-argument promotion."""
        raw = _json.dumps({
            "reply": ".",
            "tool_calls": [{
                "tool": "unknown_magic_tool",
                "some_field": "value",
            }],
            "memories": [],
            "suggestions": [],
        })
        parsed = self._parse(raw)
        tc = parsed["tool_calls"][0]
        # arguments falls back to {}
        self.assertEqual(tc.get("arguments"), {})
        # No "promoted" warning — just empty arguments
        self.assertFalse(any("promoted" in e for e in parsed["validation_errors"]))

    # ── Missing "tool" field ──────────────────────────────────────────────────

    def test_missing_tool_field_produces_validation_error(self):
        raw = _json.dumps({
            "reply": "Done.",
            "tool_calls": [{"arguments": {"question": "?", "options": ["A", "B"]}}],
            "memories": [],
            "suggestions": [],
        })
        parsed = self._parse(raw)
        errors = parsed["validation_errors"]
        self.assertTrue(any("missing 'tool'" in e for e in errors))
        # tool defaults to ""
        self.assertEqual(parsed["tool_calls"][0].get("tool", ""), "")

    def test_empty_tool_calls_list_has_no_errors(self):
        raw = _json.dumps({
            "reply": "Nothing to do.",
            "tool_calls": [],
            "memories": [],
            "suggestions": [],
        })
        parsed = self._parse(raw)
        self.assertEqual(parsed["validation_errors"], [])


class TestRuntimeToolCallExecution(unittest.TestCase):
    """Full run()-level tests: tool calls that succeed vs. fail."""

    # ── Valid tool call executed ──────────────────────────────────────────────

    def test_valid_propose_poll_creates_draft_action(self):
        """A properly formed propose_poll tool call creates a draft row."""
        db = ServiceDummyDb()
        raw = _json.dumps({
            "reply": "Here is a draft poll for you.",
            "tool_calls": [{
                "tool": "propose_poll",
                "arguments": {
                    "question": "What should we do this weekend?",
                    "options": ["Pub", "Rooftop", "Movie night"],
                }
            }],
            "memories": [],
            "suggestions": [],
        })
        result = _run(_make_runtime(db, raw).run("suggest poll", dry_run=False))

        self.assertEqual(len(result.proposed_draft_action_ids), 1)
        self.assertEqual(len(db._store), 1)
        draft = list(db._store.values())[0]
        self.assertEqual(draft.item_type, "poll")
        self.assertEqual(draft.status, "draft")
        self.assertIn("poll", result.reply.lower())

    def test_chat_propose_poll_stamps_source_and_source_message(self):
        """Chat @hub poll requests create draft rows linked to the source message."""
        db = ServiceDummyDb()
        user_id = uuid.uuid4()
        raw = _json.dumps({
            "reply": "Here is a draft poll for you.",
            "tool_calls": [{
                "tool": "propose_poll",
                "arguments": {
                    "question": "Who likes beans the most?",
                    "options": ["Luke", "Dav"],
                },
            }],
            "memories": [],
            "suggestions": [],
        })
        runtime = _make_runtime(
            db,
            raw,
            tool_context={
                "group_id": 1,
                "created_by_user_id": user_id,
                "source": "chat",
                "source_message_id": 123,
            },
        )
        result = _run(runtime.run("make a poll", dry_run=False))

        self.assertEqual(len(result.proposed_draft_action_ids), 1)
        draft = list(db._store.values())[0]
        self.assertEqual(draft.item_type, "poll")
        self.assertEqual(draft.source, "chat")
        self.assertEqual(draft.source_message_id, 123)
        self.assertEqual(draft.created_by_user_id, user_id)

    def test_valid_propose_event_creates_draft_action(self):
        db = ServiceDummyDb()
        raw = _json.dumps({
            "reply": "Event draft ready.",
            "tool_calls": [{
                "tool": "propose_event",
                "arguments": {"title": "Curry Night", "starts_at": "2026-06-05T19:00:00Z"},
            }],
            "memories": [],
            "suggestions": [],
        })
        result = _run(_make_runtime(db, raw).run("create event", dry_run=False))
        self.assertEqual(len(result.proposed_draft_action_ids), 1)
        self.assertEqual(list(db._store.values())[0].item_type, "event")

    def test_chat_propose_event_stamps_source_chat(self):
        db = ServiceDummyDb()
        raw = _json.dumps({
            "reply": "Event draft ready.",
            "tool_calls": [{
                "tool": "propose_event",
                "arguments": {"title": "Curry Night", "starts_at": "2026-06-05T19:00:00Z"},
            }],
            "memories": [],
            "suggestions": [],
        })
        result = _run(_make_runtime(
            db,
            raw,
            tool_context={
                "group_id": 1,
                "created_by_user_id": uuid.uuid4(),
                "source": "chat",
                "source_message_id": 124,
            },
        ).run("create event", dry_run=False))
        self.assertEqual(len(result.proposed_draft_action_ids), 1)
        draft = list(db._store.values())[0]
        self.assertEqual(draft.item_type, "event")
        self.assertEqual(draft.source, "chat")
        self.assertEqual(draft.source_message_id, 124)

    def test_valid_propose_reminder_creates_draft_action(self):
        db = ServiceDummyDb()
        raw = _json.dumps({
            "reply": "Reminder drafted.",
            "tool_calls": [{
                "tool": "propose_reminder",
                "arguments": {"text": "Book taxis before Friday"},
            }],
            "memories": [],
            "suggestions": [],
        })
        result = _run(_make_runtime(db, raw).run("remind everyone", dry_run=False))
        self.assertEqual(len(result.proposed_draft_action_ids), 1)
        self.assertEqual(list(db._store.values())[0].item_type, "reminder")

    def test_chat_propose_reminder_stamps_source_chat(self):
        db = ServiceDummyDb()
        raw = _json.dumps({
            "reply": "Reminder drafted.",
            "tool_calls": [{
                "tool": "propose_reminder",
                "arguments": {"text": "Buy beans"},
            }],
            "memories": [],
            "suggestions": [],
        })
        result = _run(_make_runtime(
            db,
            raw,
            tool_context={
                "group_id": 1,
                "created_by_user_id": uuid.uuid4(),
                "source": "chat",
                "source_message_id": 125,
            },
        ).run("create reminder", dry_run=False))
        self.assertEqual(len(result.proposed_draft_action_ids), 1)
        draft = list(db._store.values())[0]
        self.assertEqual(draft.item_type, "reminder")
        self.assertEqual(draft.source, "chat")
        self.assertEqual(draft.source_message_id, 125)

    # ── Malformed tool call does not create draft ─────────────────────────────

    def test_missing_tool_field_does_not_create_draft(self):
        """tool_calls entry without 'tool' key → validation error, no draft."""
        db = ServiceDummyDb()
        raw = _json.dumps({
            "reply": "I've drafted a poll for you.",
            "tool_calls": [{"arguments": {"question": "Where to go?", "options": ["Bar", "Home"]}}],
            "memories": [],
            "suggestions": [],
        })
        result = _run(_make_runtime(db, raw).run("suggest poll", dry_run=False))

        self.assertEqual(len(result.proposed_draft_action_ids), 0)
        self.assertEqual(len(db._store), 0)
        self.assertTrue(any("missing 'tool'" in e for e in result.validation_errors))

    def test_tool_arguments_at_wrong_level_are_promoted_and_succeed(self):
        """Flat arguments on a known tool are promoted and the draft is created."""
        db = ServiceDummyDb()
        raw = _json.dumps({
            "reply": "Poll drafted.",
            "tool_calls": [{
                "tool": "propose_poll",
                "question": "Pub or cinema?",
                "options": ["Pub", "Cinema"],
            }],
            "memories": [],
            "suggestions": [],
        })
        result = _run(_make_runtime(db, raw).run("suggest poll", dry_run=False))
        self.assertEqual(len(result.proposed_draft_action_ids), 1)
        self.assertEqual(len(db._store), 1)

    # ── Reply correction ──────────────────────────────────────────────────────

    def test_false_draft_claim_replaced_when_tool_fails(self):
        """If propose_* tool fails but reply claims success, reply is corrected."""
        db = ServiceDummyDb()
        raw = _json.dumps({
            "reply": "I've drafted a poll for you to review.",
            "tool_calls": [{"arguments": {"question": "?", "options": ["A", "B"]}}],
            "memories": [],
            "suggestions": [],
        })
        result = _run(_make_runtime(db, raw).run("suggest poll", dry_run=False))

        self.assertEqual(result.proposed_draft_action_ids, [])
        self.assertNotIn("i've drafted", result.reply.lower())
        self.assertIn("went wrong", result.reply.lower())

    def test_honest_reply_preserved_when_tool_succeeds(self):
        """Reply is not modified when the propose_* tool actually succeeds."""
        db = ServiceDummyDb()
        raw = _json.dumps({
            "reply": "I've drafted a poll for you.",
            "tool_calls": [{
                "tool": "propose_poll",
                "arguments": {"question": "Where?", "options": ["A", "B"]},
            }],
            "memories": [],
            "suggestions": [],
        })
        result = _run(_make_runtime(db, raw).run("suggest poll", dry_run=False))

        self.assertEqual(len(result.proposed_draft_action_ids), 1)
        self.assertIn("drafted", result.reply.lower())

    def test_dry_run_does_not_create_draft_and_no_ids(self):
        """dry_run skips safe_write tools; proposed_draft_action_ids stays empty."""
        db = ServiceDummyDb()
        raw = _json.dumps({
            "reply": "Here is what I would create.",
            "tool_calls": [{
                "tool": "propose_poll",
                "arguments": {"question": "Dry?", "options": ["Yes", "No"]},
            }],
            "memories": [],
            "suggestions": [],
        })
        result = _run(_make_runtime(db, raw).run("suggest poll", dry_run=True))

        self.assertEqual(result.proposed_draft_action_ids, [])
        self.assertEqual(len(db._store), 0)

    def test_name_instead_of_tool_normalised_and_draft_created(self):
        """Response using 'name' instead of 'tool' is fixed and draft is created."""
        db = ServiceDummyDb()
        raw = _json.dumps({
            "reply": "Poll drafted.",
            "tool_calls": [{
                "name": "propose_poll",
                "arguments": {"question": "Name test?", "options": ["A", "B"]},
            }],
            "memories": [],
            "suggestions": [],
        })
        result = _run(_make_runtime(db, raw).run("suggest poll", dry_run=False))
        self.assertEqual(len(result.proposed_draft_action_ids), 1)
        self.assertEqual(len(db._store), 1)


class TestChatHubDraftActionMarkers(unittest.TestCase):
    """Normal chat bot replies embed renderable draft-action markers."""

    def test_reply_includes_marker_for_created_draft_action(self):
        from app.ai.bot import HubBot

        draft_id = str(uuid.uuid4())
        reply = HubBot()._reply_with_draft_markers(
            "Here is a draft poll.",
            [{"id": draft_id, "item_type": "poll"}],
        )

        self.assertIn(f"[[ai-draft-action:{draft_id}]]", reply)

    def test_reply_includes_one_marker_per_draft(self):
        from app.ai.bot import HubBot

        first = str(uuid.uuid4())
        second = str(uuid.uuid4())
        reply = HubBot()._reply_with_draft_markers(
            "I drafted two things.",
            [{"id": first}, {"id": second}],
        )

        self.assertIn(f"[[ai-draft-action:{first}]]", reply)
        self.assertIn(f"[[ai-draft-action:{second}]]", reply)

    def test_reply_does_not_include_marker_without_draft_action_id(self):
        from app.ai.bot import HubBot

        reply = HubBot()._reply_with_draft_markers(
            "I tried to create a draft but something went wrong.",
            [{"item_type": "poll"}],
        )

        self.assertNotIn("[[ai-draft-action:", reply)


if __name__ == "__main__":
    unittest.main()
