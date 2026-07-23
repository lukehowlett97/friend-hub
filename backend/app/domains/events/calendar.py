from datetime import datetime, timedelta, timezone

from app.models.event import Event


DEFAULT_EVENT_DURATION = timedelta(hours=2)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _format_ics_datetime(value: datetime) -> str:
    return _as_utc(value).strftime("%Y%m%dT%H%M%SZ")


def escape_ics_text(value: str | None) -> str:
    if not value:
        return ""
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\n", "\\n")
        .replace(";", "\\;")
        .replace(",", "\\,")
    )


def _fold_ics_line(line: str) -> list[str]:
    encoded = line.encode("utf-8")
    if len(encoded) <= 75:
        return [line]

    lines: list[str] = []
    current = ""
    current_len = 0
    for char in line:
        char_len = len(char.encode("utf-8"))
        limit = 75 if not lines else 74
        if current and current_len + char_len > limit:
            lines.append(current if not lines else f" {current}")
            current = char
            current_len = char_len
        else:
            current += char
            current_len += char_len
    if current:
        lines.append(current if not lines else f" {current}")
    return lines


def build_event_ics(event: Event, event_url: str | None = None) -> str:
    starts_at = event.starts_at
    ends_at = getattr(event, "ends_at", None) or (starts_at + DEFAULT_EVENT_DURATION)
    updated_at = event.updated_at or event.created_at or datetime.utcnow()

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Friend Hub//Events//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:friend-hub-event-{event.id}@friend-hub",
        f"DTSTAMP:{_format_ics_datetime(datetime.now(timezone.utc))}",
        f"DTSTART:{_format_ics_datetime(starts_at)}",
        f"DTEND:{_format_ics_datetime(ends_at)}",
        f"SUMMARY:{escape_ics_text(event.title)}",
        f"DESCRIPTION:{escape_ics_text(event.description)}",
        f"LOCATION:{escape_ics_text(event.location)}",
        "STATUS:CONFIRMED",
        f"LAST-MODIFIED:{_format_ics_datetime(updated_at)}",
    ]
    if event_url:
        lines.append(f"URL:{escape_ics_text(event_url)}")
    lines.extend(["END:VEVENT", "END:VCALENDAR"])

    folded: list[str] = []
    for line in lines:
        folded.extend(_fold_ics_line(line))
    return "\r\n".join(folded) + "\r\n"
