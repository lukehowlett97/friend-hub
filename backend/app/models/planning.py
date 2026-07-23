import enum
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.models.message import Base


DEFAULT_GROUP_SLUG = "main"


class IdeaStatus(str, enum.Enum):
    maybe = "maybe"
    planned = "planned"
    done = "done"
    rejected = "rejected"


class PollVoteMode(str, enum.Enum):
    single = "single"
    multiple = "multiple"


class PollEventType(str, enum.Enum):
    nickname_vote = "nickname_vote"
    role_vote = "role_vote"
    general_vote = "general_vote"


class PollStatus(str, enum.Enum):
    scheduled = "scheduled"
    live = "live"
    closed = "closed"
    cancelled = "cancelled"


POLL_SOURCE_CHAT_AGENDA = "chat_agenda"


class EventRsvpResponse(str, enum.Enum):
    yes = "yes"
    maybe = "maybe"
    no = "no"


class ActivityAction(str, enum.Enum):
    created = "created"
    updated = "updated"
    deleted = "deleted"
    voted = "voted"
    rsvped = "rsvped"
    completed = "completed"
    commented = "commented"
    reacted = "reacted"


class Group(Base):
    __tablename__ = "groups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(80), nullable=False)
    slug = Column(String(80), nullable=False, unique=True)
    notice = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, server_default="NOW()")


class Idea(Base):
    __tablename__ = "ideas"

    id = Column(Integer, primary_key=True, autoincrement=True)
    group_id = Column(Integer, ForeignKey("groups.id", ondelete="CASCADE"), nullable=False)
    room_id = Column(UUID(as_uuid=True), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=True)
    title = Column(String(160), nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String(60), nullable=False, default="general")
    status = Column(Enum(IdeaStatus, name="idea_status"), nullable=False, default=IdeaStatus.maybe)
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    archived_at = Column(DateTime, nullable=True)
    archived_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, server_default="NOW()")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class Poll(Base):
    __tablename__ = "polls"

    id = Column(Integer, primary_key=True, autoincrement=True)
    group_id = Column(Integer, ForeignKey("groups.id", ondelete="CASCADE"), nullable=False)
    room_id = Column(UUID(as_uuid=True), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=True)
    question = Column(String(220), nullable=False)
    vote_mode = Column(Enum(PollVoteMode, name="poll_vote_mode"), nullable=False, default=PollVoteMode.single)
    deadline_at = Column(DateTime, nullable=True)
    linked_idea_id = Column(Integer, ForeignKey("ideas.id", ondelete="SET NULL"), nullable=True)
    linked_event_id = Column(Integer, ForeignKey("events.id", ondelete="SET NULL"), nullable=True)
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    event_type = Column(String(24), nullable=True)
    target_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    proposed_nickname = Column(String(50), nullable=True)
    proposed_role = Column(String(64), nullable=True)
    voting_opens_at = Column(DateTime, nullable=True)
    source = Column(String(24), nullable=True)
    status = Column(String(24), nullable=True)
    open_message_id = Column(Integer, ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
    result_message_id = Column(Integer, ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
    archived_at = Column(DateTime, nullable=True)
    archived_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, server_default="NOW()")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class PollOption(Base):
    __tablename__ = "poll_options"

    id = Column(Integer, primary_key=True, autoincrement=True)
    poll_id = Column(Integer, ForeignKey("polls.id", ondelete="CASCADE"), nullable=False)
    label = Column(String(160), nullable=False)
    position = Column(Integer, nullable=False, default=0)


class PollVote(Base):
    __tablename__ = "poll_votes"
    __table_args__ = (
        UniqueConstraint("poll_id", "option_id", "user_id", name="unique_poll_option_user_vote"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    poll_id = Column(Integer, ForeignKey("polls.id", ondelete="CASCADE"), nullable=False)
    option_id = Column(Integer, ForeignKey("poll_options.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, server_default="NOW()")


class Reminder(Base):
    __tablename__ = "reminders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    group_id = Column(Integer, ForeignKey("groups.id", ondelete="CASCADE"), nullable=False)
    room_id = Column(UUID(as_uuid=True), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=True)
    text = Column(Text, nullable=False)
    context = Column(Text, nullable=True)
    due_at = Column(DateTime, nullable=True)
    linked_event_id = Column(Integer, ForeignKey("events.id", ondelete="SET NULL"), nullable=True)
    is_completed = Column(Boolean, default=False, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    # recurrence: None = one-time, 'daily', 'weekly', 'every_N_days'
    recurrence = Column(String(20), nullable=True)
    recurrence_days = Column(Integer, nullable=True)   # N when recurrence='every_N_days'
    recurrence_ends_at = Column(DateTime, nullable=True)
    last_triggered_at = Column(DateTime, nullable=True)
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    completed_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    archived_at = Column(DateTime, nullable=True)
    archived_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, server_default="NOW()")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class ReminderAssignee(Base):
    __tablename__ = "reminder_assignees"
    __table_args__ = (
        UniqueConstraint("reminder_id", "user_id", name="unique_reminder_assignee"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    reminder_id = Column(Integer, ForeignKey("reminders.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    notified_at = Column(DateTime, nullable=True)


class EventPost(Base):
    __tablename__ = "event_posts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    group_id = Column(Integer, ForeignKey("groups.id", ondelete="CASCADE"), nullable=False)
    event_id = Column(Integer, ForeignKey("events.id", ondelete="CASCADE"), nullable=False)
    content = Column(Text, nullable=False)
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, server_default="NOW()")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class Comment(Base):
    __tablename__ = "comments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    group_id = Column(Integer, ForeignKey("groups.id", ondelete="CASCADE"), nullable=False)
    target_type = Column(String(24), nullable=False)
    target_id = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, server_default="NOW()")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class ActivityLog(Base):
    __tablename__ = "activity_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    group_id = Column(Integer, ForeignKey("groups.id", ondelete="CASCADE"), nullable=False)
    actor_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action = Column(Enum(ActivityAction, name="activity_action"), nullable=False)
    target_type = Column(String(24), nullable=False)
    target_id = Column(Integer, nullable=True)
    summary = Column(String(240), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, server_default="NOW()")


class ItemHistory(Base):
    __tablename__ = "item_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    item_type = Column(String(24), nullable=False)
    item_id = Column(Integer, nullable=False)
    changed_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    changed_at = Column(DateTime, nullable=False, default=datetime.utcnow, server_default="NOW()")
    changes = Column(JSONB, nullable=False, default=dict)
