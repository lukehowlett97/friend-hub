import re
from dataclasses import dataclass

from app.models.message import User


GENERATED_USER_RE = re.compile(r"^User-[0-9a-f]{6,}$", re.IGNORECASE)
TEST_USER_PREFIX_RE = re.compile(r"^TestUser", re.IGNORECASE)


@dataclass(frozen=True)
class CleanupSuggestion:
    likely_test_user: bool
    cleanup_suggestion: str | None
    suggestion_reason: str | None


def detect_user_cleanup_candidate(user: User, message_count: int | None = None) -> CleanupSuggestion:
    names = [
        getattr(user, "username", None),
        getattr(user, "nickname", None),
        getattr(user, "display_name", None),
    ]
    clean_names = [name.strip() for name in names if isinstance(name, str) and name.strip()]

    for name in clean_names:
        if GENERATED_USER_RE.match(name):
            return CleanupSuggestion(True, "review_generated_user", f"Name matches generated user pattern: {name}")
        if TEST_USER_PREFIX_RE.match(name):
            return CleanupSuggestion(True, "mark_as_test", f"Name starts with TestUser: {name}")

    for name in clean_names:
        lower = name.lower()
        if "test" in lower and lower not in {"contest", "latest"}:
            return CleanupSuggestion(True, "review_test_user", f"Name contains test marker: {name}")

    if message_count == 0 and not getattr(user, "pin_hash", None) and not getattr(user, "invite_code_used_at", None):
        return CleanupSuggestion(False, "review_inactive_placeholder", "No messages and no completed login state")

    return CleanupSuggestion(False, None, None)

