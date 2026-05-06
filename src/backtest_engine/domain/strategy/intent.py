"""Intent-level outputs emitted by pure strategy policy."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from backtest_engine.core.enums import SignalDirection
from backtest_engine.core.ids import StrategyId
from backtest_engine.core.types import NonEmptyStr, Symbol


class SignalIntent(BaseModel):
    """A strategy policy intent that downstream execution can translate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    strategy_id: StrategyId
    symbol: Symbol
    direction: SignalDirection
    reason: NonEmptyStr
    strength_frac: float = Field(ge=0.0, le=1.0, default=1.0)


__all__ = ["SignalIntent"]
