"""Validated parameters for the passive bar cartridge."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from backtest_engine.core.ids import StrategyId
from backtest_engine.core.types import Symbol


class PassiveBarParameters(BaseModel):
    """Validated passive-bar parameters derived from one strategy spec."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    strategy_id: StrategyId
    symbol: Symbol


__all__ = ["PassiveBarParameters"]
