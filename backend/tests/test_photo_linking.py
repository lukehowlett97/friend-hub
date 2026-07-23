import asyncio
import os
import unittest

os.environ["DEBUG"] = "false"
os.environ.setdefault("DATABASE_PASSWORD", "changeme")

from app.domains.photos.linking import backfill_photo_message_ids, parse_photo_filenames


class FakeResult:
    def __init__(self, scalar=None, rows=None):
        self._scalar = scalar
        self._rows = rows or []

    def scalar_one(self):
        return self._scalar

    def fetchall(self):
        return self._rows


class FakeSession:
    def __init__(self, results):
        self.results = list(results)
        self.executed = []
        self.committed = False

    async def execute(self, statement, params=None):
        self.executed.append((statement, params))
        return self.results.pop(0) if self.results else FakeResult()

    async def commit(self):
        self.committed = True


class TestParsePhotoFilenames(unittest.TestCase):
    def test_extracts_filenames_from_message_content(self):
        content = "Photo: holiday.jpg\n/uploads/photos/abc123.jpg\n/uploads/photos/def456.gif"
        self.assertEqual(parse_photo_filenames(content), ["abc123.jpg", "def456.gif"])

    def test_ignores_unrelated_lines(self):
        self.assertEqual(parse_photo_filenames("just a chat message"), [])
        self.assertEqual(parse_photo_filenames("see /uploads/videos/clip.mp4"), [])


class TestBackfillPhotoMessageIds(unittest.TestCase):
    def _run(self, coro):
        return asyncio.run(coro)

    def test_noop_when_no_photos_missing_link(self):
        db = FakeSession([FakeResult(scalar=0)])
        updated = self._run(backfill_photo_message_ids(db))
        self.assertEqual(updated, 0)
        self.assertEqual(len(db.executed), 1)
        self.assertFalse(db.committed)

    def test_links_photos_referenced_by_messages(self):
        db = FakeSession([
            FakeResult(scalar=2),
            FakeResult(rows=[(10, "Photo: a.jpg\n/uploads/photos/abc.jpg")]),
            FakeResult(rows=[(1, "abc.jpg"), (2, "orphan.jpg")]),
        ])
        updated = self._run(backfill_photo_message_ids(db))
        self.assertEqual(updated, 1)
        self.assertTrue(db.committed)
        _, params = db.executed[-1]
        self.assertEqual(params, [{"id": 1, "message_id": 10}])

    def test_noop_when_no_messages_reference_photos(self):
        db = FakeSession([
            FakeResult(scalar=5),
            FakeResult(rows=[(10, "no photo links here")]),
        ])
        updated = self._run(backfill_photo_message_ids(db))
        self.assertEqual(updated, 0)
        self.assertFalse(db.committed)


if __name__ == "__main__":
    unittest.main()
