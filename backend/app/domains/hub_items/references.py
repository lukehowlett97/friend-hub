import re

# Matches either the default-style #X-N references (where X is I/P/R/E/N) or
# a user-customised reference tag: # followed by a letter, then 1-18 chars of
# letters/digits/hyphens/underscores. The custom branch deliberately keeps a
# letter prefix so casual hashtags like "#1" don't match.
HUB_ITEM_REFERENCE_RE = re.compile(
    r"#(?:([IPREN])-(\d+)|([A-Za-z][A-Za-z0-9_-]{1,18}))\b"
)

REFERENCE_TYPE_BY_PREFIX = {
    "I": "idea",
    "P": "poll",
    "R": "reminder",
    "E": "event",
    "N": "note",
}


def find_hub_item_references(text: str) -> list[dict]:
    """Return references found in *text*.

    Default-form #X-N references carry a known type. Custom short_ids carry
    type=None — callers should resolve the actual type by looking the short_id
    up in the hub_items table.
    """
    references = []
    for match in HUB_ITEM_REFERENCE_RE.finditer(text or ""):
        default_prefix = match.group(1)
        if default_prefix:
            references.append({
                "short_id": f"#{default_prefix}-{match.group(2)}",
                "type": REFERENCE_TYPE_BY_PREFIX[default_prefix],
                "sequence": int(match.group(2)),
                "start": match.start(),
                "end": match.end(),
            })
        else:
            references.append({
                "short_id": f"#{match.group(3)}",
                "type": None,
                "sequence": None,
                "start": match.start(),
                "end": match.end(),
            })
    return references
