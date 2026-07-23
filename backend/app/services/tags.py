"""
Shared tag normalization and validation utilities.
"""


def normalize_tags(tags: list[str] | None, max_tags: int = 8, max_length: int = 40) -> list[str]:
    """
    Normalize a list of tags for storage and comparison.
    
    Args:
        tags: Raw tag list (may contain duplicates, whitespace, hashes, mixed case)
        max_tags: Maximum number of tags to keep
        max_length: Maximum length per tag
    
    Returns:
        Normalized tag list: lowercase, deduplicated, trimmed
    
    Examples:
        normalize_tags(['Beans', '  pub  ', '#holiday', 'beans']) 
        -> ['beans', 'pub', 'holiday']
    """
    if not tags:
        return []
    
    normalized = []
    seen = set()
    
    for tag in tags:
        if not isinstance(tag, str):
            continue
        
        # Trim whitespace, lowercase, remove leading hash
        value = tag.strip().lower().lstrip("#")[:max_length]
        
        # Skip empty tags and duplicates
        if value and value not in seen:
            normalized.append(value)
            seen.add(value)
            if len(normalized) >= max_tags:
                break
    
    return normalized


def is_valid_tag(tag: str) -> bool:
    """Check if a tag string is valid (non-empty after normalization)."""
    if not isinstance(tag, str):
        return False
    return bool(tag.strip())
