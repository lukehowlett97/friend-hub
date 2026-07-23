from datetime import datetime

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.models.message import Base


class ChatVoteBallot(Base):
    __tablename__ = "chat_vote_ballots"
    __table_args__ = (
        UniqueConstraint("vote_action_id", "user_id", name="chat_vote_ballots_unique_user_vote"),
        CheckConstraint("vote IN ('yes', 'no')", name="chat_vote_ballots_vote_check"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    vote_action_id = Column(Integer, ForeignKey("chat_vote_actions.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    vote = Column(String(8), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, server_default="NOW()")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, server_default="NOW()")
