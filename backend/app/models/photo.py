from datetime import datetime

from sqlalchemy import Boolean, text, Column, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.models.message import Base


class Photo(Base):
    __tablename__ = "photos"

    id = Column(Integer, primary_key=True, autoincrement=True)
    filename = Column(String(255), nullable=False, unique=True)
    thumbnail_filename = Column(String(255), nullable=True, unique=True)
    original_filename = Column(String(255), nullable=False)
    content_type = Column(String(100), nullable=False)
    size_bytes = Column(Integer, nullable=True)
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    thumbnail_size_bytes = Column(Integer, nullable=True)
    source_type = Column(String(64), nullable=False, default="manual_upload", server_default="manual_upload")
    source_id = Column(UUID(as_uuid=True), nullable=True)
    conversation_id = Column(String(80), nullable=True)
    message_id = Column(Integer, ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
    import_batch_id = Column(Integer, ForeignKey("import_batches.id", ondelete="SET NULL"), nullable=True)
    storage_path = Column(Text, nullable=False, default="", server_default="")
    file_size_bytes = Column(Integer, nullable=True)
    taken_at = Column(DateTime, nullable=True)
    # folder_id kept in DB for backwards compat — no longer used in code
    event_id = Column(Integer, ForeignKey("events.id", ondelete="SET NULL"), nullable=True)
    hub_item_id = Column(UUID(as_uuid=True), ForeignKey("hub_items.id", ondelete="SET NULL"), nullable=True)
    tag_id = Column(String(40), nullable=True)  # legacy single-tag; superseded by tags[]
    caption = Column(String(500), nullable=True)
    tags = Column(JSON, nullable=False, default=list)
    uploaded_by_session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.session_id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, server_default="NOW()")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, server_default=text("NOW()"))
    deleted_at = Column(DateTime, nullable=True)
    deleted_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    room_id = Column(UUID(as_uuid=True), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=True)


# PhotoFolder is kept here so create_all doesn't try to recreate the DB table,
# but the application no longer uses it.
class PhotoFolder(Base):
    __tablename__ = "photo_folders"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(80), nullable=False, unique=True)
    created_by_session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.session_id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, server_default="NOW()")
