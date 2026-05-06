"""Small shared helpers for spread calibration publication."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from backtest_engine.core.errors import ApplicationError
from backtest_engine.infrastructure.data.coverage_policy import TIMEFRAME_TO_MINUTES


def artifact_path_part(value: str) -> str:
    """Return a filesystem-safe path segment for a publication identity field."""

    return "".join(
        character if character.isalnum() or character in {"-", "_"} else "_" for character in value
    )


def canonical_symbol(symbol: str) -> str:
    """Normalize an input symbol for provenance joins."""

    return symbol.strip().upper()


def decimal_string(value: float | Decimal) -> str:
    """Return a stable decimal string for generated YAML and reports."""

    decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
    if not decimal_value.is_finite():
        raise ApplicationError("cannot serialize non-finite calibration decimal")
    normalized = decimal_value.normalize()
    formatted = format(normalized, "f")
    if "." in formatted:
        formatted = formatted.rstrip("0").rstrip(".")
    return formatted or "0"


def isoformat_utc(value: datetime) -> str:
    """Return an ISO-8601 UTC string with a Z suffix."""

    return value.isoformat().replace("+00:00", "Z")


def timeframe_delta(timeframe: str) -> timedelta:
    """Return the duration represented by a repository timeframe string."""

    normalized_timeframe = timeframe.strip().lower()
    try:
        timeframe_minutes = TIMEFRAME_TO_MINUTES[normalized_timeframe]
    except KeyError as exc:
        raise ApplicationError(
            "unsupported timeframe for spread calibration publication",
            timeframe=timeframe,
            supported_timeframes=",".join(sorted(TIMEFRAME_TO_MINUTES)),
        ) from exc
    return timedelta(minutes=timeframe_minutes)


__all__ = [
    "artifact_path_part",
    "canonical_symbol",
    "decimal_string",
    "isoformat_utc",
    "timeframe_delta",
]
