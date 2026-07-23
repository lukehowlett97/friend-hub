"""Text repair helpers for Facebook Messenger exports."""

from __future__ import annotations

import re
import unicodedata


CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
MOJIBAKE_MARKERS = ("Ã", "Â", "â", "ð", "ï")
ASCII_PUNCTUATION = str.maketrans({
    "‘": "'",
    "’": "'",
    "‚": "'",
    "“": '"',
    "”": '"',
    "„": '"',
})


def _looks_mojibaked(value: str) -> bool:
    return any(marker in value for marker in MOJIBAKE_MARKERS)


def repair_text(value: str | None) -> str:
    """Repair common Messenger mojibake while preserving valid Unicode."""
    if value is None:
        return ""

    text = str(value)
    if _looks_mojibaked(text):
        for source_encoding in ("cp1252", "latin-1"):
            try:
                repaired = text.encode(source_encoding).decode("utf-8")
            except UnicodeError:
                continue
            if repaired:
                text = repaired
                break

    text = unicodedata.normalize("NFC", text)
    text = text.translate(ASCII_PUNCTUATION)
    return CONTROL_CHARS_RE.sub("", text)
