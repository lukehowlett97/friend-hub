"""Phase 1 (Chat Council) — member profile metadata tests."""
import asyncio
import os
import unittest
from pathlib import Path

os.environ["DEBUG"] = "false"


class TestUserModelProfileColumns(unittest.TestCase):
    def test_profile_columns_present(self):
        from app.models.message import User

        cols = {c.key for c in User.__table__.columns}
        self.assertIn("display_role", cols)
        self.assertIn("bio", cols)
        self.assertIn("avatar_emoji", cols)

    def test_profile_columns_default_to_null(self):
        from app.models.message import User

        for name in ("display_role", "bio", "avatar_emoji"):
            col = User.__table__.columns[name]
            self.assertTrue(col.nullable, f"{name} must be nullable")
            self.assertIsNone(col.default, f"{name} should have no default")


class TestMigrationFile(unittest.TestCase):
    def test_migration_019_exists(self):
        repo_root = Path(__file__).resolve().parents[2]
        migration = repo_root / "backend" / "migrations" / "019_add_member_profiles.sql"
        self.assertTrue(migration.exists(), "Migration 019 not found")
        body = migration.read_text(encoding="utf-8")
        self.assertIn("display_role", body)
        self.assertIn("bio", body)
        self.assertIn("avatar_emoji", body)


class TestNicknamePolicyEnum(unittest.TestCase):
    def test_policy_values(self):
        from app.domains.members.profile import NicknameChangePolicy

        self.assertEqual(
            {p.value for p in NicknameChangePolicy},
            {"admin_only", "self_edit", "vote_required", "free_for_all"},
        )

    def test_default_policy_is_self_edit(self):
        from app.domains.members.profile import (
            DEFAULT_NICKNAME_POLICY,
            NicknameChangePolicy,
        )

        self.assertEqual(DEFAULT_NICKNAME_POLICY, NicknameChangePolicy.self_edit)


class TestCanEditProfile(unittest.TestCase):
    def setUp(self):
        from app.domains.members.profile import (
            NicknameChangePolicy,
            can_edit_profile,
        )
        from app.models.member import MemberRole

        self.policies = NicknameChangePolicy
        self.can = can_edit_profile
        self.MemberRole = MemberRole

    def test_admin_overrides_any_policy(self):
        for policy in self.policies:
            allowed = self.can(
                requester_session_id="A",
                requester_role=self.MemberRole.admin,
                target_session_id="B",
                policy=policy,
                field="nickname",
            )
            self.assertTrue(allowed, f"admin should always pass under {policy}")

    def test_self_edit_policy(self):
        self.assertTrue(self.can(
            requester_session_id="A",
            requester_role=self.MemberRole.member,
            target_session_id="A",
            policy=self.policies.self_edit,
        ))
        self.assertFalse(self.can(
            requester_session_id="A",
            requester_role=self.MemberRole.member,
            target_session_id="B",
            policy=self.policies.self_edit,
        ))

    def test_admin_only_policy_blocks_self(self):
        self.assertFalse(self.can(
            requester_session_id="A",
            requester_role=self.MemberRole.member,
            target_session_id="A",
            policy=self.policies.admin_only,
        ))

    def test_vote_required_blocks_for_now(self):
        # Phase 2 will plug voting in; until then nobody but admins passes.
        self.assertFalse(self.can(
            requester_session_id="A",
            requester_role=self.MemberRole.member,
            target_session_id="A",
            policy=self.policies.vote_required,
        ))

    def test_free_for_all_policy(self):
        self.assertTrue(self.can(
            requester_session_id="A",
            requester_role=self.MemberRole.member,
            target_session_id="B",
            policy=self.policies.free_for_all,
        ))

    def test_non_nickname_fields_default_to_self_edit(self):
        for field in ("display_role", "bio", "avatar_emoji"):
            self.assertTrue(self.can(
                requester_session_id="A",
                requester_role=self.MemberRole.member,
                target_session_id="A",
                policy=self.policies.admin_only,  # ignored for non-nickname fields
                field=field,
            ))
            self.assertFalse(self.can(
                requester_session_id="A",
                requester_role=self.MemberRole.member,
                target_session_id="B",
                policy=self.policies.admin_only,
                field=field,
            ))


class TestProfileNormalization(unittest.TestCase):
    def test_validate_nickname_strips_and_checks_length(self):
        from app.domains.members.profile import ProfileError, validate_nickname

        self.assertEqual(validate_nickname("  Luke  "), "Luke")
        with self.assertRaises(ProfileError):
            validate_nickname("a")  # too short
        with self.assertRaises(ProfileError):
            validate_nickname("")
        with self.assertRaises(ProfileError):
            validate_nickname("x" * 100)

    def test_normalize_update_only_includes_supplied_fields(self):
        from app.domains.members.profile import ProfileUpdate, normalize_update

        values = normalize_update(ProfileUpdate(display_role="Jester"))
        self.assertEqual(values, {"display_role": "Jester"})

    def test_normalize_update_blank_strings_become_null(self):
        from app.domains.members.profile import ProfileUpdate, normalize_update

        values = normalize_update(ProfileUpdate(bio="   "))
        self.assertEqual(values, {"bio": None})

    def test_normalize_rejects_oversized_field(self):
        from app.domains.members.profile import ProfileError, ProfileUpdate, normalize_update

        with self.assertRaises(ProfileError):
            normalize_update(ProfileUpdate(bio="x" * 1000))


class TestSerializeProfile(unittest.TestCase):
    def test_serialize_profile_emits_phase1_fields(self):
        from datetime import datetime
        from app.domains.members.profile import serialize_profile
        from app.models.message import User, UserRole

        u = User()
        u.id = "00000000-0000-0000-0000-000000000001"
        u.session_id = "11111111-1111-1111-1111-111111111111"
        u.username = "luke"
        u.nickname = "Luke"
        u.role = UserRole.member
        u.display_role = "Bean Chancellor"
        u.bio = "Starts most of the chaos."
        u.avatar_url = None
        u.avatar_emoji = "🫘"
        u.created_at = datetime(2026, 1, 1, 12, 0, 0)
        u.updated_at = datetime(2026, 5, 1, 12, 0, 0)

        payload = serialize_profile(u)
        for key in (
            "id",
            "session_id",
            "username",
            "nickname",
            "role",
            "display_role",
            "bio",
            "avatar_url",
            "avatar_emoji",
            "created_at",
            "updated_at",
        ):
            self.assertIn(key, payload)
        self.assertEqual(payload["display_role"], "Bean Chancellor")
        self.assertEqual(payload["avatar_emoji"], "🫘")
        self.assertEqual(payload["role"], "member")


class TestProfileEndpoints(unittest.TestCase):
    """Endpoint handlers wired with monkey-patched services — no DB required."""

    def test_get_profile_returns_serialized_profile(self):
        from app.api.v1.router import get_member_profile
        from app.domains.members.service import MemberService

        async def fake_get_profile(self, session_id: str):
            return {
                "id": "abc",
                "session_id": session_id,
                "username": "luke",
                "nickname": "Luke",
                "role": "member",
                "display_role": "Bean Chancellor",
                "bio": "Hi",
                "avatar_url": None,
                "avatar_emoji": "🫘",
                "created_at": None,
                "updated_at": None,
            }

        original = MemberService.get_profile
        MemberService.get_profile = fake_get_profile
        try:
            class DummySession:
                pass

            payload = asyncio.run(
                get_member_profile(session_id="sid-1", db=DummySession(), manager=None)
            )
            self.assertEqual(payload["profile"]["display_role"], "Bean Chancellor")
            self.assertEqual(payload["profile"]["avatar_emoji"], "🫘")
        finally:
            MemberService.get_profile = original

    def test_update_profile_rejects_when_service_raises(self):
        from fastapi import HTTPException

        from app.api.v1.router import (
            ProfileMetadataUpdateRequest,
            update_member_profile,
        )
        from app.domains.members.profile import ProfileError
        from app.domains.members.service import MemberService

        class FakeUser:
            session_id = "sid-1"

        # Stub auth so the endpoint thinks a user is signed in.
        from app.api.v1 import router as router_module

        original_current_user = router_module._current_user_or_401

        async def fake_current_user(authorization, db):
            return FakeUser()

        router_module._current_user_or_401 = fake_current_user

        async def fake_update_profile(self, **kwargs):
            raise ProfileError("Not permitted to change nickname", status_code=403)

        original = MemberService.update_profile
        MemberService.update_profile = fake_update_profile
        try:
            class DummySession:
                pass

            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(update_member_profile(
                    session_id="sid-2",
                    request=ProfileMetadataUpdateRequest(nickname="X"),
                    authorization="Bearer token",
                    db=DummySession(),
                ))
            self.assertEqual(ctx.exception.status_code, 403)
        finally:
            MemberService.update_profile = original
            router_module._current_user_or_401 = original_current_user

    def test_update_profile_returns_serialized_profile(self):
        from app.api.v1.router import (
            ProfileMetadataUpdateRequest,
            update_member_profile,
        )
        from app.domains.members.service import MemberService
        from app.api.v1 import router as router_module

        class FakeUser:
            session_id = "sid-1"

        original_current_user = router_module._current_user_or_401

        async def fake_current_user(authorization, db):
            return FakeUser()

        router_module._current_user_or_401 = fake_current_user

        async def fake_update_profile(self, **kwargs):
            return {
                "session_id": kwargs["target_session_id"],
                "nickname": "Updated",
                "display_role": "Jester",
                "bio": None,
                "avatar_emoji": None,
                "avatar_url": None,
                "username": "luke",
                "id": "abc",
                "role": "member",
                "created_at": None,
                "updated_at": None,
            }

        original = MemberService.update_profile
        MemberService.update_profile = fake_update_profile
        try:
            class DummySession:
                pass

            payload = asyncio.run(update_member_profile(
                session_id="sid-1",
                request=ProfileMetadataUpdateRequest(
                    nickname="Updated", display_role="Jester"
                ),
                authorization="Bearer token",
                db=DummySession(),
            ))
            self.assertEqual(payload["profile"]["nickname"], "Updated")
            self.assertEqual(payload["profile"]["display_role"], "Jester")
        finally:
            MemberService.update_profile = original
            router_module._current_user_or_401 = original_current_user


class TestMessagesIncludeProfileFields(unittest.TestCase):
    def test_messages_endpoint_passes_through_display_role_and_avatar_emoji(self):
        """Chat messages must surface the new profile fields, with fallback when absent."""
        from app.api.v1.router import get_messages
        from app.services.chat_service import ChatService

        async def fake_get_recent_messages(self, limit=50, offset=0, start_at=None, end_at=None, room_id=None):
            return [
                {
                    "id": 1,
                    "session_id": "sid-1",
                    "user_id": "uid-1",
                    "nickname": "Luke",
                    "username": "luke",
                    "is_bot": False,
                    "avatar_url": None,
                    "avatar_emoji": "🫘",
                    "display_role": "Bean Chancellor",
                    "content": "hi",
                    "created_at": "2026-05-01T00:00:00",
                    "edited_at": None,
                    "is_deleted": False,
                    "is_imported": False,
                    "type": "chat",
                },
                # Member without profile metadata — must still render via fallback.
                {
                    "id": 2,
                    "session_id": "sid-2",
                    "user_id": "uid-2",
                    "nickname": "Mike",
                    "username": "mike",
                    "is_bot": False,
                    "avatar_url": None,
                    "avatar_emoji": None,
                    "display_role": None,
                    "content": "yo",
                    "created_at": "2026-05-01T00:01:00",
                    "edited_at": None,
                    "is_deleted": False,
                    "is_imported": False,
                    "type": "chat",
                },
            ]

        original = ChatService.get_recent_messages
        ChatService.get_recent_messages = fake_get_recent_messages
        try:
            class DummySession:
                pass

            resp = asyncio.run(
                get_messages(
                    limit=2,
                    offset=0,
                    x_room_slug=None,
                    authorization=None,
                    session_cookie=None,
                    db=DummySession(),
                )
            )
            messages = resp.model_dump()["messages"]
            self.assertEqual(messages[0]["display_role"], "Bean Chancellor")
            self.assertEqual(messages[0]["avatar_emoji"], "🫘")
            # Fallback path — absent fields stay None and don't break rendering.
            self.assertIsNone(messages[1]["display_role"])
            self.assertIsNone(messages[1]["avatar_emoji"])
            self.assertEqual(messages[1]["nickname"], "Mike")
        finally:
            ChatService.get_recent_messages = original


class TestFrontendArtifacts(unittest.TestCase):
    """Smoke checks that mirror the existing pattern in test_models.py."""

    @staticmethod
    def _repo_root():
        return Path(__file__).resolve().parents[2]

    def test_person_popup_renders_display_role_and_bio(self):
        path = self._repo_root() / "frontend" / "src" / "components" / "Chat" / "PersonPopup.jsx"
        content = path.read_text(encoding="utf-8")
        self.assertIn("display_role", content)
        self.assertIn("bio", content)
        self.assertIn("avatar_emoji", content)

    def test_message_component_renders_role_badge(self):
        path = self._repo_root() / "frontend" / "src" / "components" / "Chat" / "Message.jsx"
        content = path.read_text(encoding="utf-8")
        self.assertIn("role-badge", content)
        self.assertIn("display_role", content)

    def test_api_service_exposes_profile_endpoints(self):
        path = self._repo_root() / "frontend" / "src" / "services" / "api.js"
        content = path.read_text(encoding="utf-8")
        self.assertIn("fetchMemberProfile", content)
        self.assertIn("updateMemberProfile", content)
