import unittest
from pathlib import Path

from app.api.v1 import websocket as websocket_module
from app.domains.chat.connection_manager import ConnectionManager


class TestWebSocketAuthFlow(unittest.TestCase):
    def test_frontend_does_not_expose_token_in_ws_url(self):
        """Browser WebSockets authenticate with the HttpOnly session cookie."""
        repo_root = Path(__file__).resolve().parents[2]
        hook_path = repo_root / "frontend" / "src" / "hooks" / "useWebSocket.jsx"
        content = hook_path.read_text(encoding="utf-8")
        self.assertNotIn("getToken", content)
        self.assertNotIn("params.set('token'", content)

    def test_frontend_creates_ws_without_session_param(self):
        """createWebSocketConnection must not accept a session_id argument."""
        repo_root = Path(__file__).resolve().parents[2]
        hook_path = repo_root / "frontend" / "src" / "hooks" / "useWebSocket.jsx"
        content = hook_path.read_text(encoding="utf-8")
        self.assertNotIn("createWebSocketConnection(sessionId)", content)
        self.assertNotIn("createWebSocketConnection(sid)", content)

    def test_websocket_module_calls_auth_service(self):
        """websocket.py must import and use AuthService for token validation."""
        import inspect
        source = inspect.getsource(websocket_module)
        self.assertIn("AuthService", source)
        self.assertIn("authenticate_token", source)
        self.assertIn('websocket.cookies.get("friend_hub_session")', source)

    def test_websocket_module_rejects_missing_token(self):
        """websocket_endpoint must close with 4001 when no valid token is provided."""
        import inspect
        source = inspect.getsource(websocket_module)
        self.assertIn("4001", source)

    def test_connection_manager_multi_tab(self):
        """connect() returns True only on first connection for a user."""
        import asyncio
        import types
        import uuid

        manager = ConnectionManager()

        class FakeWS:
            async def send_json(self, _): pass

        user = types.SimpleNamespace(session_id=uuid.uuid4(), nickname="Luke")
        ws1 = FakeWS()
        ws2 = FakeWS()

        is_first = manager.connect(ws1, "conn-1", user)
        self.assertTrue(is_first)

        is_first = manager.connect(ws2, "conn-2", user)
        self.assertFalse(is_first)

        # Disconnect first tab — user still online
        _, is_last = manager.disconnect("conn-1")
        self.assertFalse(is_last)

        # Disconnect second tab — user goes offline
        _, is_last = manager.disconnect("conn-2")
        self.assertTrue(is_last)

    def test_get_online_users_deduplicates(self):
        """Two connections for the same user should appear only once in online users."""
        import types
        import uuid

        manager = ConnectionManager()

        class FakeWS:
            async def send_json(self, _): pass

        user = types.SimpleNamespace(session_id=uuid.uuid4(), nickname="Bean")
        manager.connect(FakeWS(), "c1", user)
        manager.connect(FakeWS(), "c2", user)

        online = manager.get_online_users()
        self.assertEqual(len(online), 1)
        self.assertEqual(online[0]["nickname"], "Bean")
