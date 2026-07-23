"""
WebSocket event types and schemas for the chat system.
"""
from enum import Enum
from typing import Optional, Any, Dict, List
from pydantic import BaseModel
from datetime import datetime


class WebSocketEventType(str, Enum):
    # Connection
    CONNECTION = "connection"

    # Chat messages
    MESSAGE = "message"

    # Reactions
    TOGGLE_REACTION = "toggle_reaction"
    REACTION_UPDATED = "reaction_updated"

    # User lifecycle
    SET_NICKNAME = "set_nickname"
    NICKNAME_SUCCESS = "nickname_success"
    NICKNAME_ERROR = "nickname_error"
    USER_JOINED = "user_joined"
    USER_LEFT = "user_left"
    USER_DISCONNECTED = "user_disconnected"

    # Presence
    ONLINE_USERS = "online_users"
    TYPING = "typing"
    STOP_TYPING = "stop_typing"
    TYPING_INDICATOR = "typing_indicator"

    # Message mutations
    DELETE_MESSAGE  = "delete_message"   # incoming
    MESSAGE_DELETED = "message_deleted"  # outgoing
    EDIT_MESSAGE    = "edit_message"     # incoming
    MESSAGE_EDITED  = "message_edited"   # outgoing

    # Notifications
    NOTIFICATION = "notification"

    # Tab visibility (drives push-vs-live decision on the backend)
    VISIBILITY = "visibility"

    # System
    PING = "ping"
    PONG = "pong"
    ERROR = "error"


class BaseWebSocketMessage(BaseModel):
    type: WebSocketEventType
    timestamp: Optional[datetime] = None


# ── Incoming ────────────────────────────────────────────────────────────────

class IncomingChatMessage(BaseModel):
    type: str
    content: str

class IncomingSetNickname(BaseModel):
    type: str
    nickname: str

class IncomingPing(BaseModel):
    type: str


# ── Outgoing ────────────────────────────────────────────────────────────────

class OutgoingConnectionMessage(BaseWebSocketMessage):
    type: WebSocketEventType = WebSocketEventType.CONNECTION
    session_id: str
    status: str


class OutgoingChatMessage(BaseWebSocketMessage):
    type: WebSocketEventType = WebSocketEventType.MESSAGE
    session_id: str
    nickname: str
    username: Optional[str] = None
    avatar_url: Optional[str] = None
    avatar_emoji: Optional[str] = None
    display_role: Optional[str] = None
    role: Optional[str] = None
    is_bot: bool = False
    content: str
    message_id: int
    reply_to: Optional[Dict[str, Any]] = None  # {id, content, nickname}

    def dict(self, **kwargs):
        data = super().dict(**kwargs)
        if data.get("timestamp"):
            data["timestamp"] = data["timestamp"].isoformat()
        return data


class OutgoingNicknameSuccess(BaseWebSocketMessage):
    type: WebSocketEventType = WebSocketEventType.NICKNAME_SUCCESS
    nickname: str


class OutgoingNicknameError(BaseWebSocketMessage):
    type: WebSocketEventType = WebSocketEventType.NICKNAME_ERROR
    error: str


class OutgoingUserJoined(BaseWebSocketMessage):
    type: WebSocketEventType = WebSocketEventType.USER_JOINED
    session_id: str
    nickname: str


class OutgoingUserDisconnected(BaseWebSocketMessage):
    type: WebSocketEventType = WebSocketEventType.USER_DISCONNECTED
    session_id: str
    nickname: Optional[str] = None  # populated once nickname is known


class OutgoingOnlineUsers(BaseWebSocketMessage):
    type: WebSocketEventType = WebSocketEventType.ONLINE_USERS
    users: List[dict]  # [{session_id, nickname}]


class OutgoingTypingIndicator(BaseWebSocketMessage):
    type: WebSocketEventType = WebSocketEventType.TYPING_INDICATOR
    session_id: str
    nickname: str
    is_typing: bool


class OutgoingPong(BaseWebSocketMessage):
    type: WebSocketEventType = WebSocketEventType.PONG


class OutgoingError(BaseWebSocketMessage):
    type: WebSocketEventType = WebSocketEventType.ERROR
    error: str
    details: Optional[Dict[str, Any]] = None


class OutgoingReactionUpdated(BaseWebSocketMessage):
    type: WebSocketEventType = WebSocketEventType.REACTION_UPDATED
    message_id: int
    reactions: List[dict]  # [{emoji, count, session_ids, nicknames}]


class OutgoingMessageDeleted(BaseWebSocketMessage):
    type: WebSocketEventType = WebSocketEventType.MESSAGE_DELETED
    message_id: int
    session_id: str


class OutgoingMessageEdited(BaseWebSocketMessage):
    type: WebSocketEventType = WebSocketEventType.MESSAGE_EDITED
    message_id: int
    content: str
    edited_at: str  # ISO 8601 string — serialised before construction


class OutgoingNotification(BaseWebSocketMessage):
    type: WebSocketEventType = WebSocketEventType.NOTIFICATION
    notification_id: int
    notif_type: str
    title: str
    body: Optional[str] = None
    target_type: Optional[str] = None
    target_id: Optional[int] = None
