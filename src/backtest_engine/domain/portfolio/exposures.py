"""Portfolio exposure contracts."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from backtest_engine.core.types import Symbol


class InstrumentExposure(BaseModel):
    """A normalized exposure snapshot per instrument."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: Symbol
    gross_notional: float
    net_notional: float


__all__ = ["InstrumentExposure"]
