"""Shared timeframe normalization helpers."""

from __future__ import annotations


TIMEFRAME_ALIASES = {
    "M1": "1m",
    "M5": "5m",
    "M15": "15m",
    "M30": "30m",
    "H1": "1h",
    "H4": "4h",
    "D1": "1d",
}


def normalize_timeframe(value: str) -> str:
    """Return the repository's canonical lowercase timeframe token."""

    stripped = value.strip()
    return TIMEFRAME_ALIASES.get(stripped.upper(), stripped.lower())


__all__ = ["TIMEFRAME_ALIASES", "normalize_timeframe"]
