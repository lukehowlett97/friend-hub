from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID

from app.models.message import Base


class ImportBatch(Base):
    __tablename__ = "import_batches"

    id = Column(Integer, primary_key=True, autoincrement=True)
    provider = Column(String(64), nullable=False)
    source_path = Column(Text, nullable=False)
    source_thread_path = Column(String(500), nullable=True)
    target_room_id = Column(String(80), nullable=True)
    status = Column(String(24), nullable=False, default="running", server_default="running")
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow, server_default=text("NOW()"))
    completed_at = Column(DateTime, nullable=True)
    message_count = Column(Integer, nullable=False, default=0, server_default="0")
    imported_count = Column(Integer, nullable=False, default=0, server_default="0")
    skipped_count = Column(Integer, nullable=False, default=0, server_default="0")
    media_count = Column(Integer, nullable=False, default=0, server_default="0")
    error_count = Column(Integer, nullable=False, default=0, server_default="0")
    errors = Column(JSON, nullable=False, default=list, server_default="[]")
    imported_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class ImportedMessageSource(Base):
    __tablename__ = "imported_message_sources"
    __table_args__ = (
        UniqueConstraint("provider", "source_hash", name="uq_imported_message_provider_hash"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    batch_id = Column(Integer, ForeignKey("import_batches.id", ondelete="SET NULL"), nullable=True)
    provider = Column(String(64), nullable=False)
    source_thread_path = Column(String(500), nullable=False)
    target_room_id = Column(String(80), nullable=True)
    source_hash = Column(String(64), nullable=False)
    message_id = Column(Integer, ForeignKey("messages.id", ondelete="CASCADE"), nullable=False)
    raw_sender_name = Column(String(255), nullable=False)
    source_timestamp = Column(DateTime, nullable=False)
    raw_metadata = Column(JSON, nullable=False, default=dict, server_default="{}")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, server_default=text("NOW()"))


class ExternalIdentity(Base):
    __tablename__ = "external_identities"
    __table_args__ = (
        UniqueConstraint("provider", "external_name", name="uq_external_identity_provider_name"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    provider = Column(String(64), nullable=False)
    external_name = Column(String(255), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    user_session_id = Column(UUID(as_uuid=True), ForeignKey("users.session_id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, server_default=text("NOW()"))
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, server_default=text("NOW()"))
