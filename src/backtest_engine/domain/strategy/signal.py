"""Pure strategy output signals."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from backtest_engine.core.enums import SignalDirection
from backtest_engine.core.ids import StrategyId
from backtest_engine.core.types import Symbol


class StrategySignal(BaseModel):
    """A normalized strategy signal before execution translation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    strategy_id: StrategyId
    symbol: Symbol
    direction: SignalDirection
    conviction_frac: float = Field(ge=0.0, le=1.0, default=1.0)


__all__ = ["StrategySignal"]
