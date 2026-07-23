import json
import asyncio
import tempfile
import unittest
import uuid
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.importers.facebook_messenger.cli import _output_payload
from app.importers.facebook_messenger.discovery import discover_chats, inspect_chat
from app.importers.facebook_messenger.encoding import repair_text
from app.importers.facebook_messenger.importer import dry_run_chat, import_chat, resolve_chat_dir
from app.importers.facebook_messenger.parser import normalize_messages, parse_chat_messages, source_hash
from app.importers.facebook_messenger.sender_map import load_sender_map
from app.domains.image_embeddings.service import embedding_settings
from app.domains.photos.service import ProcessedPhoto
from app.models.import_tracking import ExternalIdentity, ImportBatch, ImportedMessageSource
from app.models.imported_identity import ImportedIdentity
from app.models.member import GroupMember
from app.models.photo import Photo
from app.models.photo_embedding import PhotoEmbeddingJob
from app.models.planning import Group
from app.models.reaction import Reaction
from app.models.room import DEFAULT_ROOM_ID, Room
from app.models.message import Message, User
from app.models.video import AudioFile, Video


class TestMessengerEncoding(unittest.TestCase):
    def test_repairs_common_mojibake(self):
        self.assertEqual(repair_text("Youâ€™ve"), "You've")

    def test_repairs_emoji_mojibake(self):
        self.assertEqual(repair_text("ð"), "😈")

    def test_preserves_valid_unicode(self):
        self.assertEqual(repair_text("Already fine 😈"), "Already fine 😈")


class TestMessengerDiscoveryAndParser(unittest.TestCase):
    def test_discovery_detects_valid_chat_and_ignores_unrelated_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            chat_dir = root / "your_facebook_activity" / "messages" / "inbox" / "group_123"
            chat_dir.mkdir(parents=True)
            (root / "other.json").write_text("{}", encoding="utf-8")
            _write_message_file(chat_dir / "message_1.json", [
                {"sender_name": "Alice", "timestamp_ms": 1000, "content": "Hi"},
                {"sender_name": "Bob", "timestamp_ms": 2000, "photos": [{"uri": "photos/a.jpg"}]},
            ])

            chats = discover_chats(root)

            self.assertEqual(len(chats), 1)
            self.assertEqual(chats[0].title, "Test Chat")
            self.assertEqual(chats[0].participant_count, 2)
            self.assertEqual(chats[0].message_count, 2)
            self.assertTrue(chats[0].has_media)
            self.assertEqual(chats[0].oldest_at.isoformat(), "1970-01-01T00:00:01")
            self.assertEqual(chats[0].newest_at.isoformat(), "1970-01-01T00:00:02")

    def test_parser_merges_files_chronologically_and_skips_media_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            chat_dir = Path(tmp) / "chat"
            chat_dir.mkdir()
            _write_message_file(chat_dir / "message_2.json", [
                {"sender_name": "Alice", "timestamp_ms": 3000, "content": "Three"},
            ])
            _write_message_file(chat_dir / "message_1.json", [
                {"sender_name": "Bob", "timestamp_ms": 1000, "content": "One"},
                {"sender_name": "Alice", "timestamp_ms": 2000, "gifs": [{"uri": "gifs/a.gif"}]},
            ])

            parsed = parse_chat_messages(chat_dir)
            normalized = normalize_messages(parsed, "inbox/group_123")

            self.assertEqual([message.timestamp_ms for message in parsed], [1000, 2000, 3000])
            self.assertEqual([message.content for message in normalized.messages], ["One", "Three"])
            self.assertEqual(normalized.skipped_media_count, 1)

    def test_source_hash_is_deterministic(self):
        raw = {"sender_name": "Alice", "timestamp_ms": 1000, "content": "Hi"}

        first = source_hash("thread", "Alice", 1000, "Hi", raw)
        second = source_hash("thread", "Alice", 1000, "Hi", raw)

        self.assertEqual(first, second)

    def test_resolve_chat_dir_finds_named_messenger_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            chat_dir = root / "your_facebook_activity" / "messages" / "inbox" / "group_123"
            chat_dir.mkdir(parents=True)
            _write_message_file(chat_dir / "message_1.json", [])

            self.assertEqual(resolve_chat_dir(root, "group_123"), chat_dir.resolve())

    def test_sender_map_accepts_string_and_object_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sender_map.json"
            path.write_text(json.dumps({
                "Alice": "alice",
                "Bob": {"username": "bob", "session_id": "session-1"},
            }), encoding="utf-8")

            mapping = load_sender_map(path)

            self.assertEqual(mapping["Alice"]["nickname"], "alice")
            self.assertEqual(mapping["Bob"]["username"], "bob")


class TestMessengerCliOutput(unittest.TestCase):
    def test_summarizes_errors_by_default(self):
        payload = {
            "status": "completed",
            "errors": (
                {"type": "media_file_not_found"},
                {"type": "media_file_not_found"},
                {"type": "content_too_long"},
            ),
        }

        output = _output_payload(payload, verbose_errors=False)

        self.assertNotIn("errors", output)
        self.assertEqual(output["error_details_omitted"], 3)
        self.assertEqual(output["error_summary"], {
            "content_too_long": 1,
            "media_file_not_found": 2,
        })

    def test_keeps_errors_when_verbose(self):
        payload = {"status": "completed", "errors": ({"type": "content_too_long"},)}

        output = _output_payload(payload, verbose_errors=True)

        self.assertIn("errors", output)
        self.assertEqual(output["error_summary"], {"content_too_long": 1})


class TestMessengerImportModels(unittest.TestCase):
    def test_import_tracking_models_are_registered(self):
        from app.models import Base

        self.assertIn("import_batches", Base.metadata.tables)
        self.assertIn("imported_message_sources", Base.metadata.tables)
        self.assertIn("external_identities", Base.metadata.tables)
        self.assertIn("photo_embedding_jobs", Base.metadata.tables)
        self.assertIn("photo_embeddings", Base.metadata.tables)

    def test_source_message_has_provider_hash_unique_constraint(self):
        constraint_names = {constraint.name for constraint in ImportedMessageSource.__table__.constraints}

        self.assertIn("uq_imported_message_provider_hash", constraint_names)

    def test_existing_source_hashes_requires_existing_message_row(self):
        from app.importers.facebook_messenger.importer import _existing_source_hashes

        class Db:
            def __init__(self):
                self.statement = None

            async def execute(self, stmt):
                self.statement = stmt
                return FakeResult([])

        db = Db()
        result = asyncio.run(_existing_source_hashes(db, ["hash-1"]))

        self.assertEqual(result, set())
        self.assertIn("JOIN messages", str(db.statement))


class TestMessengerDbImport(unittest.IsolatedAsyncioTestCase):
    async def test_import_is_idempotent_and_reuses_placeholder_user(self):
        with tempfile.TemporaryDirectory() as tmp:
            chat_dir = Path(tmp) / "chat"
            chat_dir.mkdir()
            video_dir = chat_dir / "videos"
            video_dir.mkdir(parents=True)
            (video_dir / "a.mp4").write_bytes(b"not-a-real-video")
            _write_message_file(chat_dir / "message_1.json", [
                {"sender_name": "Alice", "timestamp_ms": 1000, "content": "Youâ€™ve got this"},
                {"sender_name": "Alice", "timestamp_ms": 2000, "videos": [{"uri": "videos/a.mp4"}]},
            ])
            db = FakeAsyncSession()

            with patch("app.importers.facebook_messenger.importer.get_video_upload_path", return_value=Path(tmp) / "uploads" / "videos"):
                first = await import_chat(chat_dir, db)
                second = await import_chat(chat_dir, db)

            self.assertEqual(first.errors, ())
            self.assertEqual(first.imported_count, 2)
            self.assertEqual(first.media_count, 1)
            self.assertEqual(second.imported_count, 0)
            self.assertEqual(second.skipped_count, 2)
            self.assertEqual(len(db.messages), 2)
            self.assertEqual(len(db.videos), 1)
            self.assertEqual(len(db.photo_embedding_jobs), 0)
            self.assertEqual(db.messages[0].content, "You've got this")
            self.assertTrue(db.messages[1].content.startswith("Video: a.mp4\n/uploads/videos/"))
            self.assertTrue(db.messages[0].is_imported)
            self.assertEqual(len(db.users), 1)
            self.assertFalse(db.users[0].is_active)
            self.assertEqual(db.users[0].user_type, "system")
            self.assertTrue(db.users[0].hidden_from_member_list)
            self.assertEqual(len(db.identities), 1)
            self.assertEqual(len(db.imported_identities), 1)
            self.assertEqual(db.imported_identities[0].source_display_name, "Alice")
            self.assertEqual(db.imported_identities[0].message_count, 2)
            self.assertEqual(db.messages[0].imported_identity_id, db.imported_identities[0].id)

    async def test_import_adds_reactions_and_supported_gif_media_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            chat_dir = Path(tmp) / "chat"
            gif_dir = chat_dir / "gifs"
            gif_dir.mkdir(parents=True)
            (gif_dir / "a.gif").write_bytes(b"GIF89a")
            _write_message_file(chat_dir / "message_1.json", [
                {
                    "sender_name": "Alice",
                    "timestamp_ms": 1000,
                    "content": "React to this",
                    "reactions": [{"reaction": "ð", "actor": "Bob"}],
                },
                {"sender_name": "Bob", "timestamp_ms": 2000, "gifs": [{"uri": "gifs/a.gif"}]},
            ])
            db = FakeAsyncSession()
            with patch("app.importers.facebook_messenger.importer.get_photo_upload_path", return_value=Path(tmp) / "uploads"):
                summary = await import_chat(chat_dir, db, export_root=Path(tmp))

            self.assertEqual(summary.imported_count, 2)
            self.assertEqual(summary.reaction_count, 1)
            self.assertEqual(summary.media_count, 1)
            self.assertEqual(len(db.reactions), 1)
            self.assertEqual(db.reactions[0].emoji, "😈")
            self.assertEqual(len(db.imported_identities), 2)
            self.assertEqual(len(db.photos), 1)
            self.assertEqual(len(db.photo_embedding_jobs), 0)
            self.assertTrue(db.messages[1].content.startswith("Photo: a.gif\n/uploads/photos/"))

    async def test_import_creates_photo_and_pending_embedding_job_for_photo_media(self):
        with tempfile.TemporaryDirectory() as tmp:
            chat_dir = Path(tmp) / "chat"
            photo_dir = chat_dir / "photos"
            photo_dir.mkdir(parents=True)
            (photo_dir / "a.jpg").write_bytes(b"fake-image")
            _write_message_file(chat_dir / "message_1.json", [
                {"sender_name": "Alice", "timestamp_ms": 1000, "photos": [{"uri": "photos/a.jpg"}]},
            ])
            db = FakeAsyncSession()
            processed = ProcessedPhoto(
                display_bytes=b"display",
                thumbnail_bytes=b"thumb",
                width=640,
                height=480,
            )

            settings = SimpleNamespace(
                photo_display_max_width=1600,
                photo_thumbnail_max_width=480,
                photo_jpeg_quality=82,
                photo_storage_max_bytes=1024 * 1024,
            )
            image_settings = embedding_settings()

            with patch("app.importers.facebook_messenger.importer.get_settings", return_value=settings), \
                 patch("app.domains.image_embeddings.service.get_settings", return_value=image_settings), \
                 patch("app.importers.facebook_messenger.importer.get_photo_upload_path", return_value=Path(tmp) / "uploads"), \
                 patch("app.importers.facebook_messenger.importer.process_photo_upload", return_value=processed):
                first = await import_chat(chat_dir, db, export_root=Path(tmp), target_room_id="main")
                second = await import_chat(chat_dir, db, export_root=Path(tmp), target_room_id="main")

            self.assertEqual(first.errors, ())
            self.assertEqual(first.imported_count, 1)
            self.assertEqual(second.imported_count, 0)
            self.assertEqual(len(db.photos), 1)
            self.assertEqual(db.messages[0].room_id, DEFAULT_ROOM_ID)
            self.assertEqual(db.photos[0].room_id, DEFAULT_ROOM_ID)
            self.assertEqual(len(db.photo_embedding_jobs), 1)
            self.assertEqual(db.photo_embedding_jobs[0].photo_id, db.photos[0].id)
            self.assertEqual(db.photo_embedding_jobs[0].status, "pending")
            self.assertEqual(db.photos[0].source_type, "messenger_import")
            self.assertEqual(db.photos[0].message_id, db.messages[0].id)
            self.assertEqual(db.photos[0].import_batch_id, first.batch_id)
            self.assertEqual(db.photos[0].conversation_id, "main")
            self.assertTrue(db.photos[0].storage_path.startswith("/uploads/photos/"))

    async def test_dry_run_reports_counts_without_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            chat_dir = root / "your_facebook_activity" / "messages" / "inbox" / "group_123"
            chat_dir.mkdir(parents=True)
            _write_message_file(chat_dir / "message_1.json", [
                {"sender_name": "Alice", "timestamp_ms": 1000, "content": "Hi"},
                {"sender_name": "Bob", "timestamp_ms": 2000, "gifs": [{"uri": "gifs/a.gif"}]},
            ])
            db = FakeAsyncSession()

            summary = await dry_run_chat(root, "group_123", "main", db, sender_map={"Alice": {"nickname": "Alice"}})

            self.assertEqual(summary.text_count, 1)
            self.assertEqual(summary.supported_media_count, 1)
            self.assertEqual(summary.target_room_id, "main")
            self.assertEqual(len(db.messages), 0)

    async def test_oversized_content_is_counted_as_error_without_aborting(self):
        with tempfile.TemporaryDirectory() as tmp:
            chat_dir = Path(tmp) / "chat"
            chat_dir.mkdir()
            _write_message_file(chat_dir / "message_1.json", [
                {"sender_name": "Alice", "timestamp_ms": 1000, "content": "A" * 1001},
                {"sender_name": "Bob", "timestamp_ms": 2000, "content": "ok"},
            ])
            db = FakeAsyncSession()

            summary = await import_chat(chat_dir, db)

            self.assertEqual(summary.imported_count, 1)
            self.assertEqual(summary.error_count, 1)
            self.assertEqual(summary.errors[0]["type"], "content_too_long")
            self.assertEqual(len(db.messages), 1)

    async def test_missing_supported_media_is_counted_as_error_without_aborting(self):
        with tempfile.TemporaryDirectory() as tmp:
            chat_dir = Path(tmp) / "chat"
            chat_dir.mkdir()
            _write_message_file(chat_dir / "message_1.json", [
                {"sender_name": "Alice", "timestamp_ms": 1000, "gifs": [{"uri": "gifs/missing.gif"}]},
                {"sender_name": "Bob", "timestamp_ms": 2000, "content": "ok"},
            ])
            db = FakeAsyncSession()

            summary = await import_chat(chat_dir, db, export_root=Path(tmp))

            self.assertEqual(summary.status, "completed")
            self.assertEqual(summary.imported_count, 1)
            self.assertEqual(summary.error_count, 1)
            self.assertEqual(summary.errors[0]["type"], "media_file_not_found")
            self.assertEqual(len(db.messages), 1)

    async def test_import_adds_placeholder_sender_to_target_group(self):
        with tempfile.TemporaryDirectory() as tmp:
            chat_dir = Path(tmp) / "chat"
            chat_dir.mkdir()
            _write_message_file(chat_dir / "message_1.json", [
                {"sender_name": "Alice", "timestamp_ms": 1000, "content": "hello"},
            ])
            db = FakeAsyncSession()

            summary = await import_chat(chat_dir, db, target_room_id="main")

            self.assertEqual(summary.imported_count, 1)
            self.assertEqual(db.messages[0].room_id, DEFAULT_ROOM_ID)
            self.assertEqual(len(db.memberships), 1)
            self.assertEqual(db.memberships[0].group_id, 1)
            self.assertEqual(db.memberships[0].user_session_id, db.users[0].session_id)

    async def test_import_uses_linked_imported_identity_for_future_messages_and_reactions(self):
        with tempfile.TemporaryDirectory() as tmp:
            chat_dir = Path(tmp) / "chat"
            chat_dir.mkdir()
            _write_message_file(chat_dir / "message_1.json", [
                {
                    "sender_name": "Alice",
                    "timestamp_ms": 1000,
                    "content": "hello",
                    "reactions": [{"reaction": "ð", "actor": "Alice"}],
                },
            ])
            db = FakeAsyncSession()
            linked_user = User(
                id=uuid.uuid4(),
                session_id=uuid.uuid4(),
                username="alice",
                nickname="Alice",
                is_active=True,
                user_type="human",
                status="active",
            )
            db.users.append(linked_user)
            db.imported_identities.append(ImportedIdentity(
                id=uuid.uuid4(),
                source="messenger",
                source_display_name="Alice",
                normalised_name="alice",
                linked_user_id=linked_user.id,
                status="linked",
                message_count=0,
            ))

            summary = await import_chat(chat_dir, db)

            self.assertEqual(summary.imported_count, 1)
            self.assertEqual(summary.reaction_count, 1)
            self.assertEqual(len(db.users), 1)
            self.assertEqual(db.messages[0].user_id, linked_user.id)
            self.assertEqual(db.messages[0].user_session_id, linked_user.session_id)
            self.assertEqual(db.reactions[0].user_id, linked_user.id)
            self.assertEqual(db.reactions[0].user_session_id, linked_user.session_id)
            self.assertEqual(len(db.identities), 1)
            self.assertEqual(db.identities[0].user_id, linked_user.id)
            self.assertEqual(db.identities[0].user_session_id, linked_user.session_id)

    async def test_import_reattaches_orphan_imported_message_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            chat_dir = Path(tmp) / "chat"
            chat_dir.mkdir()
            raw_message = {"sender_name": "Alice", "timestamp_ms": 1000, "content": "hello"}
            _write_message_file(chat_dir / "message_1.json", [raw_message])
            record_hash = source_hash(
                source_thread_path="inbox/group_123",
                sender_name="Alice",
                timestamp_ms=1000,
                content="hello",
                raw=raw_message,
            )
            db = FakeAsyncSession()
            db.sources.append(ImportedMessageSource(
                id=99,
                batch_id=1,
                provider="facebook_messenger",
                source_thread_path="inbox/group_123",
                target_room_id="main",
                source_hash=record_hash,
                message_id=9999,
                raw_sender_name="Alice",
                source_timestamp=datetime.fromtimestamp(1),
                raw_metadata={},
            ))

            summary = await import_chat(chat_dir, db, target_room_id="main")

            self.assertEqual(summary.imported_count, 1)
            self.assertEqual(len(db.sources), 1)
            self.assertEqual(db.sources[0].message_id, db.messages[0].id)


class FakeAsyncSession:
    def __init__(self):
        self.batches = []
        self.identities = []
        self.imported_identities = []
        self.sources = []
        self.users = []
        self.messages = []
        self.photos = []
        self.videos = []
        self.audio_files = []
        self.reactions = []
        self.photo_embedding_jobs = []
        self.groups = [Group(id=1, slug="main", name="Friend Hub")]
        self.rooms = [Room(id=DEFAULT_ROOM_ID, slug="main", name="Main Space")]
        self.memberships = []
        self._next_batch_id = 1
        self._next_source_id = 1
        self._next_identity_id = 1
        self._next_message_id = 1
        self._next_photo_id = 1
        self._next_video_id = 1
        self._next_audio_id = 1
        self._next_reaction_id = 1
        self._next_photo_embedding_job_id = 1

    def add(self, obj):
        if isinstance(obj, ImportBatch):
            obj.id = self._next_batch_id
            self._next_batch_id += 1
            self.batches.append(obj)
        elif isinstance(obj, ExternalIdentity):
            obj.id = self._next_identity_id
            self._next_identity_id += 1
            self.identities.append(obj)
        elif isinstance(obj, ImportedIdentity):
            obj.id = uuid.UUID(int=self._next_identity_id)
            self._next_identity_id += 1
            self.imported_identities.append(obj)
        elif isinstance(obj, ImportedMessageSource):
            obj.id = self._next_source_id
            self._next_source_id += 1
            self.sources.append(obj)
        elif isinstance(obj, Message):
            obj.id = self._next_message_id
            self._next_message_id += 1
            self.messages.append(obj)
        elif isinstance(obj, Photo):
            obj.id = self._next_photo_id
            self._next_photo_id += 1
            self.photos.append(obj)
        elif isinstance(obj, Video):
            obj.id = self._next_video_id
            self._next_video_id += 1
            self.videos.append(obj)
        elif isinstance(obj, AudioFile):
            obj.id = self._next_audio_id
            self._next_audio_id += 1
            self.audio_files.append(obj)
        elif isinstance(obj, Reaction):
            obj.id = self._next_reaction_id
            self._next_reaction_id += 1
            self.reactions.append(obj)
        elif isinstance(obj, PhotoEmbeddingJob):
            obj.id = self._next_photo_embedding_job_id
            self._next_photo_embedding_job_id += 1
            self.photo_embedding_jobs.append(obj)
        elif isinstance(obj, GroupMember):
            self.memberships.append(obj)
        elif isinstance(obj, User):
            self.users.append(obj)
        else:
            raise AssertionError(f"Unexpected object added: {obj!r}")

    async def flush(self):
        return None

    async def commit(self):
        return None

    async def rollback(self):
        return None

    async def execute(self, stmt):
        if getattr(stmt, "is_update", False):
            return FakeResult([])

        entity = stmt.column_descriptions[0].get("entity")
        expr = stmt.column_descriptions[0].get("expr")
        filters = _filters(stmt)

        if getattr(expr, "key", None) == "session_id":
            nickname = filters.get("nickname")
            row = next((user.session_id for user in self.users if user.nickname == nickname), None)
            return FakeResult([row] if row else [])

        if entity is ImportedMessageSource:
            source_hash = filters.get("source_hash")
            if source_hash and not isinstance(source_hash, list):
                row = next((source for source in self.sources if source.source_hash == source_hash), None)
                return FakeResult([row] if row else [])
            values = filters.get("source_hash")
            if isinstance(values, list):
                message_ids = {message.id for message in self.messages}
                rows = [
                    source.source_hash
                    for source in self.sources
                    if source.source_hash in values and source.message_id in message_ids
                ]
                return FakeResult(rows)

        if entity is ExternalIdentity:
            external_name = filters.get("external_name")
            row = next((identity for identity in self.identities if identity.external_name == external_name), None)
            return FakeResult([row] if row else [])

        if entity is ImportedIdentity:
            normalised_name = filters.get("normalised_name")
            row = next((identity for identity in self.imported_identities if identity.normalised_name == normalised_name), None)
            return FakeResult([row] if row else [])

        if entity is User:
            if "session_id" in filters:
                row = next((user for user in self.users if user.session_id == filters["session_id"]), None)
            elif "id" in filters:
                row = next((user for user in self.users if user.id == filters["id"]), None)
            elif "nickname" in filters:
                row = next((user for user in self.users if user.nickname == filters["nickname"]), None)
            else:
                row = None
            return FakeResult([row] if row else [])

        if entity is Group:
            if "id" in filters:
                row = next((group for group in self.groups if group.id == filters["id"]), None)
            elif "slug" in filters:
                row = next((group for group in self.groups if group.slug == filters["slug"]), None)
            else:
                row = None
            return FakeResult([row] if row else [])

        if entity is Room:
            if "id" in filters:
                row = next((room for room in self.rooms if room.id == filters["id"]), None)
            elif "slug" in filters:
                row = next((room for room in self.rooms if room.slug == filters["slug"]), None)
            else:
                row = None
            return FakeResult([row] if row else [])

        if entity is GroupMember:
            row = next((membership for membership in self.memberships if membership.user_session_id == filters.get("user_session_id")), None)
            return FakeResult([row] if row else [])

        if entity is PhotoEmbeddingJob:
            row = next((job for job in self.photo_embedding_jobs if job.photo_id == filters.get("photo_id")), None)
            return FakeResult([row] if row else [])

        return FakeResult([])


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def scalar_one_or_none(self):
        return self.rows[0] if self.rows else None

    def scalars(self):
        return self

    def all(self):
        return self.rows


def _filters(stmt):
    values = {}
    for criterion in getattr(stmt, "_where_criteria", ()):
        left = getattr(criterion, "left", None)
        right = getattr(criterion, "right", None)
        key = getattr(left, "key", None)
        if key:
            values[key] = getattr(right, "value", None)
    return values


def _write_message_file(path: Path, messages):
    payload = {
        "participants": [{"name": "Alice"}, {"name": "Bob"}],
        "messages": messages,
        "title": "Test Chat",
        "thread_path": "inbox/group_123",
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
