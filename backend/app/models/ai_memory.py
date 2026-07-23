"""AI Memory and Suggestions models for Hub Memory feature."""
import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.models.message import Base


class AIMemoryEntry(Base):
    """Persistent memory entries for the Hub Memory system.
    
    These entries store summaries, decisions, preferences, and other
    contextual information that can be used to generate suggestions
    and maintain continuity across conversations.
    """
    __tablename__ = "ai_memory_entries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    room_id = Column(UUID(as_uuid=True), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=True)
    memory_type = Column(String(50), nullable=False)  # daily_summary, weekly_summary, decision, unresolved_plan, funny_moment, user_preference, suggestion_context
    title = Column(String(220), nullable=True)
    content = Column(Text, nullable=False)
    source_type = Column(String(50), nullable=True)  # chat, hub_item, manual
    source_id = Column(UUID(as_uuid=True), nullable=True)  # Reference to source entity (e.g., hub_item.id)
    confidence = Column(Float, nullable=True)  # 0.0 to 1.0 confidence score
    tags = Column(JSON, nullable=False, default=list)
    message_start_id = Column(Integer, nullable=True)  # first chat message covered by this entry
    message_end_id = Column(Integer, nullable=True)  # last chat message covered by this entry
    created_by = Column(String(50), nullable=False, default="hub_bot")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, server_default="NOW()")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class AISuggestion(Base):
    """AI-generated suggestions for Hub Items or actions.
    
    Suggestions are generated from memory entries and can be accepted
    (creating a Hub Item) or rejected/archived.
    """
    __tablename__ = "ai_suggestions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    suggestion_type = Column(String(50), nullable=False)  # poll, event, reminder, idea, tag, summary
    title = Column(String(220), nullable=False)
    body = Column(Text, nullable=True)
    status = Column(String(24), nullable=False, default="pending")  # pending, accepted, rejected, archived
    proposed_hub_item_type = Column(String(24), nullable=True)  # idea, poll, reminder, event, note
    proposed_payload = Column(JSON, nullable=True)  # Structured payload for creating Hub Item
    source_memory_ids = Column(JSON, nullable=False, default=list)  # List of AIMemoryEntry IDs (as strings)
    created_hub_item_id = Column(UUID(as_uuid=True), ForeignKey("hub_items.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, server_default="NOW()")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)