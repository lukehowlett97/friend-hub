from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.models.message import Base
from app.models.room import DEFAULT_ROOM_ID


class Note(Base):
    __tablename__ = "notes"
    __table_args__ = (
        UniqueConstraint("room_id", "room_sequence", name="uq_notes_room_sequence"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    room_id = Column(UUID(as_uuid=True), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False, default=DEFAULT_ROOM_ID)
    group_id = Column(Integer, ForeignKey("groups.id", ondelete="CASCADE"), nullable=True)
    room_sequence = Column(Integer, nullable=False)
    title = Column(String(220), nullable=False)
    body = Column(Text, nullable=False, default="", server_default="")
    note_type = Column(String(32), nullable=False, default="general", server_default="general")
    edit_mode = Column(String(32), nullable=False, default="owner_only", server_default="owner_only")
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    archived_at = Column(DateTime, nullable=True)
    archived_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, server_default="NOW()")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, server_default="NOW()")


class NoteRevision(Base):
    __tablename__ = "note_revisions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    note_id = Column(Integer, ForeignKey("notes.id", ondelete="CASCADE"), nullable=False)
    changed_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    before_title = Column(Text, nullable=True)
    after_title = Column(Text, nullable=True)
    before_body = Column(Text, nullable=True)
    after_body = Column(Text, nullable=True)
    before_note_type = Column(String(32), nullable=True)
    after_note_type = Column(String(32), nullable=True)
    before_edit_mode = Column(String(32), nullable=True)
    after_edit_mode = Column(String(32), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, server_default="NOW()")

