"""Compile portfolio target weights into runtime slot multipliers.

The canonical runtime uses a static initial sizing estimate at compile time.
The shared causal sizing engine in ``domain.portfolio.sizing`` evaluates
per-bar effective weights dynamically during study scoring. Both paths now
reuse the same scalar implementation so one fix cannot drift from the other.

When the shared causal sizing engine determines that the canonical runtime
scalar diverges meaningfully from the per-bar dynamic schedule, it blocks
recommendation publication (fail-closed by design).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from backtest_engine.config.runtime import PortfolioExecutionPolicy
from backtest_engine.core.annualization import resolve_annualization_factor
from backtest_engine.core.types import NonEmptyStr
from backtest_engine.domain.portfolio.sizing import resolve_portfolio_scalar
from backtest_engine.domain.strategy.specifications import PortfolioStrategySpec


class CompiledSlotSizing(BaseModel):
    """One compiled sizing record for a portfolio slot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    slot_id: NonEmptyStr
    target_weight_frac: float = Field(ge=0.0, le=1.0)
    effective_weight_frac: float = Field(ge=0.0)
    slot_multiplier: float = Field(ge=0.0)


class CompiledPortfolioSizing(BaseModel):
    """A deterministic runtime sizing plan for a portfolio run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rebalance_cadence: NonEmptyStr
    portfolio_scalar: float = Field(ge=0.0)
    target_weight_sum: float = Field(ge=0.0)
    effective_weight_sum: float = Field(ge=0.0)
    vol_lookback_bars: int = Field(ge=2)
    annualization_factor: float = Field(gt=0.0)
    warmup_policy: NonEmptyStr
    slots: tuple[CompiledSlotSizing, ...] = Field(default_factory=tuple)

def compile_portfolio_sizing(
    strategy_specs: tuple[PortfolioStrategySpec, ...],
    policy: PortfolioExecutionPolicy,
    *,
    estimated_portfolio_vol: float | None = None,
) -> CompiledPortfolioSizing:
    """Compile target sleeve weights into runtime slot multipliers.

    Parameters
    ----------
    strategy_specs:
        Portfolio strategy specs with ``weight_frac``.
    policy:
        The portfolio execution policy containing all sizing parameters.
    estimated_portfolio_vol:
        If provided, the annualized portfolio vol estimate used for dynamic
        scalar computation via the shared portfolio scalar formula.
        If ``None`` (the default at backtest start when no history is available),
        falls back to the conservative static cap ``min(target_vol, max_lev)``.
    """
    annualization_factor = resolve_annualization_factor(policy.annualization_policy)

    if estimated_portfolio_vol is not None and estimated_portfolio_vol > 0.0:
        portfolio_scalar = resolve_portfolio_scalar(
            estimated_vol=estimated_portfolio_vol,
            target_portfolio_vol_frac=policy.target_portfolio_vol_frac,
            max_portfolio_leverage=policy.max_portfolio_leverage,
        )
    else:
        # Conservative fallback: cap at the smaller of vol target and leverage limit.
        # This is the initial-bar behavior before any vol history is available.
        portfolio_scalar = float(min(policy.target_portfolio_vol_frac, policy.max_portfolio_leverage))

    target_weight_sum = float(sum(spec.weight_frac for spec in strategy_specs))
    slots = tuple(
        CompiledSlotSizing(
            slot_id=spec.slot_id,
            target_weight_frac=float(spec.weight_frac),
            effective_weight_frac=float(spec.weight_frac) * portfolio_scalar,
            slot_multiplier=float(spec.weight_frac) * portfolio_scalar,
        )
        for spec in strategy_specs
    )
    return CompiledPortfolioSizing(
        rebalance_cadence=policy.rebalance_cadence,
        portfolio_scalar=portfolio_scalar,
        target_weight_sum=target_weight_sum,
        effective_weight_sum=float(sum(slot.effective_weight_frac for slot in slots)),
        vol_lookback_bars=policy.vol_lookback_bars,
        annualization_factor=annualization_factor,
        warmup_policy=policy.warmup_policy.value,
        slots=slots,
    )


__all__ = ["CompiledPortfolioSizing", "CompiledSlotSizing", "compile_portfolio_sizing"]
