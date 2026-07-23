"""Explicit-date detection for chat queries ("what happened on June 1st 2025?").

Pure functions, no DB. All windows are naive UTC midnight-to-midnight —
the app has no per-room/user timezone concept yet, so "a day" means a UTC
day everywhere (same convention as /summarise's today/yesterday handling).
"""
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

MONTHS = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}

_MONTH_RE = "|".join(sorted(MONTHS, key=len, reverse=True))
_ORDINAL = r"(?:st|nd|rd|th)?"

# "June 1st 2025", "june 1, 2025", "Jun 1"
_MONTH_FIRST_RE = re.compile(
    rf"\b(?:on\s+)?({_MONTH_RE})\s+(\d{{1,2}}){_ORDINAL}(?:\s*,?\s*(\d{{4}}))?\b",
    re.IGNORECASE,
)
# "1 June 2025", "1st of June", "21st june"
_DAY_FIRST_RE = re.compile(
    rf"\b(?:on\s+)?(\d{{1,2}}){_ORDINAL}\s+(?:of\s+)?({_MONTH_RE})(?:\s*,?\s*(\d{{4}}))?\b",
    re.IGNORECASE,
)
# ISO "2025-06-01"
_ISO_RE = re.compile(r"\b(?:on\s+)?(\d{4})-(\d{2})-(\d{2})\b")
# Numeric "01/06/2025" or "1/6/25" — parsed day-first (UK convention)
_NUMERIC_RE = re.compile(r"\b(?:on\s+)?(\d{1,2})/(\d{1,2})/(\d{2,4})\b")


@dataclass(frozen=True)
class DateMatch:
    day_start: datetime  # naive UTC midnight
    day_end: datetime    # day_start + 1 day
    matched_text: str
    label: str           # e.g. "1 Jun 2025"


def _naive_utc(now: datetime) -> datetime:
    if now.tzinfo is not None:
        return now.astimezone(timezone.utc).replace(tzinfo=None)
    return now


def _build_match(year: int, month: int, day: int, matched_text: str) -> DateMatch | None:
    try:
        day_start = datetime(year, month, day)
    except ValueError:
        return None  # e.g. June 31st
    return DateMatch(
        day_start=day_start,
        day_end=day_start + timedelta(days=1),
        matched_text=matched_text,
        label=f"{day_start.day} {day_start:%b %Y}",
    )


def _infer_year(month: int, day: int, now: datetime) -> int:
    """Year-less dates mean the most recent occurrence not in the future."""
    try:
        this_year = datetime(now.year, month, day)
    except ValueError:
        return now.year
    return now.year if this_year <= now else now.year - 1


def parse_explicit_date(text: str, now: datetime) -> DateMatch | None:
    """Find the first explicit calendar date in text; None if there isn't one."""
    if not text:
        return None
    now = _naive_utc(now)

    m = _ISO_RE.search(text)
    if m:
        return _build_match(int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(0))

    m = _MONTH_FIRST_RE.search(text)
    if m:
        month = MONTHS[m.group(1).lower()]
        day = int(m.group(2))
        year = int(m.group(3)) if m.group(3) else _infer_year(month, day, now)
        return _build_match(year, month, day, m.group(0))

    m = _DAY_FIRST_RE.search(text)
    if m:
        day = int(m.group(1))
        month = MONTHS[m.group(2).lower()]
        year = int(m.group(3)) if m.group(3) else _infer_year(month, day, now)
        return _build_match(year, month, day, m.group(0))

    m = _NUMERIC_RE.search(text)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if year < 100:
            year += 2000
        return _build_match(year, month, day, m.group(0))

    return None


def extract_date_query(query: str, now: datetime) -> tuple[DateMatch | None, str]:
    """Detect an explicit date and return (match, query with the date phrase removed).

    The remainder drives hybrid routing: "camping on june 1st 2025" →
    (1 Jun 2025 window, "camping").
    """
    match = parse_explicit_date(query, now)
    if match is None:
        return None, query
    remainder = query.replace(match.matched_text, " ")
    remainder = re.sub(r"\s+", " ", remainder).strip(" ?!.,")
    return match, remainder
