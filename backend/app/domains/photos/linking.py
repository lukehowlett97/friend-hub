"""Link photos to the chat messages that delivered them.

Imported photos created before the importer started setting photos.message_id
(May 2026) only reference their message implicitly: the message content lists
the photo's /uploads/photos/<filename> path. The backfill recovers the link so
SQL-level features (e.g. filtering photos by original sender) cover old rows.
"""
import logging

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.message import Message
from app.models.photo import Photo

logger = logging.getLogger(__name__)


def parse_photo_filenames(content: str) -> list[str]:
    """Extract /uploads/photos/ filenames referenced by a message body."""
    filenames = []
    for line in content.split("\n"):
        line = line.strip()
        if line.startswith("/uploads/photos/"):
            filenames.append(line.removeprefix("/uploads/photos/"))
    return filenames


async def backfill_photo_message_ids(db: AsyncSession) -> int:
    """Populate photos.message_id where the link is missing. Returns rows updated."""
    missing = (
        await db.execute(
            select(func.count(Photo.id)).where(
                Photo.message_id.is_(None),
                Photo.source_type == "messenger_import",
            )
        )
    ).scalar_one()
    if not missing:
        return 0

    msg_rows = await db.execute(
        select(Message.id, Message.content).where(Message.content.like("%/uploads/photos/%"))
    )
    filename_to_message: dict[str, int] = {}
    for msg_id, content in msg_rows.fetchall():
        for filename in parse_photo_filenames(content):
            filename_to_message.setdefault(filename, msg_id)
    if not filename_to_message:
        return 0

    unlinked = await db.execute(
        select(Photo.id, Photo.filename).where(
            Photo.message_id.is_(None),
            Photo.source_type == "messenger_import",
        )
    )
    params = [
        {"id": photo_id, "message_id": filename_to_message[filename]}
        for photo_id, filename in unlinked.fetchall()
        if filename in filename_to_message
    ]
    if not params:
        return 0
    await db.execute(update(Photo), params)
    await db.commit()
    return len(params)
