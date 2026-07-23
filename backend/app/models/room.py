import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.models.message import Base

DEFAULT_ROOM_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
DEFAULT_ROOM_SLUG = "main"


class RoomStatus(str, enum.Enum):
    active = "active"
    archived = "archived"


class RoomMemberRole(str, enum.Enum):
    owner = "owner"
    admin = "admin"
    member = "member"


class Room(Base):
    __tablename__ = "rooms"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug = Column(String(80), nullable=False, unique=True)
    name = Column(String(120), nullable=False)
    status = Column(String(24), nullable=False, default=RoomStatus.active.value, server_default="active")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, server_default="NOW()")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, server_default="NOW()")


class RoomMembership(Base):
    __tablename__ = "room_memberships"
    __table_args__ = (UniqueConstraint("room_id", "user_id", name="uq_room_membership"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    room_id = Column(UUID(as_uuid=True), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(24), nullable=False, default=RoomMemberRole.member.value, server_default="member")
    joined_at = Column(DateTime, nullable=False, default=datetime.utcnow, server_default="NOW()")


class RoomInvite(Base):
    __tablename__ = "room_invites"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    room_id = Column(UUID(as_uuid=True), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False)
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    code = Column(String(64), nullable=False, unique=True)
    max_uses = Column(Integer, nullable=False, default=1)
    use_count = Column(Integer, nullable=False, default=0)
    expires_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, server_default="NOW()")


class RoomSettings(Base):
    __tablename__ = "room_settings"

    room_id = Column(UUID(as_uuid=True), ForeignKey("rooms.id", ondelete="CASCADE"), primary_key=True)
    allow_invites = Column(Boolean, nullable=False, default=True, server_default="true")
    max_members = Column(Integer, nullable=True)
    notice = Column(Text, nullable=True)
    access_mode = Column(String(24), nullable=False, default="private", server_default="private")
    allow_guest_messages = Column(Boolean, nullable=False, default=False, server_default="false")
    simulation_enabled = Column(Boolean, nullable=False, default=False, server_default="false")
    guest_message_max_length = Column(Integer, nullable=False, default=500, server_default="500")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, server_default="NOW()")
