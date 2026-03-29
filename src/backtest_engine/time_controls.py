"""Shared helpers for intraday session and EOD time controls."""

from __future__ import annotations

from datetime import datetime, time
from typing import Optional


def parse_hhmm(value: Optional[str], field_name: str) -> Optional[time]:
    """
    Parses an optional HH:MM value into datetime.time.

    Args:
        value: Input string like "09:30", blank string, or None.
        field_name: Logical setting name for validation messages.

    Returns:
        Parsed time object, or None when value is None/blank.

    Raises:
        ValueError: If input is not a valid HH:MM time.
    """
    if value is None:
        return None

    text = str(value).strip()
    if text == "":
        return None

    parts = text.split(":")
    if len(parts) != 2:
        raise ValueError(f"{field_name} must be HH:MM or None, got {value!r}")

    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be HH:MM or None, got {value!r}") from exc

    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"{field_name} must be HH:MM or None, got {value!r}")
    return time(hour=hour, minute=minute)


def is_session_active(
    timestamp: datetime,
    use_trading_hours: bool,
    trade_start_time: Optional[time],
    trade_end_time: Optional[time],
) -> bool:
    """
    Returns True when strategy logic should run at this timestamp.

    Supports open-ended windows and overnight windows that cross midnight.
    """
    if not use_trading_hours:
        return True
    if trade_start_time is None and trade_end_time is None:
        return True

    now = timestamp.time()
    if trade_start_time is None:
        return now <= trade_end_time
    if trade_end_time is None:
        return now >= trade_start_time
    if trade_start_time <= trade_end_time:
        return trade_start_time <= now <= trade_end_time
    return now >= trade_start_time or now <= trade_end_time
