"""Build a normalized portfolio plan from the canonical run spec."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from backtest_engine.config.runtime import PortfolioExecutionPolicy
from backtest_engine.domain.portfolio.allocations import AllocationTarget, PortfolioAllocationPlan
from backtest_engine.domain.portfolio.rebalancing import RebalanceInstruction, RebalancePlan
from backtest_engine.domain.strategy.specifications import PortfolioStrategySpec
from backtest_engine.infrastructure.nautilus.portfolio_sizing import (
    CompiledPortfolioSizing,
    compile_portfolio_sizing,
)


class PortfolioBacktestPlan(BaseModel):
    """A normalized portfolio execution plan."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    allocation_plan: PortfolioAllocationPlan
    rebalance_plan: RebalancePlan
    compiled_sizing: CompiledPortfolioSizing


def build_portfolio_plan(
    strategy_specs: tuple[PortfolioStrategySpec, ...],
    policy: PortfolioExecutionPolicy,
) -> PortfolioBacktestPlan:
    """Create allocation and rebalancing plans from portfolio strategy specs."""

    compiled_sizing = compile_portfolio_sizing(strategy_specs, policy)
    sizing_by_slot = {slot.slot_id: slot for slot in compiled_sizing.slots}
    targets = tuple(
        AllocationTarget(
            slot_id=spec.slot_id,
            strategy_id=spec.strategy.strategy_id,
            leg_symbols=tuple(leg.symbol for leg in spec.legs),
            weight_frac=spec.weight_frac,
            effective_weight_frac=sizing_by_slot[spec.slot_id].effective_weight_frac,
            slot_multiplier=sizing_by_slot[spec.slot_id].slot_multiplier,
        )
        for spec in strategy_specs
    )
    instructions = tuple(
        RebalanceInstruction(cadence=policy.rebalance_cadence, target=target) for target in targets
    )
    return PortfolioBacktestPlan(
        allocation_plan=PortfolioAllocationPlan(targets=targets),
        rebalance_plan=RebalancePlan(
            cadence=policy.rebalance_cadence,
            instructions=instructions,
        ),
        compiled_sizing=compiled_sizing,
    )


__all__ = ["PortfolioBacktestPlan", "build_portfolio_plan"]
