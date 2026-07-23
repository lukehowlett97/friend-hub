"""
WebSocket connection management for chat functionality.
"""
import asyncio
import logging
from typing import Dict, List, Optional, Set, Tuple

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """
    Manages WebSocket connections keyed by per-connection UUID (conn_id).

    Multiple connections can belong to the same authenticated user (multi-tab).
    Online-user lists are deduplicated by user.session_id so a user with two
    tabs appears once.
    """

    def __init__(self):
        # conn_id → WebSocket
        self.active_connections: Dict[str, WebSocket] = {}
        # conn_id → User ORM object
        self.connection_users: Dict[str, object] = {}
        # str(user.session_id) → {conn_ids}
        self.user_connections: Dict[str, Set[str]] = {}
        # conn_id → bool. True when the tab is currently in the foreground.
        # Defaults to True; clients send 'visibility' updates to flip it.
        self.connection_visibility: Dict[str, bool] = {}
        # conn_id → Room ORM object (resolved at connect time)
        self.connection_rooms: Dict[str, object] = {}

    # ── Connection lifecycle ────────────────────────────────────────────────

    def connect(self, websocket: WebSocket, conn_id: str, user, room=None) -> bool:
        """
        Register an already-accepted WebSocket under conn_id.
        Returns True if this is the user's first active connection (i.e. they
        just came online), False if they already have another tab open.
        """
        self.active_connections[conn_id] = websocket
        self.connection_users[conn_id] = user
        self.connection_visibility[conn_id] = True  # assume foreground until told otherwise
        if room is not None:
            self.connection_rooms[conn_id] = room

        user_sid = str(user.session_id)
        is_first = user_sid not in self.user_connections
        if is_first:
            self.user_connections[user_sid] = set()
        self.user_connections[user_sid].add(conn_id)
        return is_first

    def disconnect(self, conn_id: str) -> Tuple[Optional[object], bool]:
        """
        Remove a connection.
        Returns (user, is_last_connection). Both are None/False if the conn_id
        was not registered.
        """
        user = self.connection_users.pop(conn_id, None)
        self.active_connections.pop(conn_id, None)
        self.connection_visibility.pop(conn_id, None)
        self.connection_rooms.pop(conn_id, None)

        if user is None:
            return None, False

        user_sid = str(user.session_id)
        conns = self.user_connections.get(user_sid, set())
        conns.discard(conn_id)
        if not conns:
            self.user_connections.pop(user_sid, None)
            return user, True
        return user, False

    # ── Lookup ──────────────────────────────────────────────────────────────

    def get_user(self, conn_id: str) -> Optional[object]:
        return self.connection_users.get(conn_id)

    def get_room(self, conn_id: str) -> Optional[object]:
        return self.connection_rooms.get(conn_id)

    def has_room_connections_by_slug(self, slug: str) -> bool:
        return any(
            getattr(room, "slug", None) == slug
            for room in self.connection_rooms.values()
        )

    async def broadcast_to_room_except_user(self, room_id, message: dict, user_session_id: str):
        excluded = self.user_connections.get(user_session_id, set())
        tasks = [
            self._safe_send(cid, ws, message)
            for cid, ws in list(self.active_connections.items())
            if cid not in excluded
            and str(getattr(self.connection_rooms.get(cid), "id", "")) == str(room_id)
        ]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def get_nickname(self, conn_id: str) -> Optional[str]:
        user = self.connection_users.get(conn_id)
        return user.nickname if user else None

    def get_online_users(self, room_id=None) -> List[dict]:
        """Return one entry per unique authenticated user, optionally by room."""
        seen: Dict[str, dict] = {}
        for conn_id, user in self.connection_users.items():
            room = self.connection_rooms.get(conn_id)
            if room_id is not None and (room is None or str(room.id) != str(room_id)):
                continue
            sid = str(user.session_id)
            if sid not in seen:
                seen[sid] = {"session_id": sid, "nickname": user.nickname}
        return list(seen.values())

    def get_online_user_ids(self) -> Set[str]:
        """str(user.id) for every user with at least one active connection."""
        return {str(u.id) for u in self.connection_users.values() if getattr(u, "id", None)}

    def set_visibility(self, conn_id: str, visible: bool) -> None:
        """Update foreground-state for a single connection."""
        if conn_id in self.active_connections:
            self.connection_visibility[conn_id] = bool(visible)

    def get_visible_user_ids(self) -> Set[str]:
        """str(user.id) for users whose chat tab is currently in the foreground.

        These users see live messages without help — push is a duplicate. Any
        user with all of their tabs hidden/blurred falls *out* of this set so
        the push fanout reaches them on whichever device is asleep.
        """
        visible: Set[str] = set()
        for conn_id, user in self.connection_users.items():
            if not getattr(user, "id", None):
                continue
            if self.connection_visibility.get(conn_id, True):
                visible.add(str(user.id))
        return visible

    # ── Messaging ───────────────────────────────────────────────────────────

    async def send_to_conn(self, conn_id: str, message: dict):
        """Send to one specific connection."""
        ws = self.active_connections.get(conn_id)
        if ws:
            await self._safe_send(conn_id, ws, message)

    async def send_to_user(self, user_session_id: str, message: dict):
        """Send to all connections belonging to this user (all their tabs)."""
        for conn_id in list(self.user_connections.get(user_session_id, [])):
            ws = self.active_connections.get(conn_id)
            if ws:
                await self._safe_send(conn_id, ws, message)

    async def broadcast(self, message: dict, exclude_conn_id: str = None):
        """Send to all connections, optionally skipping one."""
        tasks = [
            self._safe_send(cid, ws, message)
            for cid, ws in list(self.active_connections.items())
            if cid != exclude_conn_id
        ]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def broadcast_to_room(self, room_id, message: dict, exclude_conn_id: str = None):
        """Send to all connections in one room, optionally skipping one."""
        room_id_str = str(room_id)
        tasks = []
        for cid, ws in list(self.active_connections.items()):
            if cid == exclude_conn_id:
                continue
            room = self.connection_rooms.get(cid)
            if room is None or str(getattr(room, "id", room)) != room_id_str:
                continue
            tasks.append(self._safe_send(cid, ws, message))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def send_to_user_by_id(self, user_id_str: str, message: dict):
        """Push to all connections whose user.id matches user_id_str."""
        for conn_id, user in list(self.connection_users.items()):
            if str(user.id) == user_id_str:
                ws = self.active_connections.get(conn_id)
                if ws:
                    await self._safe_send(conn_id, ws, message)

    async def broadcast_except_user(self, message: dict, user_session_id: str):
        """Send to all connections except every tab owned by this user."""
        excluded = self.user_connections.get(user_session_id, set())
        tasks = [
            self._safe_send(cid, ws, message)
            for cid, ws in list(self.active_connections.items())
            if cid not in excluded
        ]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _safe_send(self, conn_id: str, ws: WebSocket, message: dict):
        try:
            await ws.send_json(message)
        except Exception as e:
            logger.warning("Failed to send to conn %s: %s", conn_id, e)
            self.disconnect(conn_id)

    # ── Utilities ───────────────────────────────────────────────────────────

    def get_connection_count(self) -> int:
        return len(self.active_connections)

    def is_connected(self, conn_id: str) -> bool:
        return conn_id in self.active_connections

    def get_all_conn_ids(self) -> list:
        return list(self.active_connections.keys())

    def disconnect_all(self):
        for conn_id in list(self.active_connections.keys()):
            self.disconnect(conn_id)
