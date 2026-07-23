from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.models.message import Base


class Video(Base):
    __tablename__ = "videos"

    id = Column(Integer, primary_key=True, autoincrement=True)
    filename = Column(String(255), nullable=False, unique=True)
    thumbnail_filename = Column(String(255), nullable=True, unique=True)
    original_filename = Column(String(255), nullable=False)
    content_type = Column(String(100), nullable=False, default="video/mp4", server_default="video/mp4")
    size_bytes = Column(Integer, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    source_type = Column(String(64), nullable=False, default="manual_upload", server_default="manual_upload")
    source_id = Column(UUID(as_uuid=True), nullable=True)
    conversation_id = Column(String(80), nullable=True)
    message_id = Column(Integer, ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
    import_batch_id = Column(Integer, ForeignKey("import_batches.id", ondelete="SET NULL"), nullable=True)
    storage_path = Column(Text, nullable=False, default="", server_default="")
    caption = Column(String(500), nullable=True)
    tags = Column(JSON, nullable=False, default=list)
    uploaded_by_session_id = Column(UUID(as_uuid=True), ForeignKey("users.session_id", ondelete="SET NULL"), nullable=True)
    room_id = Column(UUID(as_uuid=True), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=True)
    taken_at = Column(DateTime, nullable=True)
    deleted_at = Column(DateTime, nullable=True)
    deleted_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, server_default="NOW()")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, server_default="NOW()")


class AudioFile(Base):
    __tablename__ = "audio_files"

    id = Column(Integer, primary_key=True, autoincrement=True)
    filename = Column(String(255), nullable=False, unique=True)
    original_filename = Column(String(255), nullable=False)
    content_type = Column(String(100), nullable=False, default="audio/mpeg", server_default="audio/mpeg")
    size_bytes = Column(Integer, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    source_type = Column(String(64), nullable=False, default="messenger_import", server_default="messenger_import")
    conversation_id = Column(String(80), nullable=True)
    message_id = Column(Integer, ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
    import_batch_id = Column(Integer, ForeignKey("import_batches.id", ondelete="SET NULL"), nullable=True)
    storage_path = Column(Text, nullable=False, default="", server_default="")
    uploaded_by_session_id = Column(UUID(as_uuid=True), ForeignKey("users.session_id", ondelete="SET NULL"), nullable=True)
    room_id = Column(UUID(as_uuid=True), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=True)
    taken_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, server_default="NOW()")
