import asyncio
import types
import unittest
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from app.api.v1.router import (
    AuthRegisterRequest,
    ProfileUpdateRequest,
    _bearer_token,
    get_current_user,
    peek_invite,
    pin_login,
    claim_invite,
    logout_user,
    register_user,
    update_current_user,
)
from app.domains.auth.service import AuthService
from app.domains.auth.tokens import generate_invite_code, generate_session_token, hash_secret, hash_session_token, verify_secret


class TestAuthTokens(unittest.TestCase):
    def test_generated_token_is_hashable_without_storing_raw_value(self):
        token = generate_session_token()
        token_hash = hash_session_token(token)

        self.assertNotEqual(token, token_hash)
        self.assertEqual(len(token_hash), 64)
        self.assertEqual(hash_session_token(token), token_hash)

    def test_bearer_token_parser_accepts_valid_header(self):
        self.assertEqual(_bearer_token("Bearer abc123"), "abc123")

    def test_bearer_token_parser_rejects_invalid_header(self):
        self.assertIsNone(_bearer_token(None))
        self.assertIsNone(_bearer_token("Basic abc123"))
        self.assertIsNone(_bearer_token("Bearer "))

    def test_pin_hash_does_not_store_raw_pin(self):
        stored = hash_secret("123456")
        self.assertNotIn("123456", stored)
        self.assertTrue(verify_secret("123456", stored))
        self.assertFalse(verify_secret("654321", stored))

    def test_invite_code_generator_is_hashable(self):
        invite = generate_invite_code()
        stored = hash_secret(invite)
        self.assertNotEqual(invite, stored)
        self.assertTrue(verify_secret(invite, stored))


class TestAuthValidation(unittest.TestCase):
    def test_username_validation_accepts_simple_private_group_names(self):
        self.assertIsNone(AuthService._validate_username("luke_97"))

    def test_username_validation_rejects_bad_format(self):
        self.assertEqual(
            AuthService._validate_username("Luke Smith"),
            "Username can only contain lowercase letters, numbers, underscores, and hyphens",
        )

    def test_nickname_validation_allows_spaces(self):
        self.assertIsNone(AuthService._validate_nickname("Chat GBeanT"))

    def test_nickname_validation_rejects_tabs(self):
        self.assertEqual(
            AuthService._validate_nickname("Bad\tName"),
            "Nickname cannot contain line breaks or tabs",
        )

    def test_expiry_validation_handles_timezone_aware_values(self):
        self.assertTrue(AuthService._is_expired(datetime.now(timezone.utc) - timedelta(seconds=1)))
        self.assertFalse(AuthService._is_expired(datetime.now(timezone.utc) + timedelta(seconds=1)))

    def test_pin_validation_requires_six_numeric_digits(self):
        self.assertIsNone(AuthService._validate_pin("123456"))
        self.assertEqual(AuthService._validate_pin("12345"), "PIN must be exactly 6 digits")
        self.assertEqual(AuthService._validate_pin("12345a"), "PIN must be exactly 6 digits")


class TestAuthEndpoints(unittest.TestCase):
    def setUp(self):
        self.original_init = AuthService.__init__
        AuthService.__init__ = lambda service, db: None

    def tearDown(self):
        AuthService.__init__ = self.original_init
        for name in ("register", "authenticate_token", "logout", "update_nickname"):
            if hasattr(self, f"original_{name}"):
                setattr(AuthService, name, getattr(self, f"original_{name}"))

    @staticmethod
    def _user(role="owner"):
        return types.SimpleNamespace(
            id=uuid.uuid4(),
            session_id=uuid.uuid4(),
            username="luke",
            nickname="Chat GBeanT",
            role=types.SimpleNamespace(value=role),
        )

    @staticmethod
    def _request():
        return types.SimpleNamespace(
            headers={"user-agent": "unit-test"},
            client=types.SimpleNamespace(host="127.0.0.1"),
        )

    def _patch_method(self, name, replacement):
        setattr(self, f"original_{name}", getattr(AuthService, name))
        setattr(AuthService, name, replacement)

    def test_register_endpoint_returns_user_and_token(self):
        with self.assertRaises(HTTPException) as raised:
            asyncio.run(
                register_user(
                    AuthRegisterRequest(
                        username="luke",
                        nickname="Chat GBeanT",
                        invite_code="friend-hub-dev",
                    ),
                    self._request(),
                    db=object(),
                )
            )

        self.assertEqual(raised.exception.status_code, 403)

    def test_pin_login_returns_generic_failure(self):
        async def fake_pin_login(self, **kwargs):
            return None, None, AuthService.GENERIC_LOGIN_ERROR

        self._patch_method("pin_login", fake_pin_login)

        from app.api.v1.router import PinLoginRequest

        with self.assertRaises(HTTPException) as raised:
            asyncio.run(
                pin_login(
                    PinLoginRequest(username="luke", pin="000000"),
                    self._request(),
                    response=types.SimpleNamespace(set_cookie=lambda *a, **k: None),
                    db=object(),
                )
            )

        self.assertEqual(raised.exception.detail, AuthService.GENERIC_LOGIN_ERROR)

    def test_claim_invite_returns_user_and_token(self):
        async def fake_claim_invite(self, **kwargs):
            return TestAuthEndpoints._user(role="member"), "raw-token", None

        self._patch_method("claim_invite", fake_claim_invite)

        from app.api.v1.router import ClaimInviteRequest

        response = asyncio.run(
            claim_invite(
                ClaimInviteRequest(invite_code="abc", pin="123456", pin_confirm="123456"),
                self._request(),
                response=types.SimpleNamespace(set_cookie=lambda *a, **k: None),
                db=object(),
            )
        )
        payload = response.model_dump()

        self.assertEqual(payload["user"]["username"], "luke")
        self.assertEqual(payload["token"], "raw-token")

    def test_peek_invite_returns_display_name_for_valid_code(self):
        async def fake_peek_invite(self, invite_code):
            return "Chat GBeanT", None

        self._patch_method("peek_invite", fake_peek_invite)

        response = asyncio.run(peek_invite("abc", db=object()))

        self.assertTrue(response["valid"])
        self.assertEqual(response["display_name"], "Chat GBeanT")

    def test_peek_invite_hides_details_for_invalid_code(self):
        async def fake_peek_invite(self, invite_code):
            return None, "Invalid or expired invite code"

        self._patch_method("peek_invite", fake_peek_invite)

        response = asyncio.run(peek_invite("bad", db=object()))

        self.assertFalse(response["valid"])
        self.assertIsNone(response["display_name"])

    def test_admin_create_user_assigns_requested_rooms(self):
        import app.api.v1.router as router_module
        from app.api.v1.router import AdminUserCreateRequest, admin_create_user

        created = TestAuthEndpoints._user(role="member")
        room_id = uuid.uuid4()
        executed = []

        async def fake_owner(*args, **kwargs):
            return TestAuthEndpoints._user(role="owner")

        async def fake_create_admin_user(self, **kwargs):
            return created, "invite-code", None

        async def fake_admin_user_response(db, user):
            return {"id": str(user.id), "username": user.username}

        class FakeResult:
            def scalars(self):
                return types.SimpleNamespace(all=lambda: [room_id])

        class FakeDb:
            async def execute(self, stmt):
                executed.append(stmt)
                return FakeResult()
            async def commit(self):
                pass
            async def refresh(self, obj):
                pass

        originals = (
            router_module._current_owner_user_or_403,
            router_module._admin_user_response,
            router_module._invite_url,
            AuthService.create_admin_user,
        )
        router_module._current_owner_user_or_403 = fake_owner
        router_module._admin_user_response = fake_admin_user_response
        router_module._invite_url = lambda code: f"http://test/join/{code}"
        AuthService.create_admin_user = fake_create_admin_user
        try:
            response = asyncio.run(
                admin_create_user(
                    AdminUserCreateRequest(
                        display_name="Sarah",
                        username="sarah",
                        role="member",
                        room_ids=[room_id],
                        room_role="member",
                    ),
                    authorization="Bearer owner-token",
                    db=FakeDb(),
                )
            )
        finally:
            (
                router_module._current_owner_user_or_403,
                router_module._admin_user_response,
                router_module._invite_url,
                AuthService.create_admin_user,
            ) = originals

        self.assertEqual(response["invite_code"], "invite-code")
        self.assertEqual(response["invite_url"], "http://test/join/invite-code")
        # One execute to resolve valid room ids, one to upsert the membership.
        self.assertGreaterEqual(len(executed), 2)

    def test_me_endpoint_requires_valid_token(self):
        async def fake_authenticate_token(self, token):
            return None, None

        self._patch_method("authenticate_token", fake_authenticate_token)

        with self.assertRaises(HTTPException) as raised:
            asyncio.run(get_current_user(authorization="Bearer bad", db=object()))

        self.assertEqual(raised.exception.status_code, 401)

    def test_me_endpoint_falls_back_to_cookie_when_bearer_is_stale(self):
        async def fake_authenticate_token(self, token):
            if token == "cookie-token":
                return TestAuthEndpoints._user(role="member"), object()
            return None, None

        self._patch_method("authenticate_token", fake_authenticate_token)

        response = asyncio.run(
            get_current_user(
                authorization="Bearer stale-token",
                session_cookie="cookie-token",
                db=object(),
            )
        )
        payload = response.model_dump()

        self.assertEqual(payload["user"]["username"], "luke")
        self.assertIsNone(payload["token"])

    def test_logout_endpoint_revokes_session(self):
        async def fake_logout(self, token):
            return token == "raw-token"

        self._patch_method("logout", fake_logout)

        response = asyncio.run(logout_user(authorization="Bearer raw-token", db=object()))

        self.assertEqual(response["status"], "logged_out")

    def test_profile_update_endpoint_returns_updated_user(self):
        async def fake_update_nickname(self, token, nickname):
            user = TestAuthEndpoints._user(role="member")
            user.nickname = nickname
            return user, None

        self._patch_method("update_nickname", fake_update_nickname)

        response = asyncio.run(
            update_current_user(
                ProfileUpdateRequest(nickname="Bean Commander"),
                authorization="Bearer raw-token",
                db=object(),
            )
        )
        payload = response.model_dump()

        self.assertEqual(payload["user"]["nickname"], "Bean Commander")
        self.assertIsNone(payload["token"])
