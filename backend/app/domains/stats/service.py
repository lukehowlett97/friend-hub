"""Stats explorer service — room-isolated aggregate queries for the stats page.

Supports shared filter params: from/to date range, group_by bucket, optional
user_id filter. All queries are room-scoped via room_id.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import and_, case, cast, Date, desc, extract, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.imported_identity import ImportedIdentity
from app.models.message import Message, User
from app.models.photo import Photo
from app.models.reaction import Reaction
from app.models.room import RoomMembership
from app.models.video import AudioFile

logger = logging.getLogger(__name__)

MAX_USERS = 500
MAX_REACTIONS = 30
MAX_MESSAGES = 20
THUMB_REACTIONS = {
    "👍", "👎",
    "👍🏻", "👍🏼", "👍🏽", "👍🏾", "👍🏿",
    "👎🏻", "👎🏼", "👎🏽", "👎🏾", "👎🏿",
}


def _naive_utc(value: Optional[datetime]) -> Optional[datetime]:
    """Normalise to naive UTC — matches how Message.created_at is stored."""
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _date_trunc_expr(group_by: str, col):
    """SQLAlchemy expression to truncate a DateTime column to a bucket."""
    valid = {"day", "week", "month", "year"}
    bucket = group_by if group_by in valid else "day"
    return func.date_trunc(bucket, col)


def _msg_base(room_id, date_from=None, date_to=None, user_id=None):
    """Base WHERE conditions for message queries."""
    conds = [Message.is_deleted.is_(False), Message.room_id == room_id]
    if date_from:
        conds.append(Message.created_at >= date_from)
    if date_to:
        conds.append(Message.created_at < date_to)
    if user_id:
        conds.append(Message.user_id == user_id)
    from sqlalchemy import and_
    return and_(*conds)


def _reaction_room_join(room_id):
    """Reactions have no room_id — join through messages."""
    return Message.room_id == room_id


async def _disable_parallel_query(db: AsyncSession) -> None:
    """Avoid Docker /dev/shm exhaustion on broad reaction aggregates."""
    await db.execute(text("SET LOCAL max_parallel_workers_per_gather = 0"))


class StatsService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _room_member_count(self, room_id: UUID) -> int:
        native_message_exists = (
            select(Message.id)
            .where(
                Message.room_id == room_id,
                Message.is_deleted.is_(False),
                Message.is_imported.is_(False),
                or_(
                    Message.user_id == User.id,
                    and_(Message.user_id.is_(None), Message.user_session_id == User.session_id),
                ),
            )
            .exists()
        )
        linked_import_exists = (
            select(Message.id)
            .select_from(Message)
            .join(ImportedIdentity, Message.imported_identity_id == ImportedIdentity.id)
            .where(
                Message.room_id == room_id,
                Message.is_deleted.is_(False),
                Message.is_imported.is_(True),
                Message.user_session_id == User.session_id,
                ImportedIdentity.linked_user_id.is_not(None),
                ImportedIdentity.linked_user_id != User.id,
            )
            .exists()
        )
        return (await self.db.execute(
            select(func.count(func.distinct(User.id)))
            .select_from(RoomMembership)
            .join(User, RoomMembership.user_id == User.id)
            .where(
                RoomMembership.room_id == room_id,
                User.is_active.is_(True),
                User.hidden_from_member_list.is_(False),
                User.is_test_user.is_(False),
                User.is_bot.is_(False),
                User.status.notin_(["deactivated", "archived", "deleted"]),
                User.user_type.notin_(["test", "system", "bot"]),
                or_(native_message_exists, ~linked_import_exists),
            )
        )).scalar_one() or 0

    async def _imported_member_count(self, room_id: UUID) -> int:
        return (await self.db.execute(
            select(func.count(func.distinct(ImportedIdentity.id)))
            .select_from(ImportedIdentity)
            .join(Message, Message.imported_identity_id == ImportedIdentity.id)
            .where(
                Message.room_id == room_id,
                Message.is_deleted.is_(False),
                Message.is_imported.is_(True),
            )
        )).scalar_one() or 0

    # ── Activity timeline ─────────────────────────────────────────────────────

    async def activity(
        self,
        room_id: UUID,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        group_by: str = "day",
        user_id: Optional[UUID] = None,
        metric: str = "messages",
    ) -> dict:
        date_from = _naive_utc(date_from)
        date_to = _naive_utc(date_to)
        metric = metric if metric in {"messages", "photos", "gifs"} else "messages"

        if metric == "messages":
            Author = aliased(User)
            LinkedIdentity = aliased(ImportedIdentity)
            LinkedUser = aliased(User)
            effective_user_id = case(
                (and_(Message.is_imported.is_(True), LinkedUser.id.is_not(None)), LinkedUser.id),
                else_=func.coalesce(Message.user_id, Author.id),
            )
            conds = [Message.is_deleted.is_(False), Message.room_id == room_id]
            if date_from:
                conds.append(Message.created_at >= date_from)
            if date_to:
                conds.append(Message.created_at < date_to)
            if user_id:
                conds.append(effective_user_id == user_id)

            trunc = _date_trunc_expr(group_by, Message.created_at)
            rows = (await self.db.execute(
                select(trunc.label("bucket"), func.count(Message.id).label("n"))
                .select_from(Message)
                .outerjoin(Author, Message.user_session_id == Author.session_id)
                .outerjoin(LinkedIdentity, Message.imported_identity_id == LinkedIdentity.id)
                .outerjoin(LinkedUser, LinkedIdentity.linked_user_id == LinkedUser.id)
                .where(and_(*conds))
                .group_by("bucket")
                .order_by("bucket")
            )).fetchall()
        else:
            MessageAuthor = aliased(User)
            LinkedIdentity = aliased(ImportedIdentity)
            LinkedUser = aliased(User)
            Uploader = aliased(User)
            photo_date = func.coalesce(Photo.taken_at, Photo.created_at)
            effective_user_id = case(
                (and_(Message.is_imported.is_(True), LinkedUser.id.is_not(None)), LinkedUser.id),
                else_=func.coalesce(Message.user_id, MessageAuthor.id, Uploader.id),
            )
            conds = [
                Photo.room_id == room_id,
                Photo.deleted_at.is_(None),
                Photo.content_type == "image/gif" if metric == "gifs" else Photo.content_type != "image/gif",
            ]
            if date_from:
                conds.append(photo_date >= date_from)
            if date_to:
                conds.append(photo_date < date_to)
            if user_id:
                conds.append(effective_user_id == user_id)

            trunc = _date_trunc_expr(group_by, photo_date)
            rows = (await self.db.execute(
                select(trunc.label("bucket"), func.count(Photo.id).label("n"))
                .select_from(Photo)
                .outerjoin(Message, Photo.message_id == Message.id)
                .outerjoin(MessageAuthor, Message.user_session_id == MessageAuthor.session_id)
                .outerjoin(LinkedIdentity, Message.imported_identity_id == LinkedIdentity.id)
                .outerjoin(LinkedUser, LinkedIdentity.linked_user_id == LinkedUser.id)
                .outerjoin(Uploader, Photo.uploaded_by_session_id == Uploader.session_id)
                .where(and_(*conds))
                .group_by("bucket")
                .order_by("bucket")
            )).fetchall()

        return {
            "group_by": group_by,
            "metric": metric,
            "buckets": [
                {"date": r.bucket.isoformat() if r.bucket else None, "count": r.n}
                for r in rows
            ],
        }

    # ── Leaderboard ───────────────────────────────────────────────────────────

    async def leaderboard(
        self,
        room_id: UUID,
        metric: str = "messages",
        normalise: str = "absolute",
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        limit: int = 15,
    ) -> dict:
        date_from = _naive_utc(date_from)
        date_to = _naive_utc(date_to)
        limit = min(max(limit, 1), MAX_USERS)

        valid_metrics = {
            "messages", "words", "reactions_given", "reactions_received",
            "avg_length", "active_days", "photos_sent", "gifs_sent",
        }
        metric = metric if metric in valid_metrics else "messages"

        if metric == "messages":
            rows = (await self.db.execute(
                select(
                    User.nickname,
                    User.avatar_emoji,
                    User.avatar_url,
                    func.count(Message.id).label("value"),
                    func.count(func.distinct(cast(Message.created_at, Date))).label("active_days"),
                )
                .join(Message, Message.user_session_id == User.session_id)
                .where(_msg_base(room_id, date_from, date_to))
                .group_by(User.nickname, User.avatar_emoji, User.avatar_url)
                .order_by(desc("value"))
                .limit(MAX_USERS)
            )).fetchall()
            entries = [
                {
                    "nickname": r.nickname, "avatar_emoji": r.avatar_emoji,
                    "avatar_url": r.avatar_url, "value": r.value,
                    "active_days": r.active_days,
                }
                for r in rows
            ]

        elif metric == "words":
            # word count via split — approximate but fast in SQL via regexp
            rows = (await self.db.execute(
                select(
                    User.nickname,
                    User.avatar_emoji,
                    User.avatar_url,
                    func.sum(
                        func.array_length(
                            func.regexp_split_to_array(func.trim(Message.content), r'\s+'),
                            1,
                        )
                    ).label("value"),
                    func.count(func.distinct(cast(Message.created_at, Date))).label("active_days"),
                )
                .join(Message, Message.user_session_id == User.session_id)
                .where(_msg_base(room_id, date_from, date_to))
                .group_by(User.nickname, User.avatar_emoji, User.avatar_url)
                .order_by(desc("value"))
                .limit(MAX_USERS)
            )).fetchall()
            entries = [
                {
                    "nickname": r.nickname, "avatar_emoji": r.avatar_emoji,
                    "avatar_url": r.avatar_url, "value": int(r.value or 0),
                    "active_days": r.active_days,
                }
                for r in rows
            ]

        elif metric == "reactions_given":
            conds = [Message.room_id == room_id, Message.is_deleted.is_(False)]
            if date_from:
                conds.append(Reaction.created_at >= date_from)
            if date_to:
                conds.append(Reaction.created_at < date_to)
            rows = (await self.db.execute(
                select(
                    User.nickname,
                    User.avatar_emoji,
                    User.avatar_url,
                    func.count(Reaction.id).label("value"),
                )
                .join(Reaction, Reaction.user_session_id == User.session_id)
                .join(Message, Reaction.message_id == Message.id)
                .where(and_(*conds))
                .group_by(User.nickname, User.avatar_emoji, User.avatar_url)
                .order_by(desc("value"))
                .limit(MAX_USERS)
            )).fetchall()
            entries = [
                {
                    "nickname": r.nickname, "avatar_emoji": r.avatar_emoji,
                    "avatar_url": r.avatar_url, "value": r.value,
                    "active_days": None,
                }
                for r in rows
            ]

        elif metric == "reactions_received":
            # Count reactions on messages sent by each user
            MsgAuthor = aliased(User)
            conds = [Message.room_id == room_id, Message.is_deleted.is_(False)]
            if date_from:
                conds.append(Reaction.created_at >= date_from)
            if date_to:
                conds.append(Reaction.created_at < date_to)
            rows = (await self.db.execute(
                select(
                    MsgAuthor.nickname,
                    MsgAuthor.avatar_emoji,
                    MsgAuthor.avatar_url,
                    func.count(Reaction.id).label("value"),
                )
                .join(Message, Reaction.message_id == Message.id)
                .join(MsgAuthor, Message.user_session_id == MsgAuthor.session_id)
                .where(and_(*conds))
                .group_by(MsgAuthor.nickname, MsgAuthor.avatar_emoji, MsgAuthor.avatar_url)
                .order_by(desc("value"))
                .limit(MAX_USERS)
            )).fetchall()
            entries = [
                {
                    "nickname": r.nickname, "avatar_emoji": r.avatar_emoji,
                    "avatar_url": r.avatar_url, "value": r.value,
                    "active_days": None,
                }
                for r in rows
            ]

        elif metric == "avg_length":
            rows = (await self.db.execute(
                select(
                    User.nickname,
                    User.avatar_emoji,
                    User.avatar_url,
                    func.round(func.avg(func.length(Message.content)), 1).label("value"),
                    func.count(func.distinct(cast(Message.created_at, Date))).label("active_days"),
                )
                .join(Message, Message.user_session_id == User.session_id)
                .where(_msg_base(room_id, date_from, date_to))
                .group_by(User.nickname, User.avatar_emoji, User.avatar_url)
                .order_by(desc("value"))
                .limit(MAX_USERS)
            )).fetchall()
            entries = [
                {
                    "nickname": r.nickname, "avatar_emoji": r.avatar_emoji,
                    "avatar_url": r.avatar_url, "value": float(r.value or 0),
                    "active_days": r.active_days,
                }
                for r in rows
            ]

        elif metric == "active_days":
            rows = (await self.db.execute(
                select(
                    User.nickname,
                    User.avatar_emoji,
                    User.avatar_url,
                    func.count(func.distinct(cast(Message.created_at, Date))).label("value"),
                )
                .join(Message, Message.user_session_id == User.session_id)
                .where(_msg_base(room_id, date_from, date_to))
                .group_by(User.nickname, User.avatar_emoji, User.avatar_url)
                .order_by(desc("value"))
                .limit(MAX_USERS)
            )).fetchall()
            entries = [
                {
                    "nickname": r.nickname, "avatar_emoji": r.avatar_emoji,
                    "avatar_url": r.avatar_url, "value": r.value,
                    "active_days": r.value,
                }
                for r in rows
            ]

        elif metric in {"photos_sent", "gifs_sent"}:
            MessageAuthor = aliased(User)
            LinkedIdentity = aliased(ImportedIdentity)
            LinkedUser = aliased(User)
            Uploader = aliased(User)
            photo_date = func.coalesce(Photo.taken_at, Photo.created_at)
            effective_author = case(
                (and_(Message.is_imported.is_(True), LinkedUser.nickname.is_not(None)), LinkedUser.nickname),
                else_=func.coalesce(MessageAuthor.nickname, Uploader.nickname),
            )
            effective_avatar_emoji = case(
                (and_(Message.is_imported.is_(True), LinkedUser.avatar_emoji.is_not(None)), LinkedUser.avatar_emoji),
                else_=func.coalesce(MessageAuthor.avatar_emoji, Uploader.avatar_emoji),
            )
            effective_avatar_url = case(
                (and_(Message.is_imported.is_(True), LinkedUser.avatar_url.is_not(None)), LinkedUser.avatar_url),
                else_=func.coalesce(MessageAuthor.avatar_url, Uploader.avatar_url),
            )
            conds = [
                Photo.room_id == room_id,
                Photo.deleted_at.is_(None),
                Photo.content_type == "image/gif" if metric == "gifs_sent" else Photo.content_type != "image/gif",
            ]
            if date_from:
                conds.append(photo_date >= date_from)
            if date_to:
                conds.append(photo_date < date_to)
            rows = (await self.db.execute(
                select(
                    effective_author.label("nickname"),
                    effective_avatar_emoji.label("avatar_emoji"),
                    effective_avatar_url.label("avatar_url"),
                    func.count(Photo.id).label("value"),
                    func.count(func.distinct(cast(photo_date, Date))).label("active_days"),
                )
                .select_from(Photo)
                .outerjoin(Message, Photo.message_id == Message.id)
                .outerjoin(MessageAuthor, Message.user_session_id == MessageAuthor.session_id)
                .outerjoin(LinkedIdentity, Message.imported_identity_id == LinkedIdentity.id)
                .outerjoin(LinkedUser, LinkedIdentity.linked_user_id == LinkedUser.id)
                .outerjoin(Uploader, Photo.uploaded_by_session_id == Uploader.session_id)
                .where(and_(*conds), effective_author.is_not(None))
                .group_by(effective_author, effective_avatar_emoji, effective_avatar_url)
                .order_by(desc("value"))
                .limit(MAX_USERS)
            )).fetchall()
            entries = [
                {
                    "nickname": r.nickname, "avatar_emoji": r.avatar_emoji,
                    "avatar_url": r.avatar_url, "value": r.value,
                    "active_days": r.active_days,
                }
                for r in rows
            ]

        else:
            entries = []

        # Normalise
        if normalise == "per_active_day" and entries:
            for e in entries:
                ad = e.get("active_days") or 1
                e["value_normalised"] = round(e["value"] / ad, 2)
        elif normalise == "percent" and entries:
            total = sum(e["value"] for e in entries)
            for e in entries:
                e["value_normalised"] = round(e["value"] / total * 100, 1) if total else 0
        else:
            for e in entries:
                e["value_normalised"] = e["value"]

        entries.sort(key=lambda e: e.get("value_normalised") or 0, reverse=True)
        entries = entries[:limit]

        return {"metric": metric, "normalise": normalise, "entries": entries}

    # ── Reactions: top emojis ─────────────────────────────────────────────────

    async def top_reactions(
        self,
        room_id: UUID,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        limit: int = 20,
    ) -> dict:
        date_from = _naive_utc(date_from)
        date_to = _naive_utc(date_to)
        limit = min(limit, MAX_REACTIONS)
        await _disable_parallel_query(self.db)

        conds = [Message.room_id == room_id, Message.is_deleted.is_(False)]
        if date_from:
            conds.append(Reaction.created_at >= date_from)
        if date_to:
            conds.append(Reaction.created_at < date_to)
        from sqlalchemy import and_
        rows = (await self.db.execute(
            select(Reaction.emoji, func.count(Reaction.id).label("n"))
            .select_from(Reaction)
            .join(Message, Reaction.message_id == Message.id)
            .where(and_(*conds))
            .group_by(Reaction.emoji)
            .order_by(desc("n"))
            .limit(limit)
        )).fetchall()
        return {"reactions": [{"emoji": r.emoji, "count": r.n} for r in rows]}

    # ── Reactions: signature matrix (who gives which emoji) ───────────────────

    async def reaction_signature(
        self,
        room_id: UUID,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        direction: str = "given",
    ) -> dict:
        """
        direction="given"    → rows: reactor, cols: emoji
        direction="received" → rows: message author, cols: emoji
        """
        date_from = _naive_utc(date_from)
        date_to = _naive_utc(date_to)
        from sqlalchemy import and_

        conds = [Message.room_id == room_id, Message.is_deleted.is_(False)]
        if date_from:
            conds.append(Reaction.created_at >= date_from)
        if date_to:
            conds.append(Reaction.created_at < date_to)

        if direction == "received":
            Author = aliased(User)
            LinkedIdentity = aliased(ImportedIdentity)
            LinkedUser = aliased(User)
            effective_author = case(
                (and_(Message.is_imported.is_(True), LinkedUser.nickname.is_not(None)), LinkedUser.nickname),
                else_=Author.nickname,
            )
            rows = (await self.db.execute(
                select(
                    effective_author.label("person"),
                    Reaction.emoji,
                    func.count(Reaction.id).label("n"),
                )
                .select_from(Reaction)
                .join(Message, Reaction.message_id == Message.id)
                .join(Author, Message.user_session_id == Author.session_id)
                .outerjoin(LinkedIdentity, Message.imported_identity_id == LinkedIdentity.id)
                .outerjoin(LinkedUser, LinkedIdentity.linked_user_id == LinkedUser.id)
                .where(and_(*conds))
                .group_by("person", Reaction.emoji)
                .order_by("person", desc("n"))
            )).fetchall()
        else:
            Reactor = aliased(User)
            AliasIdentity = aliased(ImportedIdentity)
            AliasLinkedUser = aliased(User)
            reactor_alias = (
                select(
                    Message.user_session_id.label("session_id"),
                    func.min(AliasLinkedUser.nickname).label("canonical_nickname"),
                )
                .select_from(Message)
                .join(AliasIdentity, Message.imported_identity_id == AliasIdentity.id)
                .join(AliasLinkedUser, AliasIdentity.linked_user_id == AliasLinkedUser.id)
                .where(Message.room_id == room_id, Message.is_imported.is_(True))
                .group_by(Message.user_session_id)
                .subquery()
            )
            effective_reactor = func.coalesce(reactor_alias.c.canonical_nickname, Reactor.nickname)
            rows = (await self.db.execute(
                select(
                    effective_reactor.label("person"),
                    Reaction.emoji,
                    func.count(Reaction.id).label("n"),
                )
                .select_from(Reaction)
                .join(Message, Reaction.message_id == Message.id)
                .join(Reactor, Reaction.user_session_id == Reactor.session_id)
                .outerjoin(reactor_alias, reactor_alias.c.session_id == Reaction.user_session_id)
                .where(and_(*conds))
                .group_by("person", Reaction.emoji)
                .order_by("person", desc("n"))
            )).fetchall()

        # Pivot: people list, emoji list, matrix
        people: list[str] = []
        emojis_seen: dict[str, int] = {}
        emoji_totals: dict[str, int] = {}
        cells: dict[tuple, int] = {}

        for r in rows:
            if r.person not in people:
                people.append(r.person)
            emojis_seen[r.emoji] = emojis_seen.get(r.emoji, 0) + r.n
            emoji_totals[r.emoji] = emoji_totals.get(r.emoji, 0) + r.n
            cells[(r.person, r.emoji)] = r.n

        # Top emojis by total usage
        top_emojis = [e for e, _ in sorted(emoji_totals.items(), key=lambda x: -x[1])[:MAX_REACTIONS]]

        matrix = [
            [cells.get((person, emoji), 0) for emoji in top_emojis]
            for person in people
        ]

        return {
            "direction": direction,
            "people": people,
            "emojis": top_emojis,
            "matrix": matrix,
        }

    # ── Reactions: dyadic heatmap (who reacts to whom) ────────────────────────

    async def reaction_dyadic(
        self,
        room_id: UUID,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        limit: int = 15,
    ) -> dict:
        date_from = _naive_utc(date_from)
        date_to = _naive_utc(date_to)
        limit = min(limit, MAX_USERS)
        from sqlalchemy import and_

        Reactor = aliased(User)
        Author = aliased(User)
        ReceiverIdentity = aliased(ImportedIdentity)
        ReceiverLinkedUser = aliased(User)
        AliasIdentity = aliased(ImportedIdentity)
        AliasLinkedUser = aliased(User)
        reactor_alias = (
            select(
                Message.user_session_id.label("session_id"),
                func.min(AliasLinkedUser.nickname).label("canonical_nickname"),
            )
            .select_from(Message)
            .join(AliasIdentity, Message.imported_identity_id == AliasIdentity.id)
            .join(AliasLinkedUser, AliasIdentity.linked_user_id == AliasLinkedUser.id)
            .where(Message.room_id == room_id, Message.is_imported.is_(True))
            .group_by(Message.user_session_id)
            .subquery()
        )
        effective_giver = func.coalesce(reactor_alias.c.canonical_nickname, Reactor.nickname)
        effective_receiver = case(
            (and_(Message.is_imported.is_(True), ReceiverLinkedUser.nickname.is_not(None)), ReceiverLinkedUser.nickname),
            else_=Author.nickname,
        )

        conds = [Message.room_id == room_id, Message.is_deleted.is_(False)]
        if date_from:
            conds.append(Reaction.created_at >= date_from)
        if date_to:
            conds.append(Reaction.created_at < date_to)

        rows = (await self.db.execute(
            select(
                effective_giver.label("giver"),
                effective_receiver.label("receiver"),
                func.count(Reaction.id).label("n"),
            )
            .select_from(Reaction)
            .join(Message, Reaction.message_id == Message.id)
            .join(Author, Message.user_session_id == Author.session_id)
            .join(Reactor, Reaction.user_session_id == Reactor.session_id)
            .outerjoin(reactor_alias, reactor_alias.c.session_id == Reaction.user_session_id)
            .outerjoin(ReceiverIdentity, Message.imported_identity_id == ReceiverIdentity.id)
            .outerjoin(ReceiverLinkedUser, ReceiverIdentity.linked_user_id == ReceiverLinkedUser.id)
            .where(and_(*conds))
            .group_by("giver", "receiver")
            .order_by(desc("n"))
        )).fetchall()

        # Collect top participants by total reaction volume
        giver_totals: dict[str, int] = {}
        recv_totals: dict[str, int] = {}
        cells: dict[tuple, int] = {}
        for r in rows:
            giver_totals[r.giver] = giver_totals.get(r.giver, 0) + r.n
            recv_totals[r.receiver] = recv_totals.get(r.receiver, 0) + r.n
            cells[(r.giver, r.receiver)] = r.n

        top_givers = [g for g, _ in sorted(giver_totals.items(), key=lambda x: -x[1])[:limit]]
        top_receivers = [r for r, _ in sorted(recv_totals.items(), key=lambda x: -x[1])[:limit]]

        matrix = [
            [cells.get((giver, recv), 0) for recv in top_receivers]
            for giver in top_givers
        ]

        return {
            "givers": top_givers,
            "receivers": top_receivers,
            "matrix": matrix,
        }

    # ── Reactions: trends over time ───────────────────────────────────────────

    async def reaction_trends(
        self,
        room_id: UUID,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        group_by: str = "month",
        top_n: int = 8,
    ) -> dict:
        date_from = _naive_utc(date_from)
        date_to = _naive_utc(date_to)
        top_n = min(top_n, MAX_REACTIONS)
        await _disable_parallel_query(self.db)
        from sqlalchemy import and_

        conds = [Message.room_id == room_id, Message.is_deleted.is_(False)]
        if date_from:
            conds.append(Reaction.created_at >= date_from)
        if date_to:
            conds.append(Reaction.created_at < date_to)

        trunc = _date_trunc_expr(group_by, Reaction.created_at)

        rows = (await self.db.execute(
            select(
                trunc.label("bucket"),
                Reaction.emoji,
                func.count(Reaction.id).label("n"),
            )
            .select_from(Reaction)
            .join(Message, Reaction.message_id == Message.id)
            .where(and_(*conds))
            .group_by("bucket", Reaction.emoji)
            .order_by("bucket", desc("n"))
        )).fetchall()

        # Find top emojis by overall count to limit noise
        emoji_totals: dict[str, int] = {}
        for r in rows:
            emoji_totals[r.emoji] = emoji_totals.get(r.emoji, 0) + r.n
        top_emojis = {e for e, _ in sorted(emoji_totals.items(), key=lambda x: -x[1])[:top_n]}

        # Build series: {emoji: [{date, count}]}
        series: dict[str, dict[str, int]] = {}
        for r in rows:
            if r.emoji not in top_emojis:
                continue
            bucket_key = r.bucket.isoformat() if r.bucket else "unknown"
            series.setdefault(r.emoji, {})[bucket_key] = r.n

        # Convert to list format
        result_series = [
            {
                "emoji": emoji,
                "data": [
                    {"date": date, "count": count}
                    for date, count in sorted(buckets.items())
                ],
            }
            for emoji, buckets in sorted(
                series.items(), key=lambda x: -sum(v for v in x[1].values())
            )
        ]

        return {"group_by": group_by, "series": result_series}

    # ── Reactions: received by sender for a chosen emoji ──────────────────────

    async def reactions_by_sender(
        self,
        room_id: UUID,
        emoji: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        limit: int = 500,
        sort_by: str = "count",
    ) -> dict:
        date_from = _naive_utc(date_from)
        date_to = _naive_utc(date_to)
        limit = min(max(limit, 1), MAX_USERS)
        emoji = emoji.strip() if emoji else None
        sort_by = sort_by if sort_by in {"count", "per_message"} else "count"

        LinkedIdentity = aliased(ImportedIdentity)
        LinkedUser = aliased(User)
        effective_sender = case(
            (and_(Message.is_imported.is_(True), LinkedUser.nickname.is_not(None)), LinkedUser.nickname),
            else_=User.nickname,
        )

        message_conds = [Message.room_id == room_id, Message.is_deleted.is_(False)]
        if date_from:
            message_conds.append(Message.created_at >= date_from)
        if date_to:
            message_conds.append(Message.created_at < date_to)

        msg_counts = (
            select(
                effective_sender.label("sender"),
                func.count(Message.id).label("message_count"),
            )
            .select_from(Message)
            .join(User, Message.user_session_id == User.session_id)
            .outerjoin(LinkedIdentity, Message.imported_identity_id == LinkedIdentity.id)
            .outerjoin(LinkedUser, LinkedIdentity.linked_user_id == LinkedUser.id)
            .where(and_(*message_conds))
            .group_by("sender")
            .subquery()
        )

        reaction_conds = [Message.room_id == room_id, Message.is_deleted.is_(False)]
        if date_from:
            reaction_conds.append(Reaction.created_at >= date_from)
        if date_to:
            reaction_conds.append(Reaction.created_at < date_to)
        if emoji:
            reaction_conds.append(Reaction.emoji == emoji)

        ReactionLinkedIdentity = aliased(ImportedIdentity)
        ReactionLinkedUser = aliased(User)
        ReactionAuthor = aliased(User)
        reaction_sender = case(
            (
                and_(Message.is_imported.is_(True), ReactionLinkedUser.nickname.is_not(None)),
                ReactionLinkedUser.nickname,
            ),
            else_=ReactionAuthor.nickname,
        )

        reaction_counts = (
            select(
                reaction_sender.label("sender"),
                func.count(Reaction.id).label("reaction_count"),
            )
            .select_from(Reaction)
            .join(Message, Reaction.message_id == Message.id)
            .join(ReactionAuthor, Message.user_session_id == ReactionAuthor.session_id)
            .outerjoin(ReactionLinkedIdentity, Message.imported_identity_id == ReactionLinkedIdentity.id)
            .outerjoin(ReactionLinkedUser, ReactionLinkedIdentity.linked_user_id == ReactionLinkedUser.id)
            .where(and_(*reaction_conds))
            .group_by("sender")
            .subquery()
        )

        rows = (await self.db.execute(
            select(
                msg_counts.c.sender,
                msg_counts.c.message_count,
                func.coalesce(reaction_counts.c.reaction_count, 0).label("reaction_count"),
            )
            .select_from(msg_counts)
            .outerjoin(reaction_counts, reaction_counts.c.sender == msg_counts.c.sender)
            .order_by(msg_counts.c.sender)
        )).fetchall()

        senders = []
        for row in rows:
            message_count = int(row.message_count or 0)
            reaction_count = int(row.reaction_count or 0)
            senders.append({
                "sender_nickname": row.sender or "Unknown",
                "message_count": message_count,
                "reaction_count": reaction_count,
                "reactions_per_message": round(reaction_count / message_count, 4) if message_count else 0,
            })

        if sort_by == "per_message":
            senders.sort(
                key=lambda row: (row["reactions_per_message"], row["reaction_count"], row["message_count"]),
                reverse=True,
            )
        else:
            senders.sort(
                key=lambda row: (row["reaction_count"], row["reactions_per_message"], row["message_count"]),
                reverse=True,
            )

        return {"emoji": emoji, "sort_by": sort_by, "senders": senders[:limit]}

    # ── Top reacted messages ──────────────────────────────────────────────────

    async def top_reacted_messages(
        self,
        room_id: UUID,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        sender: Optional[str] = None,
        limit: int = 10,
        offset: int = 0,
        images_only: bool = False,
        ignore_thumb_reactions: bool = False,
    ) -> dict:
        date_from = _naive_utc(date_from)
        date_to = _naive_utc(date_to)
        limit = min(max(limit, 1), MAX_MESSAGES)
        offset = max(offset, 0)
        sender = sender.strip() if sender else None

        conds = [Message.room_id == room_id, Message.is_deleted.is_(False)]
        if date_from:
            conds.append(Message.created_at >= date_from)
        if date_to:
            conds.append(Message.created_at < date_to)

        LinkedIdentity = aliased(ImportedIdentity)
        LinkedUser = aliased(User)
        effective_sender = case(
            (and_(Message.is_imported.is_(True), LinkedUser.nickname.is_not(None)), LinkedUser.nickname),
            else_=User.nickname,
        )

        image_photo = (
            select(
                Photo.message_id.label("message_id"),
                func.min(Photo.filename).label("filename"),
                func.min(Photo.thumbnail_filename).label("thumbnail_filename"),
                func.min(Photo.original_filename).label("original_filename"),
            )
            .where(
                Photo.deleted_at.is_(None),
                Photo.content_type != "image/gif",
                Photo.message_id.is_not(None),
            )
            .group_by(Photo.message_id)
            .subquery()
        )

        sender_conds = list(conds)
        if images_only:
            sender_conds.append(image_photo.c.filename.is_not(None))
        if ignore_thumb_reactions:
            sender_conds.append(Reaction.emoji.notin_(THUMB_REACTIONS))

        sender_rows = (await self.db.execute(
            select(effective_sender.label("sender"))
            .select_from(Message)
            .join(User, Message.user_session_id == User.session_id)
            .outerjoin(LinkedIdentity, Message.imported_identity_id == LinkedIdentity.id)
            .outerjoin(LinkedUser, LinkedIdentity.linked_user_id == LinkedUser.id)
            .outerjoin(image_photo, image_photo.c.message_id == Message.id)
            .join(Reaction, Reaction.message_id == Message.id)
            .where(and_(*sender_conds))
            .group_by("sender")
            .order_by("sender")
        )).fetchall()
        senders = [r.sender for r in sender_rows if r.sender]

        filtered_conds = list(conds)
        if sender:
            filtered_conds.append(effective_sender == sender)
        if images_only:
            filtered_conds.append(image_photo.c.filename.is_not(None))
        if ignore_thumb_reactions:
            filtered_conds.append(Reaction.emoji.notin_(THUMB_REACTIONS))

        rows = (await self.db.execute(
            select(
                Message,
                User,
                LinkedUser,
                image_photo.c.filename,
                image_photo.c.thumbnail_filename,
                image_photo.c.original_filename,
                func.count(Reaction.id).label("reaction_count"),
                func.count(func.distinct(Reaction.emoji)).label("unique_emojis"),
            )
            .join(User, Message.user_session_id == User.session_id)
            .outerjoin(LinkedIdentity, Message.imported_identity_id == LinkedIdentity.id)
            .outerjoin(LinkedUser, LinkedIdentity.linked_user_id == LinkedUser.id)
            .outerjoin(image_photo, image_photo.c.message_id == Message.id)
            .outerjoin(Reaction, Reaction.message_id == Message.id)
            .where(and_(*filtered_conds))
            .group_by(
                Message.id,
                User.session_id,
                LinkedUser.session_id,
                image_photo.c.filename,
                image_photo.c.thumbnail_filename,
                image_photo.c.original_filename,
            )
            .having(func.count(Reaction.id) > 0)
            .order_by(desc("reaction_count"), desc(Message.created_at), desc(Message.id))
            .offset(offset)
            .limit(limit + 1)
        )).fetchall()
        has_more = len(rows) > limit
        rows = rows[:limit]

        message_ids = [row[0].id for row in rows]
        emoji_map: dict[int, list[dict]] = {}
        if message_ids:
            reaction_rows = (await self.db.execute(
                select(
                    Reaction.message_id,
                    Reaction.emoji,
                    func.count(Reaction.id).label("n"),
                )
                .where(
                    Reaction.message_id.in_(message_ids),
                    Reaction.emoji.notin_(THUMB_REACTIONS) if ignore_thumb_reactions else text("true"),
                )
                .group_by(Reaction.message_id, Reaction.emoji)
                .order_by(Reaction.message_id, desc("n"))
            )).fetchall()
            for r in reaction_rows:
                emoji_map.setdefault(r.message_id, []).append({
                    "emoji": r.emoji,
                    "count": r.n,
                })

        messages = []
        for row in rows:
            msg, user, linked_user, image_filename, image_thumb, image_original, reaction_count, unique_emojis = row
            effective = linked_user if (msg.is_imported and linked_user) else user
            content = msg.content or ""
            image_url = f"/uploads/photos/{image_filename}" if image_filename else None
            image_thumbnail_url = (
                f"/uploads/photos/{image_thumb}"
                if image_thumb
                else image_url
            )
            messages.append({
                "message_id": msg.id,
                "content": content[:300] + ("…" if len(content) > 300 else ""),
                "created_at": msg.created_at.isoformat() if msg.created_at else None,
                "sender_nickname": effective.nickname if effective else "Unknown",
                "sender_avatar_url": getattr(effective, "avatar_url", None) if effective else None,
                "sender_avatar_emoji": getattr(effective, "avatar_emoji", None) if effective else None,
                "image_url": image_url,
                "image_thumbnail_url": image_thumbnail_url,
                "image_label": image_original or image_filename,
                "reaction_count": reaction_count,
                "unique_emojis": unique_emojis,
                "reactions": emoji_map.get(msg.id, []),
            })

        return {
            "messages": messages,
            "senders": senders,
            "sender": sender,
            "offset": offset,
            "limit": limit,
            "has_more": has_more,
        }

    async def top_reacted_images(
        self,
        room_id: UUID,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        sender: Optional[str] = None,
        limit: int = 10,
    ) -> dict:
        return await self.top_reacted_messages(
            room_id=room_id,
            date_from=date_from,
            date_to=date_to,
            sender=sender,
            limit=limit,
            images_only=True,
        )

    # ── Overview totals (enhanced, room-scoped) ───────────────────────────────

    async def overview(self, room_id: UUID) -> dict:
        from app.models.planning import Idea, Poll, Reminder, Comment, Group
        from sqlalchemy import and_

        group_row = (await self.db.execute(
            select(func.min(Message.id))  # just to get db, we actually query group below
        )).scalar()

        # We need the group — same pattern as existing stats endpoint
        from app.models.planning import DEFAULT_GROUP_SLUG
        group_result = await self.db.execute(
            select(Group).where(Group.slug == DEFAULT_GROUP_SLUG).limit(1)
        )
        group = group_result.scalar_one_or_none()
        if group is None:
            group_result = await self.db.execute(select(Group).limit(1))
            group = group_result.scalar_one_or_none()

        async def count(stmt):
            return (await self.db.execute(stmt)).scalar_one() or 0

        msg_count = await count(
            select(func.count(Message.id))
            .where(Message.is_deleted.is_(False), Message.room_id == room_id)
        )
        first_message_at = (await self.db.execute(
            select(func.min(Message.created_at))
            .where(Message.is_deleted.is_(False), Message.room_id == room_id)
        )).scalar_one_or_none()
        if first_message_at and first_message_at.tzinfo is not None:
            first_message_at = first_message_at.astimezone(timezone.utc).replace(tzinfo=None)
        now = datetime.utcnow()
        uptime_seconds = max(int((now - first_message_at).total_seconds()), 0) if first_message_at else 0
        uptime_days = max(uptime_seconds / 86400, 1) if first_message_at else 0
        members_count = await self._room_member_count(room_id)
        imported_members_count = await self._imported_member_count(room_id)
        reaction_count = await count(
            select(func.count(Reaction.id))
            .join(Message, Reaction.message_id == Message.id)
            .where(Message.room_id == room_id, Message.is_deleted.is_(False))
        )
        photo_count = await count(
            select(func.count(Photo.id))
            .where(Photo.room_id == room_id, Photo.deleted_at.is_(None), Photo.content_type != "image/gif")
        )
        gif_count = await count(
            select(func.count(Photo.id))
            .where(Photo.room_id == room_id, Photo.deleted_at.is_(None), Photo.content_type == "image/gif")
        )
        has_audio_files = (await self.db.execute(
            select(func.to_regclass("public.audio_files").is_not(None))
        )).scalar_one()
        voice_note_count = await count(
            select(func.count(AudioFile.id)).where(AudioFile.room_id == room_id)
        ) if has_audio_files else 0

        if group:
            ideas_count = await count(
                select(func.count(Idea.id))
                .where(Idea.group_id == group.id, Idea.room_id == room_id)
            )
            polls_count = await count(
                select(func.count(Poll.id))
                .where(Poll.group_id == group.id, Poll.room_id == room_id)
            )
            reminders_count = await count(
                select(func.count(Reminder.id))
                .where(Reminder.group_id == group.id, Reminder.room_id == room_id)
            )
            comments_count = await count(
                select(func.count(Comment.id)).where(Comment.group_id == group.id)
            )
        else:
            ideas_count = polls_count = reminders_count = comments_count = 0

        return {
            "messages": msg_count,
            "reactions": reaction_count,
            "members": members_count,
            "imported_members": imported_members_count,
            "ideas": ideas_count,
            "polls": polls_count,
            "reminders": reminders_count,
            "comments": comments_count,
            "photos": photo_count,
            "gifs": gif_count,
            "voice_notes": voice_note_count,
            "first_message_at": first_message_at.isoformat() if first_message_at else None,
            "uptime_seconds": uptime_seconds,
            "per_day": {
                "messages": round(msg_count / uptime_days, 2) if uptime_days else 0,
                "photos": round(photo_count / uptime_days, 2) if uptime_days else 0,
                "gifs": round(gif_count / uptime_days, 2) if uptime_days else 0,
                "voice_notes": round(voice_note_count / uptime_days, 2) if uptime_days else 0,
                "reactions": round(reaction_count / uptime_days, 2) if uptime_days else 0,
            },
        }

    # ── Room hub overview (top-bar drilldown) ─────────────────────────────────

    async def room_overview(self, room_id: UUID) -> dict:
        """Compact, room-scoped summary powering the chat Room Overview sheet.

        Returns activity time-window counts, recent photos, weekly top
        contributors, and headline counts. All windows are server-side and
        anchored to UTC `now` so the client never shows loaded-only counts.
        """
        now = datetime.utcnow()
        windows = {
            "past_hour": now - timedelta(hours=1),
            "past_3_hours": now - timedelta(hours=3),
            "today": now - timedelta(hours=24),
            "this_week": now - timedelta(days=7),
        }

        async def msg_count_since(since: datetime) -> int:
            return (await self.db.execute(
                select(func.count(Message.id))
                .where(_msg_base(room_id, date_from=since))
            )).scalar_one() or 0

        activity = {key: await msg_count_since(since) for key, since in windows.items()}

        # Window start timestamps let the client jump to the first message in range.
        activity_windows = {key: since.isoformat() for key, since in windows.items()}

        members_count = await self._room_member_count(room_id)
        imported_members_count = await self._imported_member_count(room_id)
        photo_count = (await self.db.execute(
            select(func.count(Photo.id))
            .where(Photo.room_id == room_id, Photo.deleted_at.is_(None), Photo.content_type != "image/gif")
        )).scalar_one() or 0

        # Recent photos (newest first, real images only — GIFs excluded).
        Uploader = aliased(User)
        photo_rows = (await self.db.execute(
            select(
                Photo.id,
                Photo.filename,
                Photo.thumbnail_filename,
                Photo.original_filename,
                Photo.caption,
                func.coalesce(Photo.taken_at, Photo.created_at).label("at"),
                Uploader.nickname,
            )
            .outerjoin(Uploader, Photo.uploaded_by_session_id == Uploader.session_id)
            .where(
                Photo.room_id == room_id,
                Photo.deleted_at.is_(None),
                Photo.content_type != "image/gif",
            )
            .order_by(desc("at"), desc(Photo.id))
            .limit(12)
        )).fetchall()
        recent_photos = [
            {
                "id": r.id,
                "url": f"/uploads/photos/{r.filename}",
                "thumbnail_url": f"/uploads/photos/{r.thumbnail_filename}" if r.thumbnail_filename else f"/uploads/photos/{r.filename}",
                "caption": r.caption,
                "label": r.original_filename or r.filename,
                "uploaded_by": r.nickname,
                "created_at": r.at.isoformat() if r.at else None,
            }
            for r in photo_rows
        ]

        # Weekly top contributors by message count (identity-aware nickname).
        week_start = windows["this_week"]
        LinkedIdentity = aliased(ImportedIdentity)
        LinkedUser = aliased(User)
        effective_author = case(
            (and_(Message.is_imported.is_(True), LinkedUser.nickname.is_not(None)), LinkedUser.nickname),
            else_=User.nickname,
        )
        effective_emoji = case(
            (and_(Message.is_imported.is_(True), LinkedUser.avatar_emoji.is_not(None)), LinkedUser.avatar_emoji),
            else_=User.avatar_emoji,
        )
        effective_url = case(
            (and_(Message.is_imported.is_(True), LinkedUser.avatar_url.is_not(None)), LinkedUser.avatar_url),
            else_=User.avatar_url,
        )
        contributor_rows = (await self.db.execute(
            select(
                effective_author.label("nickname"),
                effective_emoji.label("avatar_emoji"),
                effective_url.label("avatar_url"),
                func.count(Message.id).label("message_count"),
            )
            .select_from(Message)
            .join(User, Message.user_session_id == User.session_id)
            .outerjoin(LinkedIdentity, Message.imported_identity_id == LinkedIdentity.id)
            .outerjoin(LinkedUser, LinkedIdentity.linked_user_id == LinkedUser.id)
            .where(_msg_base(room_id, date_from=week_start), effective_author.is_not(None))
            .group_by(effective_author, effective_emoji, effective_url)
            .order_by(desc("message_count"))
            .limit(8)
        )).fetchall()
        top_contributors = [
            {
                "nickname": r.nickname,
                "avatar_emoji": r.avatar_emoji,
                "avatar_url": r.avatar_url,
                "message_count": r.message_count,
            }
            for r in contributor_rows
        ]

        return {
            "activity": activity,
            "activity_windows": activity_windows,
            "members": members_count,
            "imported_members": imported_members_count,
            "photos": photo_count,
            "recent_photos": recent_photos,
            "top_contributors": top_contributors,
        }
