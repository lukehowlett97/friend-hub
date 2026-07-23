"""Database models and connection management."""

from app.models.message import (
    Base,
    User,
    UserRole,
    Message,
)

from app.models.reaction import Reaction
from app.models.member import GroupMember, MemberRole
from app.models.event import Event, EventInvite, EventRsvp
from app.models.photo import Photo, PhotoFolder
from app.models.photo_embedding import PhotoEmbedding, PhotoEmbeddingJob
from app.models.hub_item import HubItem, HubItemStatus, HubItemType
from app.models.home_appearance import HomeAppearance
from app.models.user_session import UserSession
from app.models.import_tracking import ExternalIdentity, ImportBatch, ImportedMessageSource
from app.models.imported_identity import ImportedIdentity
from app.models.planning import (
    ActivityAction,
    ActivityLog,
    Comment,
    EventPost,
    DEFAULT_GROUP_SLUG,
    EventRsvpResponse,
    Group,
    Idea,
    IdeaStatus,
    ItemHistory,
    Poll,
    PollOption,
    PollVote,
    PollVoteMode,
    Reminder,
    ReminderAssignee,
)
from app.models.ai_memory import AIMemoryEntry, AISuggestion
from app.models.notification_preference import NotificationPreference
from app.models.chat_vote_action import ChatVoteAction, ChatVoteActionType, ChatVoteStatus, ChatVoteThresholdType
from app.models.chat_vote_ballot import ChatVoteBallot
from app.models.chat_read_state import ChatReadState
from app.models.chat_embedding import ChatEmbedding, ChatEmbeddingJob
from app.models.chat_topic import ChatTopic, ChatTopicParticipant, ChatTopicSegment, RoomParticipantAlias, RoomTopicDetectionSettings
from app.models.room import Room, RoomMembership, RoomInvite, RoomSettings, RoomStatus, RoomMemberRole, DEFAULT_ROOM_ID, DEFAULT_ROOM_SLUG

__all__ = [
    "Base",
    "User",
    "UserRole",
    "Message",
    "Reaction",
    "GroupMember",
    "MemberRole",
    "Event",
    "EventInvite",
    "EventRsvp",
    "Photo",
    "PhotoFolder",
    "PhotoEmbedding",
    "PhotoEmbeddingJob",
    "HubItem",
    "HubItemStatus",
    "HubItemType",
    "HomeAppearance",
    "UserSession",
    "ExternalIdentity",
    "ImportBatch",
    "ImportedMessageSource",
    "ImportedIdentity",
    "ActivityAction",
    "ActivityLog",
    "Comment",
    "ItemHistory",
    "EventPost",
    "DEFAULT_GROUP_SLUG",
    "EventRsvpResponse",
    "Group",
    "Idea",
    "IdeaStatus",
    "Poll",
    "PollOption",
    "PollVote",
    "PollVoteMode",
    "Reminder",
    "ReminderAssignee",
    "AIMemoryEntry",
    "AISuggestion",
    "NotificationPreference",
    "ChatVoteAction",
    "ChatVoteActionType",
    "ChatVoteStatus",
    "ChatVoteThresholdType",
    "ChatVoteBallot",
    "ChatReadState",
    "ChatEmbedding",
    "ChatEmbeddingJob",
    "ChatTopic",
    "ChatTopicParticipant",
    "ChatTopicSegment",
    "RoomParticipantAlias",
    "RoomTopicDetectionSettings",
    "Room",
    "RoomMembership",
    "RoomInvite",
    "RoomSettings",
    "RoomStatus",
    "RoomMemberRole",
    "DEFAULT_ROOM_ID",
    "DEFAULT_ROOM_SLUG",
]
