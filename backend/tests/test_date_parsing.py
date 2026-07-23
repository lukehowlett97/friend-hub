"""Tests for explicit-date parsing used by /search, /summarise, and /catchup."""
import os
import unittest
from datetime import datetime, timedelta, timezone

os.environ.setdefault("DEBUG", "false")

from app.domains.ai.date_parsing import extract_date_query, parse_explicit_date
from app.domains.ai.hub_agent_service import _parse_summarise_window

NOW = datetime(2026, 6, 11, 14, 0, 0)


class TestParseExplicitDate(unittest.TestCase):
    def _assert_day(self, text, year, month, day):
        match = parse_explicit_date(text, NOW)
        self.assertIsNotNone(match, text)
        self.assertEqual(match.day_start, datetime(year, month, day), text)
        self.assertEqual(match.day_end - match.day_start, timedelta(days=1))

    def test_month_first_formats(self):
        for text in (
            "June 1st 2025",
            "june 1 2025",
            "June 1, 2025",
            "on June 1st 2025",
            "jun 1 2025",
        ):
            self._assert_day(text, 2025, 6, 1)

    def test_day_first_formats(self):
        for text in ("1 June 2025", "1st of June 2025", "1st june 2025", "on 21st December 2025"):
            match = parse_explicit_date(text, NOW)
            self.assertIsNotNone(match, text)

    def test_iso_format(self):
        self._assert_day("2025-06-01", 2025, 6, 1)

    def test_numeric_is_day_first(self):
        self._assert_day("01/06/2025", 2025, 6, 1)
        self._assert_day("1/6/25", 2025, 6, 1)

    def test_yearless_uses_most_recent_past_occurrence(self):
        # NOW is 11 Jun 2026: "june 1" already happened this year
        self._assert_day("june 1", 2026, 6, 1)
        # "december 25" hasn't happened yet in 2026 → last year
        self._assert_day("december 25", 2025, 12, 25)

    def test_invalid_dates_return_none(self):
        self.assertIsNone(parse_explicit_date("june 31 2025", NOW))
        self.assertIsNone(parse_explicit_date("2025-02-30", NOW))

    def test_no_date_returns_none(self):
        for text in ("when did we talk about camping?", "", "next tuesday vibes", "1 of them"):
            self.assertIsNone(parse_explicit_date(text, NOW), text)

    def test_tz_aware_now_is_normalised(self):
        aware = NOW.replace(tzinfo=timezone.utc)
        match = parse_explicit_date("june 1", aware)
        self.assertEqual(match.day_start, datetime(2026, 6, 1))

    def test_label(self):
        self.assertEqual(parse_explicit_date("2025-06-01", NOW).label, "1 Jun 2025")


class TestExtractDateQuery(unittest.TestCase):
    def test_remainder_strips_date_phrase(self):
        match, remainder = extract_date_query("what happened on june 1st 2025?", NOW)
        self.assertIsNotNone(match)
        self.assertEqual(remainder, "what happened")

    def test_hybrid_keeps_topic(self):
        match, remainder = extract_date_query("camping on june 1st 2025", NOW)
        self.assertIsNotNone(match)
        self.assertEqual(remainder, "camping")

    def test_no_date_passthrough(self):
        match, remainder = extract_date_query("when did we talk about camping?", NOW)
        self.assertIsNone(match)
        self.assertEqual(remainder, "when did we talk about camping?")


class TestSummariseWindowIntegration(unittest.TestCase):
    def test_explicit_date_yields_day_window(self):
        now = datetime(2026, 6, 11, 14, 0, tzinfo=timezone.utc)
        start, end = _parse_summarise_window("june 1st 2025", now)
        self.assertEqual((start.year, start.month, start.day, start.hour), (2025, 6, 1, 0))
        self.assertEqual((end - start), timedelta(days=1))

    def test_since_date_runs_to_now(self):
        now = datetime(2026, 6, 11, 14, 0, tzinfo=timezone.utc)
        start, end = _parse_summarise_window("since 1 june 2026", now)
        self.assertEqual((start.month, start.day), (6, 1))
        self.assertEqual(end, now)

    def test_unrecognised_still_falls_back(self):
        now = datetime(2026, 6, 11, 14, 0, tzinfo=timezone.utc)
        start, end = _parse_summarise_window("next tuesday or something", now)
        self.assertAlmostEqual((end - start).total_seconds(), 7200, delta=5)


if __name__ == "__main__":
    unittest.main()
