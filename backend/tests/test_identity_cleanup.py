import asyncio
import os
import types
import unittest
import uuid
from pathlib import Path

from fastapi import HTTPException

os.environ["DEBUG"] = "false"


class FakeScalarResult:
    def __init__(self, values=None):
        self.values = values or []

    def all(self):
        return self.values


class FakeResult:
    def __init__(self, rows=None, scalars=None):
        self.rows = rows or []
        self._scalars = FakeScalarResult(scalars)

    def fetchall(self):
        return self.rows

    def scalars(self):
        return self._scalars

    def scalar_one_or_none(self):
        return self._scalars.values[0] if self._scalars.values else None


class FakeDb:
    def __init__(self, result=None):
        self.result = result or FakeResult()
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return self.result


class TestImportedIdentityModel(unittest.TestCase):
    def test_imported_identity_table_columns_and_indexes(self):
        from app.models.imported_identity import ImportedIdentity

        cols = {c.key for c in ImportedIdentity.__table__.columns}
        for name in {
            "id",
            "source",
            "source_participant_id",
            "source_display_name",
            "normalised_name",
            "linked_user_id",
            "status",
            "message_count",
            "first_seen_at",
            "last_seen_at",
            "confidence_score",
            "notes",
            "created_at",
            "updated_at",
        }:
            self.assertIn(name, cols)

        fk = next(fk for fk in ImportedIdentity.__table__.foreign_keys if fk.parent.name == "linked_user_id")
        self.assertEqual(fk.column.table.name, "users")
        self.assertEqual(fk.column.name, "id")
        self.assertEqual(fk.ondelete.upper(), "SET NULL")

    def test_user_cleanup_columns_present(self):
        from app.models.message import User

        cols = {c.key for c in User.__table__.columns}
        for name in {
            "user_type",
            "status",
            "is_test_user",
            "is_bot",
            "hidden_from_member_list",
            "deactivated_at",
        }:
            self.assertIn(name, cols)

    def test_metadata_contains_imported_identities_table(self):
        from app.models import Base
        import app.models.imported_identity  # noqa: F401

        self.assertIn("imported_identities", Base.metadata.tables)

    def test_migration_creates_imported_identities(self):
        repo_root = Path(__file__).resolve().parents[2]
        migration = repo_root / "backend" / "migrations" / "029_member_cleanup_identity_foundation.sql"
        content = migration.read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE IF NOT EXISTS imported_identities", content)
        self.assertIn("ALTER TABLE users ADD COLUMN IF NOT EXISTS user_type", content)
        self.assertNotIn("DELETE FROM users", content)


class TestGeneratedUserDetection(unittest.TestCase):
    def _user(self, **kwargs):
        defaults = {"username": None, "nickname": "Luke", "display_name": None, "pin_hash": "hash", "invite_code_used_at": object()}
        defaults.update(kwargs)
        return types.SimpleNamespace(**defaults)

    def test_detects_generated_user_pattern(self):
        from app.domains.identity.detection import detect_user_cleanup_candidate

        suggestion = detect_user_cleanup_candidate(self._user(nickname="User-129941b"), 0)
        self.assertTrue(suggestion.likely_test_user)
        self.assertEqual(suggestion.cleanup_suggestion, "review_generated_user")

    def test_detects_test_user_prefix(self):
        from app.domains.identity.detection import detect_user_cleanup_candidate

        suggestion = detect_user_cleanup_candidate(self._user(username="TestUser3"), 0)
        self.assertTrue(suggestion.likely_test_user)
        self.assertEqual(suggestion.cleanup_suggestion, "mark_as_test")

    def test_inactive_placeholder_is_advisory_not_likely_test(self):
        from app.domains.identity.detection import detect_user_cleanup_candidate

        suggestion = detect_user_cleanup_candidate(
            self._user(username="blank", pin_hash=None, invite_code_used_at=None),
            0,
        )
        self.assertFalse(suggestion.likely_test_user)
        self.assertEqual(suggestion.cleanup_suggestion, "review_inactive_placeholder")


class FakeIdentityRepository:
    def __init__(self):
        self.user_id = uuid.uuid4()
        self.identity = types.SimpleNamespace(
            id=uuid.uuid4(),
            status="unlinked",
            linked_user_id=None,
            notes=None,
            confidence_score=None,
            updated_at=None,
        )
        self.user = types.SimpleNamespace(
            id=self.user_id,
            session_id=uuid.uuid4(),
            user_type="human",
            status="active",
            is_test_user=False,
            is_bot=False,
            hidden_from_member_list=False,
            is_active=True,
            deactivated_at=None,
        )
        self.created_values = None
        self.external_identity_user_id = None
        self.external_identity_user_session_id = None

    async def list_imported_identities(self, **filters):
        return [self.identity]

    async def create_imported_identity(self, **values):
        self.created_values = values
        return types.SimpleNamespace(id=uuid.uuid4(), **values)

    async def get_imported_identity(self, identity_id):
        return self.identity if identity_id == self.identity.id else None

    async def get_user(self, user_id):
        return self.user if user_id == self.user_id else None

    async def update_imported_identity(self, identity, **updates):
        for key, value in updates.items():
            setattr(identity, key, value)
        return identity

    async def upsert_external_identity_mapping(self, identity, user):
        self.external_identity_user_id = user.id
        self.external_identity_user_session_id = user.session_id

    async def backfill_imported_message_identity(self, identity):
        self.backfilled_identity_id = identity.id
        return 0

    async def clear_external_identity_mapping(self, identity):
        self.external_identity_user_id = None
        self.external_identity_user_session_id = None

    async def list_users_for_cleanup(self, **filters):
        return [{"user": self.user, "message_count": 0, "suggestion": None}]

    async def update_user_cleanup(self, user, **updates):
        for key, value in updates.items():
            setattr(user, key, value)
        if updates.get("status") == "deactivated":
            user.is_active = False
        return user


class TestIdentityService(unittest.TestCase):
    def _service(self):
        from app.domains.identity.service import IdentityService

        service = IdentityService(db=object())
        service.repository = FakeIdentityRepository()
        return service

    def test_imported_identity_create_normalises_name(self):
        from app.domains.identity.schemas import ImportedIdentityCreate

        service = self._service()
        identity, error = asyncio.run(service.create_imported_identity(
            ImportedIdentityCreate(source_display_name=" Luke  Howlett ")
        ))

        self.assertIsNone(error)
        self.assertEqual(identity.source_display_name, "Luke  Howlett")
        self.assertEqual(identity.normalised_name, "luke howlett")

    def test_imported_identity_update_link_and_unlink(self):
        from app.domains.identity.schemas import ImportedIdentityUpdate

        service = self._service()
        identity_id = service.repository.identity.id
        user_id = service.repository.user_id

        linked, error = asyncio.run(service.link_imported_identity(identity_id, user_id))
        self.assertIsNone(error)
        self.assertEqual(linked.linked_user_id, user_id)
        self.assertEqual(linked.status, "linked")
        self.assertEqual(service.repository.external_identity_user_id, user_id)
        self.assertEqual(service.repository.external_identity_user_session_id, service.repository.user.session_id)
        self.assertEqual(service.repository.backfilled_identity_id, identity_id)

        updated, error = asyncio.run(service.update_imported_identity(
            identity_id,
            ImportedIdentityUpdate(notes="same as app user", confidence_score=0.8),
        ))
        self.assertIsNone(error)
        self.assertEqual(updated.notes, "same as app user")
        self.assertEqual(updated.confidence_score, 0.8)

        unlinked, error = asyncio.run(service.unlink_imported_identity(identity_id))
        self.assertIsNone(error)
        self.assertIsNone(unlinked.linked_user_id)
        self.assertEqual(unlinked.status, "unlinked")
        self.assertIsNone(service.repository.external_identity_user_id)
        self.assertIsNone(service.repository.external_identity_user_session_id)

    def test_imported_identity_link_rejects_placeholder_user(self):
        service = self._service()
        service.repository.user.user_type = "system"
        service.repository.user.status = "deactivated"
        service.repository.user.is_active = False

        linked, error = asyncio.run(service.link_imported_identity(
            service.repository.identity.id,
            service.repository.user_id,
        ))

        self.assertIsNone(linked)
        self.assertEqual(error, "Linked user must be an active human account")
        self.assertIsNone(service.repository.identity.linked_user_id)

    def test_user_cleanup_update_deactivates_without_delete(self):
        from app.domains.identity.schemas import UserCleanupUpdate

        service = self._service()
        user, error = asyncio.run(service.update_user_cleanup(
            service.repository.user_id,
            UserCleanupUpdate(status="deactivated", is_test_user=True, hidden_from_member_list=True),
        ))

        self.assertIsNone(error)
        self.assertFalse(user.is_active)
        self.assertTrue(user.is_test_user)
        self.assertTrue(user.hidden_from_member_list)


class TestImportedIdentityMessagePayloads(unittest.TestCase):
    def _user(self, *, nickname, username, user_id=None, session_id=None):
        return types.SimpleNamespace(
            id=user_id or uuid.uuid4(),
            session_id=session_id or uuid.uuid4(),
            nickname=nickname,
            username=username,
            is_bot=False,
            avatar_url=f"/avatars/{username}.jpg" if username else None,
            avatar_emoji=None,
            display_role=None,
        )

    def _message(self, *, imported_identity_id=None, is_imported=True, user_id=None, session_id=None):
        from datetime import datetime

        return types.SimpleNamespace(
            id=10,
            user_session_id=session_id or uuid.uuid4(),
            user_id=user_id,
            imported_identity_id=imported_identity_id,
            content="Imported hello",
            created_at=datetime(2026, 1, 1, 12, 0, 0),
            edited_at=None,
            is_deleted=False,
            is_imported=is_imported,
            reply_to_id=None,
            hub_item_id=None,
        )

    def test_imported_message_payload_prefers_linked_user(self):
        from app.domains.messages.service import MessageService

        placeholder = self._user(nickname="Alice Messenger", username=None)
        linked = self._user(nickname="Alice", username="alice")
        msg = self._message(
            imported_identity_id=uuid.uuid4(),
            user_id=placeholder.id,
            session_id=placeholder.session_id,
        )
        service = MessageService(db=object())

        payload = service._rows_to_payloads([(msg, placeholder, linked, None, None, None)])[0]

        self.assertEqual(payload["user_id"], str(linked.id))
        self.assertEqual(payload["session_id"], str(linked.session_id))
        self.assertEqual(payload["nickname"], "Alice")
        self.assertEqual(payload["username"], "alice")
        self.assertEqual(payload["imported_identity_id"], str(msg.imported_identity_id))
        self.assertTrue(payload["is_imported"])

    def test_unlinked_imported_message_payload_uses_placeholder_user(self):
        from app.domains.messages.service import MessageService

        placeholder = self._user(nickname="Alice Messenger", username=None)
        msg = self._message(
            imported_identity_id=uuid.uuid4(),
            user_id=placeholder.id,
            session_id=placeholder.session_id,
        )
        service = MessageService(db=object())

        payload = service._rows_to_payloads([(msg, placeholder, None, None, None, None)])[0]

        self.assertEqual(payload["user_id"], str(placeholder.id))
        self.assertEqual(payload["session_id"], str(placeholder.session_id))
        self.assertEqual(payload["nickname"], "Alice Messenger")
        self.assertIsNone(payload["username"])
        self.assertEqual(payload["imported_identity_id"], str(msg.imported_identity_id))


class TestProfileLinkedIdentityHelpers(unittest.TestCase):
    def test_photo_payload_can_report_linked_uploader(self):
        from datetime import datetime
        from app.api.v1.router import _photo_payload

        placeholder_session_id = uuid.uuid4()
        linked_session_id = uuid.uuid4()
        photo = types.SimpleNamespace(
            id=1,
            filename="photo.jpg",
            thumbnail_filename="photo_thumb.jpg",
            original_filename="photo.jpg",
            content_type="image/jpeg",
            size_bytes=123,
            width=640,
            height=480,
            caption=None,
            tags=[],
            event_id=None,
            hub_item_id=None,
            uploaded_by_session_id=placeholder_session_id,
            created_at=datetime(2026, 1, 1, 12, 0, 0),
            deleted_at=None,
        )

        payload = _photo_payload(
            photo,
            nickname="Techlett",
            uploaded_by_session_id=linked_session_id,
            message_id=10,
        )

        self.assertEqual(payload["uploaded_by"], "Techlett")
        self.assertEqual(payload["uploaded_by_session_id"], str(linked_session_id))
        self.assertEqual(payload["message_id"], 10)


class TestAdminIdentityAccess(unittest.TestCase):
    def test_imported_identity_list_requires_owner(self):
        from app.api.v1 import router as router_module

        original = router_module._current_owner_user_or_403

        async def deny_owner(authorization, db, session_cookie=None):
            raise HTTPException(status_code=403, detail="Owner privileges required")

        router_module._current_owner_user_or_403 = deny_owner
        try:
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(router_module.admin_list_imported_identities(db=object()))
            self.assertEqual(raised.exception.status_code, 403)
        finally:
            router_module._current_owner_user_or_403 = original


class TestPublicMemberFiltering(unittest.TestCase):
    def test_member_list_query_excludes_cleanup_users(self):
        from app.domains.members.repository import MemberRepository

        db = FakeDb()
        asyncio.run(MemberRepository(db).get_all_with_stats())
        query_text = str(db.statements[0])

        self.assertIn("hidden_from_member_list", query_text)
        self.assertIn("is_test_user", query_text)
        self.assertIn("is_bot", query_text)
        self.assertIn("status", query_text)
        self.assertIn("user_type", query_text)

    def test_message_queries_do_not_filter_hidden_users(self):
        from app.domains.messages.repository import MessageRepository

        db = FakeDb()
        asyncio.run(MessageRepository(db).get_messages_by_user_with_users("00000000-0000-0000-0000-000000000001"))
        query_text = str(db.statements[0])
        where_clause = query_text.split("WHERE", 1)[1]

        self.assertNotIn("hidden_from_member_list", where_clause)
        self.assertNotIn("is_test_user", where_clause)
