"""Portfolio rebalancing contracts."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from backtest_engine.core.types import NonEmptyStr
from backtest_engine.domain.portfolio.allocations import AllocationTarget


class RebalanceInstruction(BaseModel):
    """A rebalancing instruction tied to a target allocation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cadence: NonEmptyStr
    target: AllocationTarget


class RebalancePlan(BaseModel):
    """A normalized rebalancing plan for a portfolio run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cadence: NonEmptyStr
    instructions: tuple[RebalanceInstruction, ...]


__all__ = ["RebalanceInstruction", "RebalancePlan"]
