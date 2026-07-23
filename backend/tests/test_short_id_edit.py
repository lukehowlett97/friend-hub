"""Tests for the editable reference tag (hub_item.short_id):
- validation rejects garbage
- uniqueness check
- the chat reference regex still matches default-style refs AND custom tags
"""
import os
import unittest

os.environ["DEBUG"] = "false"
os.environ.setdefault("DATABASE_PASSWORD", "changeme")

from app.api.v1.router import _clean_short_id  # noqa: E402
from app.domains.hub_items.references import find_hub_item_references  # noqa: E402
from fastapi import HTTPException  # noqa: E402


class TestCleanShortId(unittest.TestCase):
    def test_default_form_passes(self):
        self.assertEqual(_clean_short_id("#P-8"), "#P-8")
        self.assertEqual(_clean_short_id("P-8"), "#P-8")  # auto-prefix

    def test_custom_form_passes(self):
        self.assertEqual(_clean_short_id("#mike-rename"), "#mike-rename")
        self.assertEqual(_clean_short_id("council_2026"), "#council_2026")

    def test_whitespace_trimmed(self):
        self.assertEqual(_clean_short_id("  #foo  "), "#foo")

    def test_must_start_with_letter(self):
        with self.assertRaises(HTTPException) as ctx:
            _clean_short_id("#1-bad")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_disallows_spaces(self):
        with self.assertRaises(HTTPException):
            _clean_short_id("#mike rename")

    def test_disallows_punctuation(self):
        with self.assertRaises(HTTPException):
            _clean_short_id("#mike!")
        with self.assertRaises(HTTPException):
            _clean_short_id("#mike@rename")

    def test_length_bounds(self):
        # Single char after # is too short
        with self.assertRaises(HTTPException):
            _clean_short_id("#x")
        # 19 chars after # is the limit (column is String(20))
        self.assertEqual(_clean_short_id("#" + "a" * 19), "#" + "a" * 19)
        with self.assertRaises(HTTPException):
            _clean_short_id("#" + "a" * 20)

    def test_none_rejected(self):
        with self.assertRaises(HTTPException):
            _clean_short_id(None)


class TestReferenceRegex(unittest.TestCase):
    def test_default_style_still_matches(self):
        refs = find_hub_item_references("Check #P-8 and #E-2 today.")
        short_ids = [r["short_id"] for r in refs]
        self.assertEqual(short_ids, ["#P-8", "#E-2"])
        self.assertEqual(refs[0]["type"], "poll")
        self.assertEqual(refs[1]["type"], "event")

    def test_custom_short_id_matches(self):
        refs = find_hub_item_references("Vote on #mike-rename now")
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0]["short_id"], "#mike-rename")
        self.assertIsNone(refs[0]["type"])  # caller resolves type via DB

    def test_bare_hashtag_rejected(self):
        # "#1" (digit start) should NOT be a reference — would be a casual hashtag.
        refs = find_hub_item_references("Topic #1 then #2")
        self.assertEqual(refs, [])

    def test_mixed_default_and_custom(self):
        refs = find_hub_item_references("Compare #P-8 with #council-2026")
        self.assertEqual([r["short_id"] for r in refs], ["#P-8", "#council-2026"])
        self.assertEqual(refs[0]["type"], "poll")
        self.assertIsNone(refs[1]["type"])


if __name__ == "__main__":
    unittest.main()
