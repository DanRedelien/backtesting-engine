"""Portfolio allocation contracts."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from backtest_engine.core.ids import StrategyId
from backtest_engine.core.types import NonEmptyStr, Symbol


class AllocationTarget(BaseModel):
    """A target weight for one strategy slot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    slot_id: NonEmptyStr
    strategy_id: StrategyId
    leg_symbols: tuple[Symbol, ...]
    weight_frac: float = Field(ge=0.0, le=1.0)
    effective_weight_frac: float = Field(ge=0.0, default=0.0)
    slot_multiplier: float = Field(ge=0.0, default=0.0)


class PortfolioAllocationPlan(BaseModel):
    """A normalized set of allocation targets for a run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    targets: tuple[AllocationTarget, ...]


__all__ = ["AllocationTarget", "PortfolioAllocationPlan"]
