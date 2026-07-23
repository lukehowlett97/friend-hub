from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID

from app.models.message import Base


class ChatEmbedding(Base):
    """Embedding over chat content: message batches, memories, summaries, hub items."""

    __tablename__ = "chat_embeddings"
    __table_args__ = (
        UniqueConstraint(
            "source_type", "source_id", "model_name", "model_version",
            name="uq_chat_embedding_source_model",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_type = Column(String(24), nullable=False)  # message_batch | memory | summary | hub_item
    source_id = Column(Text, nullable=False)
    room_id = Column(UUID(as_uuid=True), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=True)
    message_start_id = Column(Integer, ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
    message_end_id = Column(Integer, ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
    model_name = Column(String(120), nullable=False)
    model_version = Column(String(120), nullable=False)
    # Migrations use pgvector when available. The ORM keeps this as text so tests
    # and local metadata creation do not require the pgvector SQLAlchemy package.
    embedding = Column(Text, nullable=False)
    content_preview = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, server_default=text("NOW()"))
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, server_default=text("NOW()"))


class ChatEmbeddingJob(Base):
    __tablename__ = "chat_embedding_jobs"
    __table_args__ = (
        UniqueConstraint("source_type", "source_id", name="uq_chat_embedding_job_source"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_type = Column(String(24), nullable=False)
    source_id = Column(Text, nullable=False)
    room_id = Column(UUID(as_uuid=True), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=True)
    payload = Column(JSON, nullable=False, default=dict, server_default="{}")
    status = Column(String(24), nullable=False, default="pending", server_default="pending")
    attempt_count = Column(Integer, nullable=False, default=0, server_default="0")
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, server_default=text("NOW()"))
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, server_default=text("NOW()"))
