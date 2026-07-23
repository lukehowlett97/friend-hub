"""
WebSocket endpoint for real-time chat functionality.
"""
import json
import logging
import time
import uuid
from collections import defaultdict, deque

from fastapi import WebSocket, WebSocketDisconnect

from app.config import get_settings
from app.models.database import async_session_factory
from app.domains.chat.connection_manager import ConnectionManager
from app.domains.chat.message_handler import WebSocketMessageHandler
from app.domains.chat.events import (
    OutgoingConnectionMessage,
    OutgoingOnlineUsers,
    OutgoingUserJoined,
    OutgoingUserDisconnected,
    OutgoingError,
)
from app.domains.auth.service import AuthService
from app.domains.rooms.service import RoomService

logger = logging.getLogger(__name__)
settings = get_settings()

# Per-connection sliding-window rate limiter (typing/ping events bypass this)
_rate_limit_buckets: dict[str, deque] = defaultdict(deque)
_RATE_LIMIT_EXEMPT = {"typing", "stop_typing", "ping"}


def _is_rate_limited(conn_id: str, limit: int | None = None) -> bool:
    now = time.monotonic()
    bucket = _rate_limit_buckets[conn_id]
    window = settings.ws_rate_limit_window_seconds
    while bucket and bucket[0] < now - window:
        bucket.popleft()
    if len(bucket) >= (limit or settings.ws_rate_limit_messages):
        return True
    bucket.append(now)
    return False


def _cleanup_rate_limit(conn_id: str):
    _rate_limit_buckets.pop(conn_id, None)


async def websocket_endpoint(websocket: WebSocket, manager: ConnectionManager):
    # Accept first so we can send an error frame if auth fails.
    await websocket.accept()

    token = websocket.query_params.get("token")
    room_slug = websocket.query_params.get("room") or None
    user = None
    room = None
    async with async_session_factory() as db:
        user, _ = await AuthService(db).authenticate_token(token)
        if user:
            room_service = RoomService(db)
            room, room_error = await room_service.resolve_room(slug=room_slug, user_id=user.id)

    if not user:
        await websocket.send_json(OutgoingError(error="Authentication required").dict())
        await websocket.close(code=4001)
        return

    if not room:
        await websocket.send_json(OutgoingError(error=room_error or "Room required").dict())
        await websocket.close(code=4003)
        return

    conn_id = str(uuid.uuid4())
    is_new_user = manager.connect(websocket, conn_id, user, room=room)
    user_sid = str(user.session_id)
    logger.info("WS connected: conn=%s user=%s new=%s", conn_id, user_sid, is_new_user)

    message_handler = WebSocketMessageHandler(manager)

    try:
        # Confirm the connection — send the user their own session_id so the
        # frontend can use it for isMe comparisons.
        await websocket.send_json(
            OutgoingConnectionMessage(session_id=user_sid, status="connected").dict()
        )

        # Send the current online roster.
        await websocket.send_json(
            OutgoingOnlineUsers(users=manager.get_online_users(room.id)).dict()
        )

        # Announce to others only on first connection (not on new tab).
        if is_new_user:
            await manager.broadcast_to_room_except_user(
                room.id,
                OutgoingUserJoined(session_id=user_sid, nickname=user.nickname).dict(),
                user_sid,
            )
            await manager.broadcast_to_room(room.id, OutgoingOnlineUsers(users=manager.get_online_users(room.id)).dict())

        while True:
            raw = await websocket.receive_text()

            if len(raw.encode()) > settings.ws_max_message_bytes:
                await websocket.send_json(OutgoingError(error="Message too large").dict())
                continue

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json(OutgoingError(error="Invalid JSON").dict())
                continue

            msg_type = data.get("type", "")
            guest_limit = settings.demo_guest_message_rate_limit if getattr(user, "user_type", None) == "guest" else None
            if msg_type not in _RATE_LIMIT_EXEMPT and _is_rate_limited(conn_id, guest_limit):
                await websocket.send_json(OutgoingError(error="Rate limit exceeded, slow down").dict())
                continue

            logger.debug("Received from conn=%s: %s", conn_id, data)

            async with async_session_factory() as db:
                response = await message_handler.handle_message(msg_type, data, conn_id, db)
                if response:
                    await websocket.send_json(response)

    except WebSocketDisconnect:
        await _handle_disconnect(conn_id, manager)

    except Exception as e:
        logger.error("WS error conn=%s: %s", conn_id, e)
        await _handle_disconnect(conn_id, manager)


async def _handle_disconnect(conn_id: str, manager: ConnectionManager):
    room = manager.get_room(conn_id)
    user, is_last = manager.disconnect(conn_id)
    _cleanup_rate_limit(conn_id)

    if user is None:
        return

    user_sid = str(user.session_id)
    logger.info("WS disconnected: conn=%s user=%s last=%s", conn_id, user_sid, is_last)

    if is_last:
        try:
            async with async_session_factory() as db:
                from app.services.chat_service import ChatService
                await ChatService(db).update_user_last_seen(user_sid)
        except Exception as e:
            logger.error("Error updating last_seen: %s", e)

        if room is None:
            return
        await manager.broadcast_to_room(
            room.id,
            OutgoingUserDisconnected(session_id=user_sid, nickname=user.nickname).dict()
        )
        await manager.broadcast_to_room(
            room.id,
            OutgoingOnlineUsers(users=manager.get_online_users(room.id)).dict()
        )
