"""IB timeframe mappings for the V2 source-cache adapter."""

from __future__ import annotations

from enum import Enum

from backtest_engine.core.errors import InfrastructureError
from backtest_engine.core.types import Timeframe


class IbTimeframe(Enum):
    """Supported IB historical bar sizes used by the rewrite."""

    M1 = ("1m", "1 min")
    M5 = ("5m", "5 mins")
    M15 = ("15m", "15 mins")
    M30 = ("30m", "30 mins")
    H1 = ("1h", "1 hour")
    H4 = ("4h", "4 hours")
    D1 = ("1d", "1 day")

    def __init__(self, file_suffix: str, ib_bar_size: str) -> None:
        self.file_suffix = file_suffix
        self.ib_bar_size = ib_bar_size

    @classmethod
    def from_timeframe(cls, timeframe: Timeframe) -> "IbTimeframe":
        """Resolve one canonical timeframe string into an IB bar-size mapping."""

        for candidate in cls:
            if candidate.file_suffix == timeframe:
                return candidate
        supported = ", ".join(item.file_suffix for item in cls)
        raise InfrastructureError(
            "unsupported IB timeframe",
            timeframe=timeframe,
            supported_timeframes=supported,
        )


__all__ = ["IbTimeframe"]
