"""MT5 timeframe mappings for the historical-data provider."""

from __future__ import annotations

from backtest_engine.infrastructure.data.errors import UnsupportedTimeframeError


_MT5_TIMEFRAME_ATTRS: dict[str, str] = {
    "1m": "TIMEFRAME_M1",
    "5m": "TIMEFRAME_M5",
    "15m": "TIMEFRAME_M15",
    "30m": "TIMEFRAME_M30",
    "1h": "TIMEFRAME_H1",
    "4h": "TIMEFRAME_H4",
    "1d": "TIMEFRAME_D1",
}


def mt5_timeframe_attr(timeframe: str) -> str:
    """Return the MetaTrader5 timeframe constant name for one canonical timeframe."""

    try:
        return _MT5_TIMEFRAME_ATTRS[timeframe]
    except KeyError as exc:
        raise UnsupportedTimeframeError(
            "unsupported MT5 timeframe",
            timeframe=timeframe,
            supported_timeframes=",".join(sorted(_MT5_TIMEFRAME_ATTRS)),
        ) from exc


def supported_mt5_timeframes() -> tuple[str, ...]:
    """Return supported native MT5 timeframes."""

    return tuple(_MT5_TIMEFRAME_ATTRS)


__all__ = ["mt5_timeframe_attr", "supported_mt5_timeframes"]
