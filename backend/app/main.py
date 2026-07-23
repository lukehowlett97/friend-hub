"""
Main FastAPI application for Friend Hub Chat.
Clean, minimal setup that delegates functionality to domain modules.
"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_photo_upload_path, get_settings
from app.models.database import database
from app.domains.chat.connection_manager import ConnectionManager
from app.api.v1.router import router as api_v1_router, set_connection_manager
from app.api.v1.archive import archive_router
from app.api.v1.ai_router import router as ai_router
from app.api.v1.draft_action_router import router as draft_action_router
from app.api.v1.group_lore_router import router as group_lore_router
from app.api.v1.stats_router import router as stats_explorer_router
from app.api.v1.image_embeddings_router import router as image_embeddings_router
from app.api.v1.chat_embeddings_router import router as chat_embeddings_router
from app.api.v1.media_router import router as media_router
from app.api.v1.notes_router import router as notes_router
from app.api.v1.photo_search_router import router as photo_search_router
from app.api.v1.topics_router import router as topics_router
from app.domains.governance.vote_router import router as governance_vote_router, set_connection_manager as set_governance_connection_manager
from app.api.v1.websocket import websocket_endpoint

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Get settings
settings = get_settings()

# Initialize connection manager
connection_manager = ConnectionManager()


async def _backfill_photo_message_links():
    from app.models.database import async_session_factory
    from app.domains.photos.linking import backfill_photo_message_ids

    try:
        async with async_session_factory() as session:
            updated = await backfill_photo_message_ids(session)
        if updated:
            logger.info(f"Linked {updated} imported photos to their source messages")
    except Exception:
        logger.exception("Photo message-link backfill failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle application startup and shutdown."""
    # Startup
    logger.info(f"Starting {settings.app_name} v{settings.app_version}")
    logger.info(f"Debug mode: {settings.debug}")

    # Initialize database
    await database.connect()
    logger.info("Database connected and tables created")

    # Set connection manager for API routes
    set_connection_manager(connection_manager)
    set_governance_connection_manager(connection_manager)

    # Start reminder scheduler
    from app.domains.reminders.scheduler import run_reminder_scheduler
    scheduler_task = asyncio.create_task(run_reminder_scheduler())

    # Start daily summary scheduler
    from app.domains.ai.daily_summary_scheduler import run_daily_summary_scheduler
    daily_summary_task = asyncio.create_task(run_daily_summary_scheduler())

    # One-off: link imported photos to their messages (no-op once backfilled)
    backfill_task = asyncio.create_task(_backfill_photo_message_links())

    yield

    # Shutdown
    logger.info("Shutting down...")
    for task in (scheduler_task, daily_summary_task, backfill_task):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    await database.disconnect()

    # Close all WebSocket connections
    connection_manager.disconnect_all()


# Create FastAPI app
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan
)

photo_upload_path = get_photo_upload_path()
photo_upload_path.mkdir(parents=True, exist_ok=True)
(photo_upload_path.parent / "avatars").mkdir(parents=True, exist_ok=True)
(photo_upload_path.parent / "videos").mkdir(parents=True, exist_ok=True)
(photo_upload_path.parent / "audio").mkdir(parents=True, exist_ok=True)

# Configure CORS — explicit methods/headers, no credentials for localStorage bearer auth
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-Session-Id"],
)

# Include API routes
app.include_router(media_router)
app.include_router(api_v1_router)
app.include_router(archive_router)
app.include_router(ai_router)
app.include_router(draft_action_router)
app.include_router(group_lore_router)
app.include_router(stats_explorer_router)
app.include_router(notes_router)
app.include_router(governance_vote_router)
app.include_router(image_embeddings_router)
app.include_router(chat_embeddings_router)
app.include_router(photo_search_router)
app.include_router(topics_router)

# Root endpoint
@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "app": settings.app_name,
        "version": settings.app_version,
        "status": "running"
    }

# WebSocket endpoint — token passed as query param ?token=<raw_token>
@app.websocket("/ws")
async def websocket_handler(websocket: WebSocket):
    await websocket_endpoint(websocket, connection_manager)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug
    )
