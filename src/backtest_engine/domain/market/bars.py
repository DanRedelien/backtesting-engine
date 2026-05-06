"""Normalized bar series contracts."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from backtest_engine.core.types import Symbol, Timeframe


class BarSeriesSpec(BaseModel):
    """A normalized request for one bar series."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: Symbol
    timeframe: Timeframe
    lookback_bars: int = Field(ge=1, default=1)


__all__ = ["BarSeriesSpec"]
