"""UTC helpers shared across immutable contracts."""

from __future__ import annotations

from datetime import datetime, timezone


def ensure_utc(value: datetime) -> datetime:
    """Normalize an aware timestamp to UTC."""

    if value.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(timezone.utc)


def isoformat_utc(value: datetime) -> str:
    """Return a UTC ISO string for a timezone-aware datetime."""

    return ensure_utc(value).isoformat()


__all__ = ["ensure_utc", "isoformat_utc"]
