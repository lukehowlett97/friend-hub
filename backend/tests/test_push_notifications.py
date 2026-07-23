"""Push notification subsystem tests — endpoints, repository contract, SW assets."""
import asyncio
import os
import types
import unittest
import uuid
from datetime import datetime, timedelta
from pathlib import Path

os.environ["DEBUG"] = "false"


class TestMigrationAndModel(unittest.TestCase):
    def test_migration_018_exists_and_creates_table(self):
        repo_root = Path(__file__).resolve().parents[2]
        migration = repo_root / "backend" / "migrations" / "018_add_push_subscriptions.sql"
        self.assertTrue(migration.exists(), "Migration 018 not found")
        body = migration.read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE", body)
        self.assertIn("push_subscriptions", body)
        # Endpoint uniqueness per user keeps the upsert path clean.
        self.assertIn("idx_push_subscriptions_user_endpoint", body)

    def test_push_subscription_model_columns(self):
        from app.models.push_subscription import PushSubscription

        cols = {c.key for c in PushSubscription.__table__.columns}
        for name in (
            "id",
            "user_id",
            "endpoint",
            "p256dh_key",
            "auth_key",
            "user_agent",
            "created_at",
            "last_success_at",
            "last_failure_at",
        ):
            self.assertIn(name, cols)

    def test_user_id_cascade_delete(self):
        from app.models.push_subscription import PushSubscription

        fk = next(iter(PushSubscription.__table__.foreign_keys))
        self.assertEqual(fk.column.table.name, "users")
        self.assertEqual(fk.ondelete.upper(), "CASCADE")


class TestVapidPublicKeyEndpoint(unittest.TestCase):
    def test_returns_503_when_unconfigured(self):
        from fastapi import HTTPException

        from app.api.v1.router import get_vapid_public_key
        from app import config as config_module

        original = config_module.get_settings
        original_cached = getattr(config_module, "_settings", None)

        class FakeSettings:
            vapid_public_key = None

        config_module.get_settings = lambda: FakeSettings()
        # The router imports get_settings at call-time, so monkey-patching the
        # module attribute is enough.
        try:
            from app.api.v1 import router as router_module
            router_module.get_settings = lambda: FakeSettings()
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(get_vapid_public_key())
            self.assertEqual(ctx.exception.status_code, 503)
        finally:
            config_module.get_settings = original
            from app.api.v1 import router as router_module
            router_module.get_settings = original

    def test_returns_public_key_when_configured(self):
        from app.api.v1 import router as router_module
        from app.api.v1.router import get_vapid_public_key

        class FakeSettings:
            vapid_public_key = "BPublicKey123"

        original = router_module.get_settings
        router_module.get_settings = lambda: FakeSettings()
        try:
            payload = asyncio.run(get_vapid_public_key())
            self.assertEqual(payload, {"public_key": "BPublicKey123"})
        finally:
            router_module.get_settings = original


class TestSubscriptionEndpoints(unittest.TestCase):
    def _patch_user(self, router_module):
        class FakeUser:
            id = "user-1"
            session_id = "sid-1"

        original = router_module._current_user_or_401

        async def fake_current_user(authorization, db, session_cookie=None):
            return FakeUser()

        router_module._current_user_or_401 = fake_current_user
        return original

    def test_create_calls_repo_upsert(self):
        from app.api.v1 import router as router_module
        from app.api.v1.router import (
            PushSubscriptionRequest,
            create_push_subscription,
        )
        from app.domains.notifications.push_repository import (
            PushSubscriptionRepository,
        )

        original_user = self._patch_user(router_module)

        captured = {}

        async def fake_upsert(self, **kwargs):
            captured.update(kwargs)
            return object()

        original_upsert = PushSubscriptionRepository.upsert
        PushSubscriptionRepository.upsert = fake_upsert
        try:
            class DummySession:
                pass

            payload = asyncio.run(create_push_subscription(
                request=PushSubscriptionRequest(
                    endpoint="https://push.example/abc",
                    p256dh_key="p256",
                    auth_key="auth",
                    user_agent="Mozilla",
                ),
                authorization="Bearer t",
                db=DummySession(),
            ))
            self.assertEqual(payload, {"status": "registered"})
            self.assertEqual(captured["endpoint"], "https://push.example/abc")
            self.assertEqual(captured["p256dh_key"], "p256")
            self.assertEqual(captured["auth_key"], "auth")
            self.assertEqual(captured["user_agent"], "Mozilla")
            self.assertEqual(captured["user_id"], "user-1")
        finally:
            PushSubscriptionRepository.upsert = original_upsert
            router_module._current_user_or_401 = original_user

    def test_delete_uses_query_string_endpoint(self):
        from app.api.v1 import router as router_module
        from app.api.v1.router import delete_push_subscription
        from app.domains.notifications.push_repository import (
            PushSubscriptionRepository,
        )

        original_user = self._patch_user(router_module)

        async def fake_delete_for_user(self, *, user_id, endpoint):
            self.last_call = (user_id, endpoint)
            return 1

        original_delete = PushSubscriptionRepository.delete_for_user
        PushSubscriptionRepository.delete_for_user = fake_delete_for_user
        try:
            class DummySession:
                pass

            payload = asyncio.run(delete_push_subscription(
                endpoint="https://push.example/abc",
                authorization="Bearer t",
                db=DummySession(),
            ))
            self.assertEqual(payload, {"status": "unregistered"})
        finally:
            PushSubscriptionRepository.delete_for_user = original_delete
            router_module._current_user_or_401 = original_user

    def test_send_test_push_404s_when_no_subscriptions(self):
        from fastapi import HTTPException

        from app.api.v1 import router as router_module
        from app.api.v1.router import send_test_push
        from app.domains.notifications.push_repository import (
            PushSubscriptionRepository,
        )

        original_user = self._patch_user(router_module)

        async def fake_list(self, user_id):
            return []

        original_list = PushSubscriptionRepository.list_for_user
        PushSubscriptionRepository.list_for_user = fake_list
        try:
            class DummySession:
                pass

            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(send_test_push(authorization="Bearer t", db=DummySession()))
            self.assertEqual(ctx.exception.status_code, 404)
        finally:
            PushSubscriptionRepository.list_for_user = original_list
            router_module._current_user_or_401 = original_user

    def test_send_test_push_calls_fanout_when_subscribed(self):
        from app.api.v1 import router as router_module
        from app.api.v1.router import send_test_push
        from app.domains.notifications import push_fanout
        from app.domains.notifications.push_repository import (
            PushSubscriptionRepository,
        )

        original_user = self._patch_user(router_module)

        class FakeSub:
            id = 1
            endpoint = "ep-1"

        async def fake_list(self, user_id):
            return [FakeSub()]

        captured = {}

        async def fake_fanout(db, *, user_id, **kwargs):
            captured["user_id"] = user_id
            captured.update(kwargs)

        original_list = PushSubscriptionRepository.list_for_user
        original_fanout = push_fanout.fanout_push_to_user
        PushSubscriptionRepository.list_for_user = fake_list
        push_fanout.fanout_push_to_user = fake_fanout
        try:
            class DummySession:
                pass

            payload = asyncio.run(send_test_push(authorization="Bearer t", db=DummySession()))
            self.assertEqual(payload["status"], "sent")
            self.assertEqual(payload["subscription_count"], 1)
            self.assertEqual(captured["user_id"], "user-1")
            self.assertIn("test", captured["title"].lower())
        finally:
            PushSubscriptionRepository.list_for_user = original_list
            push_fanout.fanout_push_to_user = original_fanout
            router_module._current_user_or_401 = original_user

    def test_delete_returns_404_when_no_match(self):
        from fastapi import HTTPException

        from app.api.v1 import router as router_module
        from app.api.v1.router import delete_push_subscription
        from app.domains.notifications.push_repository import (
            PushSubscriptionRepository,
        )

        original_user = self._patch_user(router_module)

        async def fake_delete_for_user(self, *, user_id, endpoint):
            return 0

        original_delete = PushSubscriptionRepository.delete_for_user
        PushSubscriptionRepository.delete_for_user = fake_delete_for_user
        try:
            class DummySession:
                pass

            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(delete_push_subscription(
                    endpoint="https://gone.example/x",
                    authorization="Bearer t",
                    db=DummySession(),
                ))
            self.assertEqual(ctx.exception.status_code, 404)
        finally:
            PushSubscriptionRepository.delete_for_user = original_delete
            router_module._current_user_or_401 = original_user


class TestPushDeliveryHeaders(unittest.TestCase):
    """TTL/Urgency/Topic must reach pywebpush — TTL=0 (the pywebpush default)
    silently drops pushes to dozing/offline Android devices."""

    def _send(self, **send_kwargs):
        import sys

        from app.services.push_notification_service import PushNotificationService

        calls = []
        fake_module = types.ModuleType("pywebpush")

        class FakeWebPushException(Exception):
            pass

        def fake_webpush(**kwargs):
            calls.append(kwargs)
            return types.SimpleNamespace(status_code=201)

        fake_module.webpush = fake_webpush
        fake_module.WebPushException = FakeWebPushException

        class FakeSub:
            id = 1
            user_id = "user-1"
            endpoint = "https://fcm.googleapis.com/fcm/send/abc"
            p256dh_key = "p256"
            auth_key = "auth"

        svc = PushNotificationService()
        svc.settings = types.SimpleNamespace(
            vapid_private_key="priv", vapid_public_key="pub", vapid_subject="mailto:t@e.st",
        )

        original = sys.modules.get("pywebpush")
        sys.modules["pywebpush"] = fake_module
        try:
            results = asyncio.run(svc.send_to_subscriptions(
                [FakeSub()], title="t", **send_kwargs,
            ))
        finally:
            if original is not None:
                sys.modules["pywebpush"] = original
            else:
                sys.modules.pop("pywebpush", None)
        return calls, results

    def test_defaults_are_normal_urgency_and_one_day_ttl(self):
        calls, results = self._send()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["ttl"], 86400)
        self.assertEqual(calls[0]["headers"]["Urgency"], "normal")
        self.assertNotIn("Topic", calls[0]["headers"])
        self.assertTrue(results[0].success)
        self.assertEqual(results[0].status_code, 201)

    def test_explicit_urgency_ttl_topic_are_sent(self):
        calls, _ = self._send(urgency="high", ttl=300, topic="fh-chat-main")
        self.assertEqual(calls[0]["ttl"], 300)
        self.assertEqual(calls[0]["headers"]["Urgency"], "high")
        self.assertEqual(calls[0]["headers"]["Topic"], "fh-chat-main")

    def test_topic_is_sanitized_to_base64url_32_chars(self):
        from app.services.push_notification_service import sanitize_topic

        self.assertEqual(sanitize_topic("fh chat/room#1"), "fh-chat-room-1")
        self.assertEqual(len(sanitize_topic("x" * 64)), 32)


class TestPushProfiles(unittest.TestCase):
    def test_profile_resolution(self):
        from app.domains.notifications.push_fanout import resolve_push_profile

        self.assertEqual(resolve_push_profile("chat_messages"), ("high", 432000))
        self.assertEqual(resolve_push_profile("chat_mentions"), ("high", 432000))
        self.assertEqual(resolve_push_profile("hub_bot"), ("high", 432000))
        self.assertEqual(resolve_push_profile("reminders"), ("high", 86400))
        # Unknown and missing types fall back to the general profile.
        self.assertEqual(resolve_push_profile("poll_created"), ("normal", 86400))
        self.assertEqual(resolve_push_profile(None), ("normal", 86400))

    def test_fanout_passes_profile_to_service(self):
        from app.domains.notifications import push_fanout
        from app.services.push_notification_service import PushNotificationService

        class FakeSub:
            id = 1
            endpoint = "ep-1"

        class FakeRepo:
            def __init__(self, db):
                pass

            async def list_for_user(self, user_id):
                return [FakeSub()]

            async def mark_success(self, sid):
                pass

        captured = {}

        async def fake_send(self, subs, **kwargs):
            captured.update(kwargs)
            from app.services.push_notification_service import PushDeliveryResult
            return [PushDeliveryResult(1, success=True, is_gone=False)]

        original_repo = push_fanout.PushSubscriptionRepository
        original_send = PushNotificationService.send_to_subscriptions
        push_fanout.PushSubscriptionRepository = FakeRepo
        PushNotificationService.send_to_subscriptions = fake_send
        try:
            asyncio.run(push_fanout.fanout_push_to_user(
                db=object(), user_id="u-1", title="hi",
                notif_type="chat_messages", topic="fh-chat-main",
            ))
        finally:
            push_fanout.PushSubscriptionRepository = original_repo
            PushNotificationService.send_to_subscriptions = original_send

        self.assertEqual(captured["urgency"], "high")
        self.assertEqual(captured["ttl"], 432000)
        self.assertEqual(captured["topic"], "fh-chat-main")
        self.assertEqual(captured["notif_type"], "chat_messages")


class TestPushNotificationService(unittest.TestCase):
    def test_skips_when_unconfigured(self):
        from app.services.push_notification_service import PushNotificationService

        svc = PushNotificationService()
        # Force unconfigured state.
        svc.settings.vapid_private_key = None
        svc.settings.vapid_public_key = None

        results = asyncio.run(svc.send_to_subscriptions([], title="t", body="b"))
        self.assertEqual(results, [])

    def test_url_for_target_routes_known_types(self):
        from app.api.v1.router import _url_for_target

        self.assertEqual(_url_for_target("event", 42), "/events/42")
        self.assertEqual(_url_for_target("poll", 1), "/polls")
        self.assertEqual(_url_for_target("idea", 1), "/ideas")
        self.assertEqual(_url_for_target("reminder", 1), "/reminders")
        self.assertIsNone(_url_for_target(None, None))
        # Unknown types fall back to /home so the SW always has somewhere to go.
        self.assertEqual(_url_for_target("mystery", 7), "/home")


class TestPushFanoutCleansUpDeadEndpoints(unittest.TestCase):
    def test_dead_subscription_is_deleted(self):
        from app.domains.notifications import push_fanout
        from app.services.push_notification_service import (
            PushDeliveryResult,
            PushNotificationService,
        )

        class FakeSub:
            def __init__(self, sid, endpoint):
                self.id = sid
                self.endpoint = endpoint

        deleted = []
        marked_success = []
        marked_failure = []

        class FakeRepo:
            def __init__(self, db):
                pass

            async def list_for_user(self, user_id):
                return [FakeSub(1, "ep-dead"), FakeSub(2, "ep-ok"), FakeSub(3, "ep-fail")]

            async def delete_by_endpoint(self, endpoint):
                deleted.append(endpoint)
                return 1

            async def mark_success(self, sid):
                marked_success.append(sid)

            async def mark_failure(self, sid):
                marked_failure.append(sid)

        async def fake_send(self, subs, **kwargs):
            return [
                PushDeliveryResult(1, success=False, is_gone=True),
                PushDeliveryResult(2, success=True, is_gone=False),
                PushDeliveryResult(3, success=False, is_gone=False),
            ]

        original_repo_cls = push_fanout.PushSubscriptionRepository
        original_send = PushNotificationService.send_to_subscriptions
        push_fanout.PushSubscriptionRepository = FakeRepo
        PushNotificationService.send_to_subscriptions = fake_send
        try:
            asyncio.run(push_fanout.fanout_push_to_user(
                db=object(), user_id="u-1", title="hi"
            ))
        finally:
            push_fanout.PushSubscriptionRepository = original_repo_cls
            PushNotificationService.send_to_subscriptions = original_send

        self.assertEqual(deleted, ["ep-dead"])
        self.assertEqual(marked_success, [2])
        self.assertEqual(marked_failure, [3])

    def test_fanout_swallows_exceptions(self):
        """A push failure must never break the request that triggered it."""
        from app.domains.notifications import push_fanout

        class ExplodingRepo:
            def __init__(self, db):
                pass

            async def list_for_user(self, user_id):
                raise RuntimeError("DB exploded")

        original = push_fanout.PushSubscriptionRepository
        push_fanout.PushSubscriptionRepository = ExplodingRepo
        try:
            # Should NOT raise.
            asyncio.run(push_fanout.fanout_push_to_user(
                db=object(), user_id="u-1", title="hi"
            ))
        finally:
            push_fanout.PushSubscriptionRepository = original


class TestChatMentionPushNotifications(unittest.TestCase):
    class _ScalarResult:
        def __init__(self, value):
            self.value = value

        def scalar_one_or_none(self):
            return self.value

    class _RowsResult:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

    class _DummySession:
        def __init__(self, rows, group_id=1, room_mode=False):
            self.rows = rows
            self.group_id = group_id
            self.room_mode = room_mode
            self.statements = []
            self.calls = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def execute(self, stmt):
            self.calls += 1
            self.statements.append(str(stmt))
            if self.room_mode:
                return TestChatMentionPushNotifications._RowsResult(self.rows)
            if self.calls == 1:
                return TestChatMentionPushNotifications._ScalarResult(self.group_id)
            return TestChatMentionPushNotifications._RowsResult(self.rows)

    class _SessionFactory:
        def __init__(self, session):
            self.session = session

        def __call__(self):
            return self.session

    @staticmethod
    def _run_helper(
        content,
        *,
        rows,
        sender_id="sender-1",
        fanout=None,
        group_id=1,
        room_id=None,
        visible_user_ids=None,
        mention_only=True,
    ):
        from app.domains.chat import message_handler
        from app.domains.notifications import push_fanout
        from app.models import database as database_module

        session = TestChatMentionPushNotifications._DummySession(
            rows,
            group_id=group_id,
            room_mode=room_id is not None,
        )
        calls = []

        async def fake_fanout(db, *, user_id, **kwargs):
            calls.append({"user_id": user_id, **kwargs})
            if fanout is not None:
                await fanout(db, user_id=user_id, **kwargs)

        original_factory = database_module.async_session_factory
        original_fanout = push_fanout.fanout_push_to_user_if_allowed
        database_module.async_session_factory = TestChatMentionPushNotifications._SessionFactory(session)
        push_fanout.fanout_push_to_user_if_allowed = fake_fanout
        try:
            helper = (
                message_handler._push_mention_notifications
                if mention_only
                else message_handler._push_chat_notifications
            )
            kwargs = {
                "sender_id": sender_id,
                "sender_nickname": "Alice",
                "content": content,
                "message_id": 42,
            }
            if not mention_only:
                kwargs["room_id"] = room_id
                kwargs["visible_user_ids"] = visible_user_ids
            asyncio.run(helper(**kwargs))
        finally:
            database_module.async_session_factory = original_factory
            push_fanout.fanout_push_to_user_if_allowed = original_fanout
        return calls, session

    def test_mentioned_group_member_receives_push(self):
        calls, _session = self._run_helper("hello @bob", rows=[("user-b", "Bob")])

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["user_id"], "user-b")
        self.assertEqual(calls[0]["title"], "Alice mentioned you in Friend Hub")
        self.assertEqual(calls[0]["body"], "hello @bob")
        self.assertEqual(calls[0]["url"], "/chat?message=42")
        self.assertEqual(calls[0]["icon"], "/icons/notification-icon.svg")
        self.assertEqual(calls[0]["badge"], "/icons/notification-badge.svg")
        self.assertEqual(calls[0]["tag"], "fh-chat-main-42")
        self.assertTrue(calls[0]["renotify"])
        self.assertEqual(calls[0]["data"]["notif_type"], "mention")
        self.assertEqual(calls[0]["data"]["target_type"], "message")
        self.assertEqual(calls[0]["data"]["target_id"], 42)
        self.assertEqual(calls[0]["data"]["sender_nickname"], "Alice")
        self.assertEqual(calls[0]["data"]["action_title"], "Open chat")

    def test_sender_does_not_receive_self_mention_push(self):
        calls, _session = self._run_helper(
            "note to @alice",
            rows=[("sender-1", "alice")],
            sender_id="sender-1",
        )

        self.assertEqual(calls, [])

    def test_multiple_mentioned_users_receive_push(self):
        calls, _session = self._run_helper(
            "@bob and @carol please look",
            rows=[("user-b", "bob"), ("user-c", "Carol"), ("user-d", "dan")],
        )

        self.assertEqual([call["user_id"] for call in calls], ["user-b", "user-c"])

    def test_duplicate_mentions_only_push_once_per_user(self):
        calls, _session = self._run_helper(
            "@bob @BOB @bob",
            rows=[("user-b", "Bob"), ("user-b", "Bob")],
        )

        self.assertEqual([call["user_id"] for call in calls], ["user-b"])

    def test_no_push_when_message_has_no_mentions(self):
        calls, session = self._run_helper("hello everyone", rows=[("user-b", "bob")])

        self.assertEqual(calls, [])
        self.assertEqual(session.calls, 0)

    def test_hub_mention_detection_accepts_inline_mentions(self):
        from app.domains.chat.message_handler import _is_hub_mention

        self.assertTrue(_is_hub_mention("@hub help"))
        self.assertTrue(_is_hub_mention("can you help @hub"))
        self.assertTrue(_is_hub_mention("thanks @Hub"))
        self.assertFalse(_is_hub_mention("@hubble no"))
        self.assertFalse(_is_hub_mention("email@hub.test"))

    def test_no_push_when_default_group_missing(self):
        calls, session = self._run_helper("@bob hello", rows=[("user-b", "bob")], group_id=None)

        self.assertEqual(calls, [])
        self.assertEqual(session.calls, 1)

    def test_membership_query_scopes_to_default_group(self):
        calls, session = self._run_helper("@bob hello", rows=[])

        self.assertEqual(calls, [])
        self.assertGreaterEqual(len(session.statements), 2)
        member_query = session.statements[1]
        self.assertIn("group_members", member_query)
        self.assertIn("group_id", member_query)
        self.assertIn("users.is_active", member_query)
        self.assertIn("users.hidden_from_member_list", member_query)
        self.assertIn("users.is_test_user", member_query)
        self.assertIn("users.is_bot", member_query)
        self.assertIn("users.status", member_query)
        self.assertIn("users.user_type", member_query)

    def test_helper_completes_if_fanout_raises(self):
        async def exploding_fanout(db, *, user_id, **kwargs):
            raise RuntimeError("push failed")

        # Should not raise.
        calls, _session = self._run_helper(
            "@bob hello",
            rows=[("user-b", "bob")],
            fanout=exploding_fanout,
        )

        self.assertEqual([call["user_id"] for call in calls], ["user-b"])

    def test_preview_is_single_line_and_truncated(self):
        content = "@bob " + ("hello\n" * 40)
        calls, _session = self._run_helper(content, rows=[("user-b", "bob")])

        self.assertEqual(len(calls), 1)
        self.assertNotIn("\n", calls[0]["body"])
        self.assertLessEqual(len(calls[0]["body"]), 120)
        self.assertTrue(calls[0]["body"].endswith("…"))

    def test_chat_message_pushes_to_room_members(self):
        calls, session = self._run_helper(
            "hello everyone",
            rows=[("user-b", "bob"), ("user-c", "Carol")],
            room_id=uuid.uuid4(),
            mention_only=False,
        )

        self.assertEqual([call["user_id"] for call in calls], ["user-b", "user-c"])
        self.assertEqual(calls[0]["title"], "Alice in Friend Hub")
        self.assertEqual(calls[0]["body"], "hello everyone")
        self.assertEqual(calls[0]["url"], "/chat?message=42")
        self.assertEqual(calls[0]["icon"], "/icons/notification-icon.svg")
        self.assertEqual(calls[0]["badge"], "/icons/notification-badge.svg")
        self.assertEqual(calls[0]["tag"], f"fh-chat-{calls[0]['data']['room_id']}-42")
        self.assertFalse(calls[0]["renotify"])
        self.assertEqual(calls[0]["data"]["notif_type"], "chat_message")
        self.assertEqual(calls[0]["data"]["target_type"], "message")
        self.assertEqual(calls[0]["data"]["target_id"], 42)
        self.assertEqual(calls[0]["data"]["sender_nickname"], "Alice")
        self.assertEqual(calls[0]["data"]["action_title"], "Open chat")
        self.assertEqual(len(session.statements), 1)
        self.assertIn("room_memberships", session.statements[0])
        self.assertIn("room_id", session.statements[0])

    def test_chat_message_skips_sender_and_visible_users(self):
        calls, _session = self._run_helper(
            "hello everyone",
            rows=[("sender-1", "alice"), ("user-b", "bob"), ("user-c", "Carol")],
            visible_user_ids={"user-c"},
            room_id=uuid.uuid4(),
            mention_only=False,
        )

        self.assertEqual([call["user_id"] for call in calls], ["user-b"])

    def test_chat_message_uses_mention_payload_for_mentioned_members(self):
        calls, _session = self._run_helper(
            "hello @bob and everyone",
            rows=[("user-b", "Bob"), ("user-c", "Carol")],
            room_id=uuid.uuid4(),
            mention_only=False,
        )

        self.assertEqual([call["title"] for call in calls], [
            "Alice mentioned you in Friend Hub",
            "Alice in Friend Hub",
        ])
        self.assertEqual([call["data"]["notif_type"] for call in calls], ["mention", "chat_message"])


class TestPollCreatedPushNotifications(unittest.TestCase):
    class _ScalarList:
        def __init__(self, rows):
            self.rows = rows

        def all(self):
            return self.rows

    class _RowsResult:
        def __init__(self, rows):
            self.rows = rows

        def scalars(self):
            return TestPollCreatedPushNotifications._ScalarList(self.rows)

    class _DummySession:
        def __init__(self, rows):
            self.rows = rows
            self.statements = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def execute(self, stmt):
            self.statements.append(str(stmt))
            return TestPollCreatedPushNotifications._RowsResult(self.rows)

    class _SessionFactory:
        def __init__(self, session):
            self.session = session

        def __call__(self):
            return self.session

    @staticmethod
    def _run_helper(rows, *, creator_id="creator-1", fanout=None, question="Where Friday?", hub_item_id="hub-1"):
        from app.api.v1 import router as router_module
        from app.domains.notifications import push_fanout

        session = TestPollCreatedPushNotifications._DummySession(rows)
        calls = []

        async def fake_fanout(db, *, user_id, **kwargs):
            calls.append({"user_id": user_id, **kwargs})
            if fanout is not None:
                await fanout(db, user_id=user_id, **kwargs)

        original_factory = router_module.async_session_factory
        original_fanout = push_fanout.fanout_push_to_user
        router_module.async_session_factory = TestPollCreatedPushNotifications._SessionFactory(session)
        push_fanout.fanout_push_to_user = fake_fanout
        try:
            asyncio.run(router_module._bg_poll_created_push_notification(
                creator_id=creator_id,
                creator_nickname="Alice",
                group_id=7,
                poll_id=42,
                poll_question=question,
                hub_item_id=hub_item_id,
            ))
        finally:
            router_module.async_session_factory = original_factory
            push_fanout.fanout_push_to_user = original_fanout
        return calls, session

    def test_active_group_members_except_creator_receive_poll_push(self):
        calls, _session = self._run_helper(["user-b", "user-c"])

        self.assertEqual([call["user_id"] for call in calls], ["user-b", "user-c"])
        self.assertEqual(calls[0]["title"], "New poll in Friend Hub")
        self.assertEqual(calls[0]["body"], "Alice created a poll: Where Friday?")
        self.assertEqual(calls[0]["url"], "/polls")
        self.assertEqual(calls[0]["data"]["notif_type"], "poll_created")
        self.assertEqual(calls[0]["data"]["target_type"], "poll")
        self.assertEqual(calls[0]["data"]["target_id"], 42)
        self.assertEqual(calls[0]["data"]["hub_item_id"], "hub-1")

    def test_creator_and_duplicate_rows_do_not_receive_duplicate_push(self):
        calls, _session = self._run_helper(
            ["creator-1", "user-b", "user-b"],
            creator_id="creator-1",
        )

        self.assertEqual([call["user_id"] for call in calls], ["user-b"])

    def test_membership_query_filters_group_and_inactive_cleanup_users(self):
        calls, session = self._run_helper([])

        self.assertEqual(calls, [])
        self.assertEqual(len(session.statements), 1)
        member_query = session.statements[0]
        self.assertIn("group_members", member_query)
        self.assertIn("group_id", member_query)
        self.assertIn("users.id !=", member_query)
        self.assertIn("users.is_active", member_query)
        self.assertIn("users.hidden_from_member_list", member_query)
        self.assertIn("users.is_test_user", member_query)
        self.assertIn("users.is_bot", member_query)
        self.assertIn("users.status", member_query)
        self.assertIn("users.user_type", member_query)

    def test_fanout_failure_does_not_escape_helper(self):
        async def exploding_fanout(db, *, user_id, **kwargs):
            raise RuntimeError("push failed")

        calls, _session = self._run_helper(["user-b"], fanout=exploding_fanout)

        self.assertEqual([call["user_id"] for call in calls], ["user-b"])

    def test_poll_preview_is_single_line_and_truncated(self):
        question = "Where\n" + ("Friday " * 40)
        calls, _session = self._run_helper(["user-b"], question=question)

        self.assertEqual(len(calls), 1)
        self.assertNotIn("\n", calls[0]["body"])
        self.assertLessEqual(len(calls[0]["body"]), len("Alice created a poll: ") + 120)
        self.assertTrue(calls[0]["body"].endswith("…"))

    def test_create_poll_schedules_poll_push_and_disables_generic_push(self):
        from app.api.v1 import router as router_module
        from app.api.v1.router import PollCreateRequest, create_poll
        from app.models.planning import Poll

        original_current_user = router_module._current_user_or_401
        original_default_group = router_module._default_group
        original_hub_item = router_module._hub_item_for_source
        original_log = router_module._log_activity
        original_room_id = router_module._request_room_id

        user = types.SimpleNamespace(id=uuid.uuid4(), nickname="Alice")
        group = types.SimpleNamespace(id=7)
        hub_item = types.SimpleNamespace(id=uuid.uuid4())

        async def fake_current_user(authorization, db, session_cookie=None):
            return user

        async def fake_default_group(db):
            return group

        async def fake_hub_item(*args, **kwargs):
            return hub_item

        async def fake_log(*args, **kwargs):
            return None

        async def fake_room_id(db, **kwargs):
            return None

        class DummyDb:
            def __init__(self):
                self.added = []
                self.committed = False
                self.flushes = 0

            def add(self, value):
                self.added.append(value)

            async def flush(self):
                self.flushes += 1
                for value in self.added:
                    if isinstance(value, Poll) and getattr(value, "id", None) is None:
                        value.id = 42

            async def commit(self):
                self.committed = True

        bg = types.SimpleNamespace(tasks=[])
        bg.add_task = lambda fn, *a, **kw: bg.tasks.append((fn, a, kw))

        router_module._current_user_or_401 = fake_current_user
        router_module._default_group = fake_default_group
        router_module._hub_item_for_source = fake_hub_item
        router_module._log_activity = fake_log
        router_module._request_room_id = fake_room_id
        try:
            result = asyncio.run(create_poll(
                request=PollCreateRequest(
                    question="Where Friday?",
                    options=["Pub", "Cinema"],
                    deadline_at=datetime.utcnow() + timedelta(hours=1),
                ),
                background_tasks=bg,
                authorization="Bearer token",
                db=DummyDb(),
                manager=None,
            ))
        finally:
            router_module._current_user_or_401 = original_current_user
            router_module._default_group = original_default_group
            router_module._hub_item_for_source = original_hub_item
            router_module._log_activity = original_log
            router_module._request_room_id = original_room_id

        self.assertEqual(result, {"status": "created", "id": 42})
        self.assertEqual(len(bg.tasks), 2)
        self.assertIs(bg.tasks[0][0], router_module._bg_broadcast_notification)
        self.assertFalse(bg.tasks[0][2]["send_push"])
        self.assertIs(bg.tasks[1][0], router_module._bg_poll_created_push_notification)
        self.assertEqual(bg.tasks[1][1][0], user.id)
        self.assertEqual(bg.tasks[1][1][2], group.id)
        self.assertEqual(bg.tasks[1][1][3], 42)
        self.assertEqual(bg.tasks[1][1][4], "Where Friday?")
        self.assertEqual(bg.tasks[1][1][5], str(hub_item.id))


class TestFrontendArtifacts(unittest.TestCase):
    """Ensure the frontend pieces of the push pipeline ship with the bundle."""

    @staticmethod
    def _root():
        return Path(__file__).resolve().parents[2]

    def test_service_worker_handles_push_and_clicks(self):
        path = self._root() / "frontend" / "src" / "sw.js"
        self.assertTrue(path.exists(), "src/sw.js (injectManifest entry) missing")
        body = path.read_text(encoding="utf-8")
        self.assertIn("addEventListener('push'", body)
        self.assertIn("addEventListener('notificationclick'", body)
        self.assertIn("showNotification", body)
        # Endpoint rotation must re-register with the server.
        self.assertIn("addEventListener('pushsubscriptionchange'", body)
        # Workbox precache is wired in.
        self.assertIn("__WB_MANIFEST", body)

    def test_main_jsx_syncs_push_subscription_on_startup(self):
        body = (self._root() / "frontend" / "src" / "main.jsx").read_text(encoding="utf-8")
        self.assertIn("syncPushSubscription", body)
        resub = (self._root() / "frontend" / "src" / "push" / "resubscribe.js").read_text(encoding="utf-8")
        self.assertIn("/api/v1/push/subscriptions", resub)
        self.assertIn("pushManager.subscribe", resub)

    def test_vite_config_uses_inject_manifest_for_push(self):
        config = (self._root() / "frontend" / "vite.config.js").read_text(encoding="utf-8")
        self.assertIn("injectManifest", config)
        self.assertIn("'sw.js'", config)
        # Dev SW must be enabled — without it `serviceWorker.ready` hangs in dev.
        self.assertIn("devOptions", config)

    def test_main_jsx_registers_service_worker(self):
        body = (self._root() / "frontend" / "src" / "main.jsx").read_text(encoding="utf-8")
        self.assertIn("virtual:pwa-register", body)
        self.assertIn("registerSW", body)

    def test_notification_settings_uses_apifetch_and_backend_vapid_route(self):
        body = (
            self._root()
            / "frontend"
            / "src"
            / "components"
            / "Notifications"
            / "NotificationSettings.jsx"
        ).read_text(encoding="utf-8")
        self.assertIn("/api/v1/push/vapid-public-key", body)
        self.assertIn("/api/v1/push/subscriptions", body)
        self.assertIn("apiFetch", body)
        # The old broken `process.env` reference must be gone.
        self.assertNotIn("process.env.REACT_APP_VAPID_PUBLIC_KEY", body)


class TestPreferenceGatedFanout(unittest.TestCase):
    """`fanout_push_to_user_if_allowed` honours per-user notification prefs."""

    def _run(self, *, allowed, raise_in_check=False):
        from app.domains.notifications import push_fanout
        from app.domains.notifications import preferences_repository as prefs_module

        delivered = []

        async def fake_inner(db, *, user_id, **kwargs):
            delivered.append({"user_id": user_id, **kwargs})

        async def fake_should_send(self, user_id, notif_type):
            if raise_in_check:
                raise RuntimeError("pref lookup boom")
            return allowed

        original_inner = push_fanout.fanout_push_to_user
        original_check = prefs_module.NotificationPreferencesRepository.should_send_push
        push_fanout.fanout_push_to_user = fake_inner
        prefs_module.NotificationPreferencesRepository.should_send_push = fake_should_send
        try:
            asyncio.run(push_fanout.fanout_push_to_user_if_allowed(
                object(),  # db is unused by the fakes
                user_id="user-a",
                notif_type="chat_messages",
                title="hi",
            ))
        finally:
            push_fanout.fanout_push_to_user = original_inner
            prefs_module.NotificationPreferencesRepository.should_send_push = original_check
        return delivered

    def test_delivers_when_preference_allows(self):
        delivered = self._run(allowed=True)
        self.assertEqual([d["user_id"] for d in delivered], ["user-a"])

    def test_suppressed_when_preference_disallows(self):
        delivered = self._run(allowed=False)
        self.assertEqual(delivered, [])

    def test_suppressed_and_safe_when_pref_check_raises(self):
        # A failing preference lookup must not deliver and must not raise.
        delivered = self._run(allowed=True, raise_in_check=True)
        self.assertEqual(delivered, [])
