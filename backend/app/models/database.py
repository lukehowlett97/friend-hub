import asyncpg
from pathlib import Path
from sqlalchemy import URL
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.config import get_settings
from app.models.event import Event, EventInvite, EventRsvp  # noqa: F401 — registers tables with Base.metadata
from app.models.message import Base
from app.models.member import GroupMember  # noqa: F401 — registers table with Base.metadata
from app.models.photo import Photo, PhotoFolder  # noqa: F401 — registers tables with Base.metadata
from app.models.photo_embedding import PhotoEmbedding, PhotoEmbeddingJob  # noqa: F401 — registers tables with Base.metadata
from app.models.hub_item import HubItem  # noqa: F401 — registers table with Base.metadata
from app.models.home_appearance import HomeAppearance  # noqa: F401 — registers table with Base.metadata
from app.models.note import Note, NoteRevision  # noqa: F401 — registers table with Base.metadata
from app.models.planning import ActivityLog, Comment, EventPost, Group, Idea, Poll, PollOption, PollVote, Reminder, ReminderAssignee  # noqa: F401
from app.models.reaction import Reaction  # noqa: F401 — registers table with Base.metadata
from app.models.notification import Notification  # noqa: F401 — registers table with Base.metadata
from app.models.user_session import UserSession  # noqa: F401 — registers table with Base.metadata
from app.models.import_tracking import ImportBatch, ImportedMessageSource, ExternalIdentity  # noqa: F401 — registers tables with Base.metadata
from app.models.imported_identity import ImportedIdentity  # noqa: F401 — registers table with Base.metadata
from app.models.push_subscription import PushSubscription  # noqa: F401 — registers table with Base.metadata
from app.models.notification_preference import NotificationPreference  # noqa: F401 — registers table with Base.metadata
from app.models.ai_memory import AIMemoryEntry, AISuggestion  # noqa: F401 — registers tables with Base.metadata
from app.models.ai_draft_action import AIDraftAction  # noqa: F401 — registers table with Base.metadata
from app.models.chat_vote_action import ChatVoteAction  # noqa: F401 — registers table with Base.metadata
from app.models.chat_vote_ballot import ChatVoteBallot  # noqa: F401 — registers table with Base.metadata
from app.models.chat_read_state import ChatReadState  # noqa: F401 — registers table with Base.metadata
from app.models.chat_embedding import ChatEmbedding, ChatEmbeddingJob  # noqa: F401 — registers tables with Base.metadata
from app.models.chat_topic import ChatTopic, ChatTopicParticipant, ChatTopicSegment, RoomParticipantAlias, RoomTopicDetectionSettings  # noqa: F401 — registers tables with Base.metadata
from app.models.room import Room, RoomMembership, RoomInvite, RoomSettings  # noqa: F401 — registers tables with Base.metadata

settings = get_settings()

# Async SQLAlchemy engine
DATABASE_URL = URL.create(
    "postgresql+asyncpg",
    username=settings.database_user,
    password=settings.database_password,
    host=settings.database_host,
    port=settings.database_port,
    database=settings.database_name,
)

engine = create_async_engine(DATABASE_URL, echo=settings.debug)
async_session_factory = async_sessionmaker(
    engine, 
    class_=AsyncSession, 
    expire_on_commit=False
)

class Database:
    def __init__(self):
        self.pool = None
        self.engine = engine
    
    async def connect(self):
        """Create asyncpg connection pool for direct queries and create tables."""
        self.pool = await asyncpg.create_pool(
            host=settings.database_host,
            port=settings.database_port,
            user=settings.database_user,
            password=settings.database_password,
            database=settings.database_name,
            min_size=5,
            max_size=20
        )

        await self._apply_existing_schema_migrations()
        
        # Create tables if they don't exist
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def _apply_existing_schema_migrations(self):
        """
        Apply lightweight idempotent SQL migrations needed before create_all.

        SQLAlchemy can create new tables, but it will not add columns to an
        existing table. Existing Friend Hub databases created before stable
        users do not have users.id, so user_sessions cannot be created until
        that migration runs.
        """
        migrations_dir = Path(__file__).resolve().parents[2] / "migrations"
        if not migrations_dir.exists() or not self.pool:
            return

        async with self.pool.acquire() as conn:
            users_table_exists = await conn.fetchval("SELECT to_regclass('public.users')")
            if users_table_exists:
                for migration_path in sorted(migrations_dir.glob("[0-9][0-9][0-9]_*.sql")):
                    await conn.execute(migration_path.read_text(encoding="utf-8"))
    
    async def disconnect(self):
        if self.pool:
            await self.pool.close()
        await self.engine.dispose()

database = Database()

# Dependency for getting database session
async def get_db_session():
    async with async_session_factory() as session:
        yield session
