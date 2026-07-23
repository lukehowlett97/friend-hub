import enum
from datetime import datetime

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.models.message import Base


class ChatVoteActionType(str, enum.Enum):
    nickname_change = "nickname_change"
    display_role_change = "display_role_change"
    restriction_apply = "restriction_apply"
    restriction_remove = "restriction_remove"
    rule_create = "rule_create"
    rule_repeal = "rule_repeal"
    council_motion = "council_motion"


class ChatVoteStatus(str, enum.Enum):
    open = "open"
    passed = "passed"
    failed = "failed"
    expired = "expired"
    cancelled = "cancelled"


class ChatVoteThresholdType(str, enum.Enum):
    active_member_majority = "active_member_majority"


class ChatVoteAction(Base):
    __tablename__ = "chat_vote_actions"
    __table_args__ = (
        CheckConstraint(
            "action_type IN ('nickname_change', 'display_role_change', 'restriction_apply', "
            "'restriction_remove', 'rule_create', 'rule_repeal', 'council_motion')",
            name="chat_vote_actions_action_type_check",
        ),
        CheckConstraint(
            "status IN ('open', 'passed', 'failed', 'expired', 'cancelled')",
            name="chat_vote_actions_status_check",
        ),
        CheckConstraint(
            "threshold_type IN ('active_member_majority')",
            name="chat_vote_actions_threshold_type_check",
        ),
        CheckConstraint("threshold_value > 0", name="chat_vote_actions_threshold_value_positive"),
        CheckConstraint("yes_count >= 0 AND no_count >= 0", name="chat_vote_actions_counts_non_negative"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    group_id = Column(Integer, ForeignKey("groups.id", ondelete="CASCADE"), nullable=False)
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    target_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action_type = Column(String(40), nullable=False)
    status = Column(String(24), nullable=False, default=ChatVoteStatus.open.value, server_default="open")
    title = Column(String(160), nullable=False)
    summary = Column(Text, nullable=True)
    payload_json = Column(JSONB, nullable=False, default=dict, server_default="{}")
    threshold_type = Column(String(40), nullable=False)
    threshold_value = Column(Integer, nullable=False)
    yes_count = Column(Integer, nullable=False, default=0, server_default="0")
    no_count = Column(Integer, nullable=False, default=0, server_default="0")
    expires_at = Column(DateTime, nullable=False)
    resolved_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, server_default="NOW()")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, server_default="NOW()")
    resolved_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    open_message_id = Column(Integer, ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
    result_message_id = Column(Integer, ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
