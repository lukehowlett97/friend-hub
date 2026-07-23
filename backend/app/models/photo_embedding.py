from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, text

from app.models.message import Base


class PhotoEmbedding(Base):
    __tablename__ = "photo_embeddings"
    __table_args__ = (
        UniqueConstraint("photo_id", "model_name", "model_version", name="uq_photo_embedding_model"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    photo_id = Column(Integer, ForeignKey("photos.id", ondelete="CASCADE"), nullable=False)
    model_name = Column(String(120), nullable=False)
    model_version = Column(String(120), nullable=False)
    # Migrations use pgvector when available. The ORM keeps this as text so tests
    # and local metadata creation do not require the pgvector SQLAlchemy package.
    embedding = Column(Text, nullable=False)
    caption = Column(Text, nullable=True)
    tags = Column(JSON, nullable=False, default=list, server_default="[]")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, server_default=text("NOW()"))
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, server_default=text("NOW()"))


class PhotoEmbeddingJob(Base):
    __tablename__ = "photo_embedding_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    photo_id = Column(Integer, ForeignKey("photos.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(24), nullable=False, default="pending", server_default="pending")
    attempt_count = Column(Integer, nullable=False, default=0, server_default="0")
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, server_default=text("NOW()"))
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, server_default=text("NOW()"))
