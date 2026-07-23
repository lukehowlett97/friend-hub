import enum
import uuid
from datetime import datetime

from sqlalchemy import text, Boolean, Column, DateTime, ForeignKey, Index, Integer, JSON, SmallInteger, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.models.message import Base


class HubItemType(str, enum.Enum):
    idea = "idea"
    poll = "poll"
    reminder = "reminder"
    event = "event"
    note = "note"


class HubItemStatus(str, enum.Enum):
    open = "open"
    done = "done"
    archived = "archived"


class HubItem(Base):
    __tablename__ = "hub_items"
    __table_args__ = (
        UniqueConstraint("room_id", "item_type", "type_sequence", name="uq_hub_items_room_type_sequence_model"),
        UniqueConstraint("room_id", "source_type", "source_id", name="uq_hub_items_room_source_model"),
        Index("uq_hub_items_room_short_id_ci_model", "room_id", text("upper(short_id)"), unique=True),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    group_id = Column(Integer, ForeignKey("groups.id", ondelete="CASCADE"), nullable=False)
    room_id = Column(UUID(as_uuid=True), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=True)
    short_id = Column(String(20), nullable=False)
    item_type = Column(String(24), nullable=False)
    type_sequence = Column(Integer, nullable=False)
    title = Column(String(220), nullable=False)
    body = Column(Text, nullable=True)
    tags = Column(JSON, nullable=False, default=list)
    status = Column(String(24), nullable=False, default=HubItemStatus.open.value)
    pinned_to_home = Column(Boolean, nullable=False, default=False)
    sent_to_chat_at = Column(DateTime, nullable=True)
    chat_message_id = Column(Integer, ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    assigned_to_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    due_at = Column(DateTime, nullable=True)
    event_start_at = Column(DateTime, nullable=True)
    event_end_at = Column(DateTime, nullable=True)
    source_type = Column(String(24), nullable=True)
    source_id = Column(Integer, nullable=True)
    cover_photo_id = Column(Integer, ForeignKey("photos.id", ondelete="SET NULL"), nullable=True)
    cover_photo_position_x = Column(SmallInteger, nullable=False, default=50, server_default="50")
    cover_photo_position_y = Column(SmallInteger, nullable=False, default=50, server_default="50")
    archived_at = Column(DateTime, nullable=True)
    archived_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, server_default="NOW()")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
