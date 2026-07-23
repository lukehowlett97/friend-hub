"""Tests for the Group Lore phase 1 (search + phrase stats)."""
import asyncio
import os
import types
import unittest
import uuid
from datetime import datetime, timedelta

os.environ["DEBUG"] = "false"

from app.domains.group_lore.service import GroupLoreService, _build_snippet


def _msg(*, id, content, user_session_id, created_at, user_id=None, is_deleted=False, is_imported=False):
    m = types.SimpleNamespace()
    m.id = id
    m.content = content
    m.user_session_id = user_session_id
    m.user_id = user_id
    m.created_at = created_at
    m.is_deleted = is_deleted
    m.is_imported = is_imported
    return m


def _user(*, session_id, nickname, username=None, avatar_url=None, avatar_emoji=None):
    u = types.SimpleNamespace()
    u.session_id = session_id
    u.nickname = nickname
    u.username = username
    u.avatar_url = avatar_url
    u.avatar_emoji = avatar_emoji
    return u


class FakeRowsResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def scalar(self):
        return len(self._rows)


class FakeDb:
    """Pretends to be an AsyncSession.

    The service issues two queries — a count and a row fetch (or one row
    fetch for stats). We hand back a deterministic, in-memory result derived
    from the seeded rows so tests stay hermetic and don't need Postgres.
    """

    def __init__(self, rows):
        # rows: list of (Message, User) tuples
        self.rows = rows
        self._call_idx = 0

    async def execute(self, stmt):
        # Inspect the compiled SQL to decide if this is the count or the rows query.
        try:
            sql = str(stmt).lower()
        except Exception:
            sql = ""

        # We can't reliably parse predicates from SQLAlchemy expressions here,
        # so the FakeDb is paired with pre-filtered rows: callers seed only the
        # rows that match the query they're about to issue.
        if "count(" in sql:
            return FakeRowsResult(self.rows)
        return FakeRowsResult(self.rows)


SID_A = uuid.uuid4()
SID_B = uuid.uuid4()
SID_C = uuid.uuid4()


def _matching(rows, needle):
    nl = needle.lower()
    return [(m, u) for (m, u) in rows if (not m.is_deleted) and nl in (m.content or "").lower()]


class TestGroupLoreSearch(unittest.TestCase):
    def setUp(self):
        users = {
            SID_A: _user(session_id=SID_A, nickname="Luke", username="luke"),
            SID_B: _user(session_id=SID_B, nickname="Ryan", username="ryan"),
            SID_C: _user(session_id=SID_C, nickname="Tom",  username="tom"),
        }
        now = datetime(2026, 5, 12, 12, 0, 0)
        self.rows = [
            (_msg(id=1, content="Benidorm is going to ruin us",
                  user_session_id=SID_A, created_at=now - timedelta(days=1)), users[SID_A]),
            (_msg(id=2, content="benidorm benidorm benidorm",
                  user_session_id=SID_B, created_at=now - timedelta(days=2)), users[SID_B]),
            (_msg(id=3, content="totally unrelated message",
                  user_session_id=SID_C, created_at=now - timedelta(days=3)), users[SID_C]),
            (_msg(id=4, content="we should book benidorm flights",
                  user_session_id=SID_A, created_at=now - timedelta(days=4)), users[SID_A]),
            (_msg(id=5, content="[message deleted]",
                  user_session_id=SID_A, created_at=now - timedelta(days=5),
                  is_deleted=True), users[SID_A]),
        ]

    def test_case_insensitive_match(self):
        matched = _matching(self.rows, "benidorm")
        db = FakeDb(matched)
        service = GroupLoreService(db)
        result = asyncio.run(service.search_messages("Benidorm", limit=10, offset=0))

        self.assertEqual(result["query"], "Benidorm")
        # 3 non-deleted messages contain the phrase (case-insensitive).
        self.assertEqual(len(result["results"]), 3)
        self.assertEqual(result["total"], 3)
        # Snippet + match metadata is present for highlighting.
        first = result["results"][0]
        self.assertIn("snippet", first)
        self.assertGreaterEqual(first["match_start"], 0)
        self.assertEqual(first["match_length"], len("Benidorm"))
        self.assertIn("sender_nickname", first)

    def test_empty_results_for_no_match(self):
        matched = _matching(self.rows, "kangaroo")
        db = FakeDb(matched)
        service = GroupLoreService(db)
        result = asyncio.run(service.search_messages("kangaroo"))
        self.assertEqual(result["results"], [])
        self.assertEqual(result["total"], 0)

    def test_blank_query_returns_all_messages(self):
        # Blank query is "browse the archive": with no phrase to filter on
        # we still want every non-deleted message back, optionally narrowed
        # by date filters.
        db = FakeDb([(m, u) for (m, u) in self.rows if not m.is_deleted])
        service = GroupLoreService(db)
        for q in ["", "   ", None]:
            result = asyncio.run(service.search_messages(q))
            # All 4 non-deleted messages flow through.
            self.assertEqual(result["total"], 4)
            self.assertEqual(len(result["results"]), 4)
            # No highlight when there is no query.
            first = result["results"][0]
            self.assertEqual(first["match_length"], 0)
            self.assertEqual(first["match_start"], 0)
            self.assertEqual(first["match_count"], 0)
            self.assertTrue(first["snippet"])

    def test_limit_is_applied(self):
        # FakeDb returns whatever rows it's seeded with; the service should
        # still report total separately and honour the requested limit at the
        # response shape level (which it leaves to the DB LIMIT clause). Here
        # we check the clamping of out-of-range limits.
        matched = _matching(self.rows, "benidorm")
        db = FakeDb(matched)
        service = GroupLoreService(db)
        result = asyncio.run(service.search_messages("benidorm", limit=9999))
        self.assertLessEqual(result["limit"], 100)
        result_zero = asyncio.run(service.search_messages("benidorm", limit=0))
        self.assertGreaterEqual(result_zero["limit"], 1)


class TestGroupLoreStats(unittest.TestCase):
    def test_counts_occurrences_by_sender(self):
        users = {
            SID_A: _user(session_id=SID_A, nickname="Luke"),
            SID_B: _user(session_id=SID_B, nickname="Ryan"),
        }
        now = datetime(2026, 5, 12, 12, 0, 0)
        rows = [
            (_msg(id=1, content="pub pub pub",
                  user_session_id=SID_A, created_at=now), users[SID_A]),
            (_msg(id=2, content="back to the pub later",
                  user_session_id=SID_A, created_at=now), users[SID_A]),
            (_msg(id=3, content="Pub crawl?",
                  user_session_id=SID_B, created_at=now), users[SID_B]),
        ]
        matched = _matching(rows, "pub")
        db = FakeDb(matched)
        service = GroupLoreService(db)

        result = asyncio.run(service.phrase_stats("pub"))

        self.assertEqual(result["total_occurrences"], 5)  # 3 + 1 + 1
        self.assertEqual(result["matching_messages"], 3)
        self.assertEqual(result["people"], 2)
        # Highest first.
        self.assertEqual(result["results"][0]["sender_nickname"], "Luke")
        self.assertEqual(result["results"][0]["count"], 4)
        self.assertEqual(result["results"][1]["sender_nickname"], "Ryan")
        self.assertEqual(result["results"][1]["count"], 1)

    def test_blank_query_returns_empty_stats(self):
        db = FakeDb([])
        service = GroupLoreService(db)
        for q in ["", "   ", None]:
            result = asyncio.run(service.phrase_stats(q))
            self.assertEqual(result["total_occurrences"], 0)
            self.assertEqual(result["matching_messages"], 0)
            self.assertEqual(result["people"], 0)
            self.assertEqual(result["results"], [])


class TestSnippetBuilder(unittest.TestCase):
    def test_match_at_start_no_leading_ellipsis(self):
        content = "Benidorm is going to ruin us this summer if we're not careful"
        snippet, offset = _build_snippet(content, 0, len("Benidorm"))
        self.assertFalse(snippet.startswith("…"))
        self.assertEqual(offset, 0)
        self.assertIn("Benidorm", snippet)

    def test_match_at_end_no_trailing_ellipsis(self):
        content = "Honestly I think the best plan is just to skip benidorm"
        match_start = content.lower().find("benidorm")
        snippet, offset = _build_snippet(content, match_start, len("benidorm"))
        self.assertFalse(snippet.endswith("…"))
        self.assertEqual(snippet[offset:offset + len("benidorm")].lower(), "benidorm")

    def test_match_in_middle_has_both_ellipses(self):
        before = "x" * 200
        after = "y" * 200
        content = f"{before} benidorm {after}"
        match_start = content.lower().find("benidorm")
        snippet, offset = _build_snippet(content, match_start, len("benidorm"))
        self.assertTrue(snippet.startswith("…"))
        self.assertTrue(snippet.endswith("…"))
        self.assertEqual(snippet[offset:offset + len("benidorm")], "benidorm")

    def test_empty_content_safe(self):
        snippet, offset = _build_snippet("", 0, 3)
        self.assertEqual(snippet, "")
        self.assertEqual(offset, 0)

    def test_short_message_returns_full_content(self):
        content = "lol"
        snippet, offset = _build_snippet(content, 0, 3)
        self.assertEqual(snippet, "lol")
        self.assertEqual(offset, 0)


class TestDateFilters(unittest.TestCase):
    def _seed(self):
        users = {SID_A: _user(session_id=SID_A, nickname="Luke")}
        now = datetime(2026, 5, 12, 12, 0, 0)
        rows = [
            (_msg(id=1, content="benidorm now",
                  user_session_id=SID_A, created_at=now), users[SID_A]),
            (_msg(id=2, content="benidorm last week",
                  user_session_id=SID_A, created_at=now - timedelta(days=7)), users[SID_A]),
            (_msg(id=3, content="benidorm last year",
                  user_session_id=SID_A, created_at=now - timedelta(days=365)), users[SID_A]),
        ]
        return rows, now

    def _filter(self, rows, needle, date_from=None, date_to=None):
        nl = needle.lower()
        out = []
        for m, u in rows:
            if m.is_deleted: continue
            if nl not in (m.content or "").lower(): continue
            if date_from is not None and m.created_at < date_from: continue
            if date_to is not None and m.created_at >= date_to: continue
            out.append((m, u))
        return out

    def test_search_respects_date_from(self):
        rows, now = self._seed()
        date_from = now - timedelta(days=30)
        db = FakeDb(self._filter(rows, "benidorm", date_from=date_from))
        service = GroupLoreService(db)
        result = asyncio.run(service.search_messages("benidorm", date_from=date_from))
        ids = sorted(r["message_id"] for r in result["results"])
        self.assertEqual(ids, [1, 2])
        self.assertEqual(result["date_from"], date_from.isoformat())

    def test_search_respects_date_to_exclusive(self):
        rows, now = self._seed()
        # ``date_to`` is exclusive — a boundary message must not appear.
        date_to = now
        db = FakeDb(self._filter(rows, "benidorm", date_to=date_to))
        service = GroupLoreService(db)
        result = asyncio.run(service.search_messages("benidorm", date_to=date_to))
        ids = sorted(r["message_id"] for r in result["results"])
        self.assertEqual(ids, [2, 3])

    def test_stats_respects_date_range(self):
        rows, now = self._seed()
        date_from = now - timedelta(days=30)
        date_to = now + timedelta(days=1)
        db = FakeDb(self._filter(rows, "benidorm", date_from=date_from, date_to=date_to))
        service = GroupLoreService(db)
        result = asyncio.run(service.phrase_stats(
            "benidorm", date_from=date_from, date_to=date_to,
        ))
        self.assertEqual(result["matching_messages"], 2)
        self.assertEqual(result["total_occurrences"], 2)

    def test_blank_query_with_dates_still_safe(self):
        db = FakeDb([])
        service = GroupLoreService(db)
        now = datetime(2026, 5, 12, 12, 0, 0)
        result = asyncio.run(service.search_messages(
            "", date_from=now - timedelta(days=1), date_to=now,
        ))
        self.assertEqual(result["results"], [])
        self.assertEqual(result["total"], 0)
        self.assertIsNotNone(result["date_from"])
        self.assertIsNotNone(result["date_to"])


class TestRepeatedPhraseInOneMessage(unittest.TestCase):
    def test_match_count_reflects_repeats(self):
        users = {SID_A: _user(session_id=SID_A, nickname="Luke")}
        now = datetime(2026, 5, 12, 12, 0, 0)
        rows = [
            (_msg(id=10, content="lol lol lol that's hilarious lol",
                  user_session_id=SID_A, created_at=now), users[SID_A]),
        ]
        db = FakeDb(rows)
        service = GroupLoreService(db)
        result = asyncio.run(service.search_messages("lol"))
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(result["results"][0]["match_count"], 4)


if __name__ == "__main__":
    unittest.main()
