"""
Authenticated media serving for uploaded files.

Replaces the unauthenticated StaticFiles mounts for /uploads/*.
All routes require a valid session. Room-scoped media (photos, videos, audio)
additionally require the requesting user to be a member of the room that owns
the file. Avatars require auth only — they must be visible to any authenticated
user regardless of room context.

Path traversal is prevented by resolving the requested filename against the
configured upload root and rejecting any path that escapes it.
"""
import mimetypes
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_photo_upload_path, get_settings
from app.domains.auth.service import AuthService
from app.domains.rooms.repository import RoomRepository
from app.models.database import get_db_session
from app.models.message import User
from app.models.photo import Photo
from app.models.video import AudioFile, Video

AUTH_COOKIE_NAME = "friend_hub_session"

router = APIRouter()


# ── Auth helpers ──────────────────────────────────────────────────────────────

def _bearer_token(authorization: Optional[str]) -> Optional[str]:
    if not authorization or not isinstance(authorization, str):
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


async def _require_auth(
    authorization: Optional[str],
    session_cookie: Optional[str],
    db: AsyncSession,
) -> User:
    auth_service = AuthService(db)
    token = _bearer_token(authorization)
    user = None
    if token:
        user, _ = await auth_service.authenticate_token(token)
    if user is None and session_cookie and session_cookie != token:
        user, _ = await auth_service.authenticate_token(session_cookie)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


# ── Path safety ───────────────────────────────────────────────────────────────

def _safe_file_path(base_dir: Path, filename: str) -> Path:
    """
    Resolve filename relative to base_dir and raise 404 if the result
    escapes base_dir (path traversal) or contains a path separator.
    """
    if "/" in filename or "\\" in filename:
        raise HTTPException(status_code=404)
    resolved = (base_dir / filename).resolve()
    try:
        resolved.relative_to(base_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=404)
    return resolved


def _serve(path: Path) -> FileResponse:
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404)
    media_type, _ = mimetypes.guess_type(str(path))
    return FileResponse(str(path), media_type=media_type or "application/octet-stream")


# ── Room membership check ─────────────────────────────────────────────────────

async def _require_room_member_for_file(
    user: User,
    room_id,  # UUID | None from the DB record
    db: AsyncSession,
) -> None:
    """
    If the file has a room_id, verify the user is a member of that room.
    Files with no room_id (e.g. legacy imports) are accessible to any
    authenticated user — they pre-date multi-room and have no isolation context.
    """
    if getattr(user, "user_type", None) == "guest" and room_id is None:
        raise HTTPException(status_code=404)
    if room_id is None:
        return
    repo = RoomRepository(db)
    if not await repo.is_member(room_id, user.id):
        raise HTTPException(status_code=404)


# ── Photo endpoints ───────────────────────────────────────────────────────────

@router.get("/uploads/photos/{filename}")
async def serve_photo(
    filename: str,
    authorization: Optional[str] = Header(default=None),
    session_cookie: Optional[str] = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
) -> FileResponse:
    user = await _require_auth(authorization, session_cookie, db)

    upload_dir = get_photo_upload_path()
    file_path = _safe_file_path(upload_dir, filename)

    # Strip thumbnail suffix to find the canonical filename for the DB lookup.
    # Both display and thumbnail files share the same room_id via the parent record.
    lookup_name = filename
    result = await db.execute(
        select(Photo.room_id).where(
            (Photo.filename == lookup_name) | (Photo.thumbnail_filename == lookup_name)
        )
    )
    row = result.first()
    room_id = row[0] if row else None
    await _require_room_member_for_file(user, room_id, db)

    return _serve(file_path)


# ── Avatar endpoints ──────────────────────────────────────────────────────────
# Avatars are user profile pictures — visible to any authenticated user,
# not tied to a specific room.

@router.get("/uploads/avatars/{filename}")
async def serve_avatar(
    filename: str,
    authorization: Optional[str] = Header(default=None),
    session_cookie: Optional[str] = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
) -> FileResponse:
    await _require_auth(authorization, session_cookie, db)

    avatar_dir = get_photo_upload_path().parent / "avatars"
    file_path = _safe_file_path(avatar_dir, filename)

    return _serve(file_path)


# ── Video endpoints ───────────────────────────────────────────────────────────

@router.get("/uploads/videos/{filename}")
async def serve_video(
    filename: str,
    authorization: Optional[str] = Header(default=None),
    session_cookie: Optional[str] = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
) -> FileResponse:
    user = await _require_auth(authorization, session_cookie, db)

    video_dir = get_photo_upload_path().parent / "videos"
    file_path = _safe_file_path(video_dir, filename)

    result = await db.execute(
        select(Video.room_id).where(
            (Video.filename == filename) | (Video.thumbnail_filename == filename)
        )
    )
    row = result.first()
    room_id = row[0] if row else None
    await _require_room_member_for_file(user, room_id, db)

    return _serve(file_path)


# ── Audio endpoints ───────────────────────────────────────────────────────────

@router.get("/uploads/audio/{filename}")
async def serve_audio(
    filename: str,
    authorization: Optional[str] = Header(default=None),
    session_cookie: Optional[str] = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
) -> FileResponse:
    user = await _require_auth(authorization, session_cookie, db)

    audio_dir = get_photo_upload_path().parent / "audio"
    file_path = _safe_file_path(audio_dir, filename)

    result = await db.execute(
        select(AudioFile.room_id).where(AudioFile.filename == filename)
    )
    row = result.first()
    room_id = row[0] if row else None
    await _require_room_member_for_file(user, room_id, db)

    return _serve(file_path)
