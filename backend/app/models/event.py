from datetime import datetime

from sqlalchemy import text, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.models.message import Base


class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    group_id = Column(Integer, ForeignKey("groups.id", ondelete="CASCADE"), nullable=True)
    title = Column(String(120), nullable=False)
    description = Column(Text, nullable=True)
    location = Column(String(160), nullable=True)
    cover_photo_url = Column(String(500), nullable=True)
    photo_tag_id = Column(String(40), nullable=True)
    starts_at = Column(DateTime, nullable=False)
    linked_poll_id = Column(Integer, nullable=True)
    created_by_session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.session_id", ondelete="SET NULL"),
        nullable=True,
    )
    archived_at = Column(DateTime, nullable=True)
    archived_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, server_default="NOW()")
    updated_at = Column(DateTime, nullable=True)
    room_id = Column(UUID(as_uuid=True), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=True)


class EventInvite(Base):
    __tablename__ = "event_invites"
    __table_args__ = (
        UniqueConstraint("event_id", "user_id", name="unique_event_invite_user"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey("events.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    invited_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, server_default="NOW()")


class EventRsvp(Base):
    __tablename__ = "event_rsvps"
    __table_args__ = (
        UniqueConstraint("event_id", "user_session_id", name="unique_event_user_rsvp"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey("events.id", ondelete="CASCADE"), nullable=False)
    user_session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.session_id", ondelete="CASCADE"),
        nullable=False,
    )
    response = Column(String(8), nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)
