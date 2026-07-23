import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, Date, DateTime, Float, ForeignKey, Integer, JSON, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models.message import Base


class ChatTopic(Base):
    """Generated topic cluster over chat embedding batches."""

    __tablename__ = "chat_topics"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    room_id = Column(UUID(as_uuid=True), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False)
    label = Column(Text, nullable=False)
    keywords = Column(JSON, nullable=False, default=list, server_default="[]")
    description = Column(Text, nullable=True)
    raw_label = Column(Text, nullable=True)
    refined_label = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)
    tags = Column(JSON, nullable=False, default=list, server_default="[]")
    topic_type = Column(String(40), nullable=True)
    refinement_model = Column(Text, nullable=True)
    refined_at = Column(DateTime(timezone=True), nullable=True)
    confidence = Column(Float, nullable=True)
    label_source = Column(String(40), nullable=False, default="keyword_placeholder", server_default="keyword_placeholder")
    generation_type = Column(String(40), nullable=False, default="semantic_cluster", server_default="semantic_cluster")
    topic_date = Column(Date, nullable=True)
    bucket_start_at = Column(DateTime(timezone=True), nullable=True)
    bucket_end_at = Column(DateTime(timezone=True), nullable=True)
    message_start_id = Column(Integer, ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
    message_end_id = Column(Integer, ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
    first_message_at = Column(DateTime(timezone=True), nullable=True)
    last_message_at = Column(DateTime(timezone=True), nullable=True)
    batch_count = Column(Integer, nullable=False, default=0, server_default="0")
    model_name = Column(Text, nullable=False)
    model_version = Column(Text, nullable=False)
    detection_version = Column(Text, nullable=False)
    status = Column(String(24), nullable=False, default="active", server_default="active")
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, server_default=text("NOW()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, server_default=text("NOW()"))
    segments = relationship("ChatTopicSegment", back_populates="topic", cascade="all, delete-orphan")
    participants = relationship("ChatTopicParticipant", back_populates="topic", cascade="all, delete-orphan")


class ChatTopicSegment(Base):
    """One message-batch embedding assigned to a generated topic."""

    __tablename__ = "chat_topic_segments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    topic_id = Column(UUID(as_uuid=True), ForeignKey("chat_topics.id", ondelete="CASCADE"), nullable=False)
    room_id = Column(UUID(as_uuid=True), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False)
    embedding_source_id = Column(Text, nullable=False)
    message_start_id = Column(Integer, ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
    message_end_id = Column(Integer, ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
    score = Column(Float, nullable=True)
    excerpt = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, server_default=text("NOW()"))
    topic = relationship("ChatTopic", back_populates="segments")


class ChatTopicParticipant(Base):
    """Aggregated participant presence for a generated topic."""

    __tablename__ = "chat_topic_participants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    topic_id = Column(UUID(as_uuid=True), ForeignKey("chat_topics.id", ondelete="CASCADE"), nullable=False)
    room_id = Column(UUID(as_uuid=True), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    canonical_name = Column(Text, nullable=False)
    display_name = Column(Text, nullable=True)
    message_count = Column(Integer, nullable=False, default=0, server_default="0")
    segment_count = Column(Integer, nullable=False, default=0, server_default="0")
    first_seen_at = Column(DateTime(timezone=True), nullable=True)
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, server_default=text("NOW()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, server_default=text("NOW()"))
    topic = relationship("ChatTopic", back_populates="participants")


class RoomTopicDetectionSettings(Base):
    """Optional room-specific overrides for topic detection."""

    __tablename__ = "room_topic_detection_settings"

    room_id = Column(UUID(as_uuid=True), ForeignKey("rooms.id", ondelete="CASCADE"), primary_key=True)
    enabled = Column(Boolean, nullable=True)
    similarity_threshold = Column(Float, nullable=True)
    hard_gap_minutes = Column(Integer, nullable=True)
    soft_gap_minutes = Column(Integer, nullable=True)
    max_topic_duration_hours = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, server_default=text("NOW()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, server_default=text("NOW()"))


class RoomParticipantAlias(Base):
    """Room-scoped display-name override used only for AI export/refinement text."""

    __tablename__ = "room_participant_aliases"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    room_id = Column(UUID(as_uuid=True), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False)
    display_name = Column(Text, nullable=False)
    canonical_name = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, server_default=text("NOW()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, server_default=text("NOW()"))
