import unittest
import asyncio
import os
from pathlib import Path

os.environ["DEBUG"] = "false"


class TestReactionModel(unittest.TestCase):
    def test_table_name(self):
        from app.models.reaction import Reaction
        self.assertEqual(Reaction.__tablename__, "reactions")

    def test_required_columns_present(self):
        from app.models.reaction import Reaction
        cols = {c.key for c in Reaction.__table__.columns}
        self.assertIn("id", cols)
        self.assertIn("message_id", cols)
        self.assertIn("user_session_id", cols)
        self.assertIn("emoji", cols)
        self.assertIn("created_at", cols)

    def test_message_id_has_cascade_delete(self):
        from app.models.reaction import Reaction
        fk = next(
            fk for fk in Reaction.__table__.foreign_keys
            if "messages" in fk.target_fullname
        )
        self.assertEqual(fk.ondelete.upper(), "CASCADE")

    def test_user_session_id_has_cascade_delete(self):
        from app.models.reaction import Reaction
        fk = next(
            fk for fk in Reaction.__table__.foreign_keys
            if fk.parent.name == "user_session_id"
        )
        self.assertEqual(fk.ondelete.upper(), "CASCADE")

    def test_user_id_is_nullable_and_set_null(self):
        from app.models.reaction import Reaction
        col = Reaction.__table__.columns["user_id"]
        self.assertTrue(col.nullable)
        fk = next(
            fk for fk in Reaction.__table__.foreign_keys
            if fk.parent.name == "user_id"
        )
        self.assertEqual(fk.column.table.name, "users")
        self.assertEqual(fk.column.name, "id")
        self.assertEqual(fk.ondelete.upper(), "SET NULL")

    def test_exported_from_models_package(self):
        from app.models import Reaction
        self.assertIsNotNone(Reaction)


class TestMessageModelColumns(unittest.TestCase):
    def test_edited_at_column_present(self):
        from app.models.message import Message
        cols = {c.key for c in Message.__table__.columns}
        self.assertIn("edited_at", cols)

    def test_is_deleted_column_present(self):
        from app.models.message import Message
        cols = {c.key for c in Message.__table__.columns}
        self.assertIn("is_deleted", cols)

    def test_is_imported_column_present(self):
        from app.models.message import Message
        cols = {c.key for c in Message.__table__.columns}
        self.assertIn("is_imported", cols)

    def test_reply_to_id_column_present(self):
        from app.models.message import Message
        cols = {c.key for c in Message.__table__.columns}
        self.assertIn("reply_to_id", cols)

    def test_is_deleted_defaults_false(self):
        from app.models.message import Message
        col = Message.__table__.columns["is_deleted"]
        self.assertFalse(col.default.arg)

    def test_reply_to_id_is_nullable(self):
        from app.models.message import Message
        col = Message.__table__.columns["reply_to_id"]
        self.assertTrue(col.nullable)

    def test_reply_to_id_references_messages(self):
        from app.models.message import Message
        fk = next(
            fk for fk in Message.__table__.foreign_keys
            if fk.column.table.name == "messages"
        )
        self.assertEqual(fk.ondelete.upper(), "SET NULL")

    def test_user_id_is_nullable_and_references_stable_user_id(self):
        from app.models.message import Message
        col = Message.__table__.columns["user_id"]
        self.assertTrue(col.nullable)
        fk = next(
            fk for fk in Message.__table__.foreign_keys
            if fk.parent.name == "user_id"
        )
        self.assertEqual(fk.column.table.name, "users")
        self.assertEqual(fk.column.name, "id")
        self.assertEqual(fk.ondelete.upper(), "SET NULL")

    def test_imported_identity_id_is_nullable_and_set_null(self):
        from app.models.message import Message

        col = Message.__table__.columns["imported_identity_id"]
        self.assertTrue(col.nullable)
        fk = next(
            fk for fk in Message.__table__.foreign_keys
            if fk.parent.name == "imported_identity_id"
        )
        self.assertEqual(fk.column.table.name, "imported_identities")
        self.assertEqual(fk.column.name, "id")
        self.assertEqual(fk.ondelete.upper(), "SET NULL")

    def test_to_dict_includes_new_fields(self):
        from app.models.message import Message
        from datetime import datetime
        import uuid

        msg = Message()
        msg.id = 1
        msg.user_session_id = uuid.uuid4()
        msg.content = "hello"
        msg.created_at = datetime(2025, 1, 1, 12, 0, 0)
        msg.edited_at = None
        msg.is_deleted = False
        msg.reply_to_id = None

        d = msg.to_dict()
        self.assertIn("edited_at", d)
        self.assertIn("is_deleted", d)
        self.assertIn("is_imported", d)
        self.assertIn("imported_identity_id", d)
        self.assertIn("reply_to_id", d)
        self.assertIsNone(d["edited_at"])
        self.assertFalse(d["is_deleted"])
        self.assertFalse(d["is_imported"])

    def test_to_dict_serialises_edited_at_as_iso(self):
        from app.models.message import Message
        from datetime import datetime
        import uuid

        msg = Message()
        msg.id = 2
        msg.user_session_id = uuid.uuid4()
        msg.content = "edited"
        msg.created_at = datetime(2025, 1, 1, 12, 0, 0)
        msg.edited_at = datetime(2025, 1, 1, 12, 5, 0)
        msg.is_deleted = False
        msg.reply_to_id = None

        d = msg.to_dict()
        self.assertEqual(d["edited_at"], "2025-01-01T12:05:00")


class TestPersistentUserIdentityModels(unittest.TestCase):
    def test_user_has_stable_identity_columns(self):
        from app.models.message import User

        cols = {c.key for c in User.__table__.columns}
        for name in {
            "id",
            "username",
            "nickname",
            "role",
            "created_at",
            "updated_at",
            "last_seen_at",
            "is_active",
        }:
            self.assertIn(name, cols)

    def test_legacy_session_id_is_still_present(self):
        from app.models.message import User

        self.assertIn("session_id", {c.key for c in User.__table__.columns})
        self.assertTrue(User.__table__.columns["session_id"].primary_key)

    def test_user_session_columns_present(self):
        from app.models.user_session import UserSession

        cols = {c.key for c in UserSession.__table__.columns}
        for name in {
            "id",
            "user_id",
            "token_hash",
            "created_at",
            "expires_at",
            "last_used_at",
            "user_agent",
            "ip_address",
            "revoked_at",
        }:
            self.assertIn(name, cols)

    def test_user_session_references_stable_user_id(self):
        from app.models.user_session import UserSession

        fk = next(iter(UserSession.__table__.foreign_keys))
        self.assertEqual(fk.column.table.name, "users")
        self.assertEqual(fk.column.name, "id")
        self.assertEqual(fk.ondelete.upper(), "CASCADE")

    def test_metadata_contains_phase_user_tables(self):
        from app.models import Base
        import app.models.message  # noqa: F401 - registers users/messages
        import app.models.reaction  # noqa: F401 - registers reactions
        import app.models.user_session  # noqa: F401 - registers user_sessions

        self.assertIn("users", Base.metadata.tables)
        self.assertIn("user_sessions", Base.metadata.tables)
        self.assertIn("messages", Base.metadata.tables)
        self.assertIn("reactions", Base.metadata.tables)

    def test_relationships_are_declared(self):
        from app.models.message import Message, User
        from app.models.reaction import Reaction
        from app.models.user_session import UserSession

        self.assertIn("sessions", User.__mapper__.relationships)
        self.assertIn("messages", User.__mapper__.relationships)
        self.assertIn("reactions", User.__mapper__.relationships)
        self.assertIn("user", UserSession.__mapper__.relationships)
        self.assertIn("user", Message.__mapper__.relationships)
        self.assertIn("user", Reaction.__mapper__.relationships)


class TestMemberPermissions(unittest.TestCase):
    def test_owner_can_assign_any_role(self):
        from app.domains.permissions import can_assign_role

        self.assertTrue(can_assign_role("owner", "admin", "member"))
        self.assertTrue(can_assign_role("owner", "member", "owner"))

    def test_admin_cannot_change_or_assign_owner(self):
        from app.domains.permissions import can_assign_role

        self.assertFalse(can_assign_role("admin", "owner", "member"))
        self.assertFalse(can_assign_role("admin", "member", "owner"))
        self.assertTrue(can_assign_role("admin", "member", "admin"))

    def test_member_cannot_assign_roles(self):
        from app.domains.permissions import can_assign_role

        self.assertFalse(can_assign_role("member", "member", "admin"))

    def test_member_repository_keeps_legacy_owner_role_visible(self):
        from app.domains.members.repository import MemberRepository
        from app.models.member import MemberRole
        from app.models.message import UserRole

        role = MemberRepository._response_role(UserRole.member, MemberRole.owner)

        self.assertEqual(role, MemberRole.owner)


class TestMessageServiceResponse(unittest.TestCase):
    def test_response_includes_edited_at_and_is_deleted(self):
        """MessageService.get_recent_messages must include the new fields."""
        from app.api.v1.router import get_messages
        from app.services.chat_service import ChatService

        async def fake_get_recent_messages(self, limit=50, offset=0, start_at=None, end_at=None, room_id=None):
            return [
                {
                    "id": 1,
                    "session_id": "session-1",
                    "nickname": "Alice",
                    "content": "hi",
                    "created_at": "2025-01-01T00:00:00",
                    "edited_at": None,
                    "is_deleted": False,
                    "is_imported": True,
                    "type": "chat",
                }
            ]

        original = ChatService.get_recent_messages
        ChatService.get_recent_messages = fake_get_recent_messages
        try:
            class DummySession:
                pass

            resp = asyncio.run(
                get_messages(
                    limit=1,
                    offset=0,
                    x_room_slug=None,
                    authorization=None,
                    session_cookie=None,
                    db=DummySession(),
                )
            )
            msg = resp.model_dump()["messages"][0]
            self.assertIn("edited_at", msg)
            self.assertIn("is_deleted", msg)
            self.assertIn("is_imported", msg)
        finally:
            ChatService.get_recent_messages = original


class TestFrontendArtifacts(unittest.TestCase):
    """Smoke-check that expected frontend files exist (mirrors pattern in test_api.py)."""

    @staticmethod
    def _repo_root():
        return Path(__file__).resolve().parents[2]

    def test_color_utils_exists(self):
        p = self._repo_root() / "frontend" / "src" / "utils" / "colorUtils.js"
        self.assertTrue(p.exists(), "colorUtils.js not found")

    def test_color_utils_exports_get_color_for_nickname(self):
        p = self._repo_root() / "frontend" / "src" / "utils" / "colorUtils.js"
        self.assertIn("getColorForNickname", p.read_text(encoding="utf-8"))

    def test_user_avatar_component_exists(self):
        p = self._repo_root() / "frontend" / "src" / "components" / "Chat" / "UserAvatar.jsx"
        self.assertTrue(p.exists(), "UserAvatar.jsx not found")

    def test_helpers_exports_format_time(self):
        p = self._repo_root() / "frontend" / "src" / "utils" / "helpers.js"
        self.assertIn("formatTime", p.read_text(encoding="utf-8"))

    def test_message_component_imports_format_time_from_helpers(self):
        p = self._repo_root() / "frontend" / "src" / "components" / "Chat" / "Message.jsx"
        content = p.read_text(encoding="utf-8")
        self.assertIn("helpers", content)
        self.assertIn("formatTime", content)
