"""SQLAlchemy model for AI Draft Actions."""
import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.models.message import Base


class AIDraftAction(Base):
    """An AI-proposed Hub Item draft awaiting user confirmation.

    The AI may only create draft records (status='draft').
    A user must explicitly accept to create the real Event, Poll, or Reminder.
    """
    __tablename__ = "ai_draft_actions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Scoping
    group_id = Column(Integer, ForeignKey("groups.id", ondelete="CASCADE"), nullable=False)
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=False)

    # Proposal metadata
    proposed_by = Column(String(24), nullable=False, default="ai")
    action_type = Column(String(50), nullable=False, default="create_hub_item")
    item_type = Column(String(24), nullable=False)  # event | poll | reminder

    # Lifecycle
    status = Column(String(24), nullable=False, default="draft")  # draft | accepted | rejected | expired

    # Display
    title = Column(Text, nullable=False)
    summary = Column(Text, nullable=True)

    # Type-specific structured payload
    payload_json = Column(JSON, nullable=False, default=dict)

    # Origin
    source = Column(String(50), nullable=False, default="hub_lab")  # hub_lab | chat | scheduled_job
    source_message_id = Column(Integer, ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
    agent_run_id = Column(UUID(as_uuid=True), ForeignKey("ai_agent_runs.id", ondelete="SET NULL"), nullable=True)

    # Set on accept: the hub_items mirror row (created for every item type)
    created_hub_item_id = Column(UUID(as_uuid=True), ForeignKey("hub_items.id", ondelete="SET NULL"), nullable=True)

    # Set on accept: canonical domain rows (only one non-null per draft)
    created_poll_id = Column(Integer, ForeignKey("polls.id", ondelete="SET NULL"), nullable=True)
    created_event_id = Column(Integer, ForeignKey("events.id", ondelete="SET NULL"), nullable=True)
    created_reminder_id = Column(Integer, ForeignKey("reminders.id", ondelete="SET NULL"), nullable=True)

    # Resolution
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolved_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, server_default="NOW()")
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
