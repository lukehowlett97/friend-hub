import asyncio
import os
import types
import unittest
import uuid
from datetime import datetime

os.environ["DEBUG"] = "false"
os.environ.setdefault("DATABASE_PASSWORD", "changeme")

from app.api.v1 import router
from app.api.v1.router import HubItemCreateRequest, HubItemPinRequest, create_hub_item, get_hub_items, pin_hub_item, send_hub_item_to_chat
from app.domains.hub_items.references import find_hub_item_references
from app.models.hub_item import HubItem
from app.models.message import Message
from app.models.room import DEFAULT_ROOM_ID


class DummyDb:
    def __init__(self):
        self.added = []
        self.flushed = False
        self.committed = False

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        self.flushed = True
        for value in self.added:
            if isinstance(value, Message) and value.id is None:
                value.id = 42
            if isinstance(value, HubItem) and value.id is None:
                value.id = uuid.uuid4()

    async def commit(self):
        self.committed = True

    async def refresh(self, value):
        return None

    async def execute(self, stmt):
        return types.SimpleNamespace(scalar_one_or_none=lambda: None)


class TestHubItemReferences(unittest.TestCase):
    def test_finds_supported_short_ids(self):
        # Default-prefix refs resolve to a known type up front. Other
        # letter-prefixed refs (e.g. #X-1, #mike-rename) are now treated as
        # custom short_ids — they still match but carry type=None so the
        # caller has to look up the actual hub_item in the DB.
        refs = find_hub_item_references("Check #R-21 and #P-7 plus #X-1")

        self.assertEqual([ref["short_id"] for ref in refs], ["#R-21", "#P-7", "#X-1"])
        self.assertEqual(refs[0]["type"], "reminder")
        self.assertEqual(refs[1]["sequence"], 7)
        self.assertIsNone(refs[2]["type"])
        self.assertIsNone(refs[2]["sequence"])


class TestHubItemModel(unittest.TestCase):
    def test_required_columns_present(self):
        cols = {column.key for column in HubItem.__table__.columns}

        for name in {
            "id",
            "short_id",
            "item_type",
            "title",
            "body",
            "tags",
            "status",
            "pinned_to_home",
            "sent_to_chat_at",
            "chat_message_id",
            "created_by_user_id",
            "assigned_to_user_id",
            "due_at",
            "event_start_at",
            "event_end_at",
        }:
            self.assertIn(name, cols)


class TestHubItemEndpoints(unittest.TestCase):
    def setUp(self):
        self.original_current_user = router._current_user_or_401
        self.original_default_group = router._default_group
        self.original_next_sequence = router._next_hub_item_sequence
        self.original_payloads = router._hub_item_payloads
        self.original_item_by_id = router._hub_item_by_id_or_404
        self.original_request_room_id = router._request_room_id

        self.user = types.SimpleNamespace(
            id=uuid.uuid4(),
            session_id=uuid.uuid4(),
            nickname="Luke",
            username="luke",
            role=types.SimpleNamespace(value="owner"),
        )
        self.group = types.SimpleNamespace(id=1)
        router._current_user_or_401 = lambda authorization, db, session_cookie=None: self._async(self.user)
        router._default_group = lambda db: self._async(self.group)
        router._next_hub_item_sequence = lambda db, item_type: self._async(3)
        router._request_room_id = lambda db, **kwargs: self._async(DEFAULT_ROOM_ID)

    def tearDown(self):
        router._current_user_or_401 = self.original_current_user
        router._default_group = self.original_default_group
        router._next_hub_item_sequence = self.original_next_sequence
        router._hub_item_payloads = self.original_payloads
        router._hub_item_by_id_or_404 = self.original_item_by_id
        router._request_room_id = self.original_request_room_id

    @staticmethod
    async def _async(value):
        return value

    def _item(self):
        item = HubItem(
            id=uuid.uuid4(),
            group_id=1,
            room_id=DEFAULT_ROOM_ID,
            item_type="reminder",
            type_sequence=21,
            short_id="#R-21",
            title="eat beans",
            body="eat beans",
            status="open",
            tags=[],
            created_by_user_id=self.user.id,
        )
        item.created_at = datetime.utcnow()
        item.updated_at = datetime.utcnow()
        return item

    def test_create_hub_item_assigns_short_id(self):
        db = DummyDb()

        response = asyncio.run(create_hub_item(HubItemCreateRequest(type="note", title="A note"), db=db))

        item = db.added[0]
        self.assertEqual(item.short_id, "#N-3")
        self.assertEqual(item.item_type, "note")
        self.assertTrue(db.committed)
        self.assertEqual(response["item"]["short_id"], "#N-3")

    def test_create_hub_item_uses_resolved_room_id(self):
        room_id = uuid.uuid4()
        router._request_room_id = lambda db, **kwargs: self._async(room_id)
        db = DummyDb()

        asyncio.run(create_hub_item(HubItemCreateRequest(type="note", title="A note"), db=db))

        item = db.added[0]
        self.assertEqual(item.room_id, room_id)

    def test_filtering_passes_type_to_payload_query(self):
        captured = {}

        async def fake_payloads(db, group_id, **kwargs):
            captured.update(kwargs)
            return []

        router._hub_item_payloads = fake_payloads

        response = asyncio.run(get_hub_items(type="idea", db=DummyDb()))

        self.assertEqual(captured["item_type"], "idea")
        self.assertEqual(captured["room_id"], DEFAULT_ROOM_ID)
        self.assertEqual(response["total"], 0)

    def test_pin_hub_item_updates_flag(self):
        item = self._item()
        router._hub_item_by_id_or_404 = lambda db, group_id, item_id, room_id=None: self._async(item)

        response = asyncio.run(pin_hub_item(str(item.id), HubItemPinRequest(pinned=True), db=DummyDb()))

        self.assertTrue(item.pinned_to_home)
        self.assertEqual(response["item"]["short_id"], "#R-21")

    def test_send_to_chat_creates_message_and_links_item(self):
        item = self._item()
        db = DummyDb()
        router._hub_item_by_id_or_404 = lambda db, group_id, item_id, room_id=None: self._async(item)

        response = asyncio.run(send_hub_item_to_chat(str(item.id), db=db))

        message = next(value for value in db.added if isinstance(value, Message))
        self.assertIn("Luke shared #R-21", message.content)
        self.assertEqual(message.hub_item_id, item.id)
        self.assertEqual(message.room_id, DEFAULT_ROOM_ID)
        self.assertEqual(item.chat_message_id, 42)
        self.assertEqual(response["message_id"], 42)

    def test_hub_item_for_source_preserves_existing_tags_when_tags_not_provided(self):
        item = self._item()
        item.tags = ["beans", "pub"]

        class ExistingHubItemDb(DummyDb):
            async def execute(self, stmt):
                return types.SimpleNamespace(scalar_one_or_none=lambda: item)

        db = ExistingHubItemDb()

        asyncio.run(router._hub_item_for_source(
            db,
            group_id=1,
            item_type="reminder",
            source_id=21,
            title="eat beans",
            body="eat beans",
            created_by_user_id=self.user.id,
        ))

        self.assertEqual(item.tags, ["beans", "pub"])
