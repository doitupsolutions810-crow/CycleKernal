import hashlib


def civ_id_for(user_id: str) -> str:
    """Stable internal key: sha256 of the FULL user_id, first 12 hex chars.

    The 6-char prefix is retained only as a human-readable display label.
    Companion channel: both the digest key and the display label are emitted
    so the discarded residue is never silently treated as the object.
    """
    if not user_id:
        raise ValueError("user_id must be non-empty")
    digest = hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:12]
    display = user_id[:6]
    return f"civ_{digest}", display


def legacy_civ_id_for(user_id: str) -> str:
    """The old truncation behavior — retained solely for migration comparison."""
    return f"user_{user_id[:6]}"
