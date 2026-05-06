"""Tests for portfolio sizing parity between runtime and study paths."""

from __future__ import annotations

import pandas as pd
import pytest

from backtest_engine.config.runtime import PortfolioExecutionPolicy
from backtest_engine.core.enums import WarmupPolicy
from backtest_engine.domain.portfolio.sizing import (
    SleeveAnalyticsFrame,
    build_sleeve_analytics_frame,
    evaluate_portfolio_sizing_run,
    resolve_portfolio_scalar,
)
from backtest_engine.domain.strategy.specifications import (
    PortfolioStrategySpec,
    StrategyLegSpec,
    StrategySpec,
)
from backtest_engine.infrastructure.nautilus.portfolio_sizing import compile_portfolio_sizing


def _make_policy(**overrides: object) -> PortfolioExecutionPolicy:
    defaults: dict[str, object] = {
        "rebalance_cadence": "run_open",
        "target_portfolio_vol_frac": 0.20,
        "vol_lookback_bars": 5,
        "max_portfolio_leverage": 1.0,
        "estimator_version": "rolling_sample_v1",
        "annualization_policy": "252d",
        "warmup_policy": WarmupPolicy.HOLD_FLAT_UNTIL_LOOKBACK,
    }
    defaults.update(overrides)
    return PortfolioExecutionPolicy(**defaults)


def _make_strategy_specs(weights: dict[str, float]) -> tuple[PortfolioStrategySpec, ...]:
    return tuple(
        PortfolioStrategySpec(
            slot_id=slot_id,
            strategy=StrategySpec(
                strategy_id=f"strat_{slot_id}",
                implementation_id="sma_pullback",
                policy_version="v1",
            ),
            legs=(StrategyLegSpec(symbol=slot_id),),
            weight_frac=weight,
        )
        for slot_id, weight in weights.items()
    )


def _make_sleeve_frame(slot_id: str, returns: list[float]) -> SleeveAnalyticsFrame:
    n = len(returns)
    frame = pd.DataFrame(
        {
            "timestamp_utc": pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC"),
            "unit_return_after_costs": returns,
            "unit_turnover": [0.01] * n,
            "is_active": [True] * n,
            "has_valid_history": [True] * n,
            "gross_exposure": [1.0] * n,
            "costs": [0.001] * n,
        }
    )
    return build_sleeve_analytics_frame(slot_id, frame)


class TestPortfolioScalarFormulaParity:
    """The shared scalar contract must stay stable and explicit."""

    def test_resolve_portfolio_scalar_matches_expected_formula(self) -> None:
        for estimated_vol in [0.0, 0.05, 0.10, 0.20, 0.40, 1.0]:
            result = resolve_portfolio_scalar(
                estimated_vol=estimated_vol,
                target_portfolio_vol_frac=0.20,
                max_portfolio_leverage=1.0,
            )
            expected = 0.0 if estimated_vol <= 0.0 else min(1.0, 1.0, 0.20 / estimated_vol)
            assert result == expected

    def test_scalar_zero_for_zero_vol(self) -> None:
        result = resolve_portfolio_scalar(
            estimated_vol=0.0,
            target_portfolio_vol_frac=0.20,
            max_portfolio_leverage=1.0,
        )
        assert result == 0.0

    def test_scalar_capped_at_max_leverage(self) -> None:
        result = resolve_portfolio_scalar(
            estimated_vol=0.01,
            target_portfolio_vol_frac=0.20,
            max_portfolio_leverage=0.5,
        )
        assert result == 0.5

    def test_scalar_capped_at_one(self) -> None:
        result = resolve_portfolio_scalar(
            estimated_vol=0.01,
            target_portfolio_vol_frac=0.20,
            max_portfolio_leverage=100.0,
        )
        assert result == 1.0


class TestCompiledSizingPolicy:
    """Compiled sizing must carry all policy parameters for downstream audit."""

    def test_policy_fields_preserved(self) -> None:
        policy = _make_policy(vol_lookback_bars=10, annualization_policy="365d")
        specs = _make_strategy_specs({"A": 0.6, "B": 0.4})
        compiled = compile_portfolio_sizing(specs, policy)
        assert compiled.vol_lookback_bars == 10
        assert compiled.annualization_factor == 365.0
        assert compiled.warmup_policy == "hold_flat_until_lookback"

    def test_dynamic_scalar_with_estimated_vol(self) -> None:
        policy = _make_policy(target_portfolio_vol_frac=0.20, max_portfolio_leverage=1.0)
        specs = _make_strategy_specs({"A": 0.5, "B": 0.5})
        compiled = compile_portfolio_sizing(specs, policy, estimated_portfolio_vol=0.10)
        assert compiled.portfolio_scalar == 1.0

    def test_dynamic_scalar_scales_down_high_vol(self) -> None:
        policy = _make_policy(target_portfolio_vol_frac=0.20, max_portfolio_leverage=1.0)
        specs = _make_strategy_specs({"A": 0.5, "B": 0.5})
        compiled = compile_portfolio_sizing(specs, policy, estimated_portfolio_vol=0.40)
        assert compiled.portfolio_scalar == pytest.approx(0.5)

    def test_fallback_when_no_vol_estimate(self) -> None:
        policy = _make_policy(target_portfolio_vol_frac=0.15, max_portfolio_leverage=0.8)
        specs = _make_strategy_specs({"A": 1.0})
        compiled = compile_portfolio_sizing(specs, policy)
        assert compiled.portfolio_scalar == pytest.approx(0.15)


class TestCausalSizingWarmup:
    """The shared causal engine must exclude bars during warmup."""

    def test_empty_analytics_returns_zeroed_run(self) -> None:
        policy = _make_policy(vol_lookback_bars=5)
        result = evaluate_portfolio_sizing_run(
            analytics_by_slot={},
            target_weights={},
            policy=policy,
        )

        assert result.snapshots == ()
        assert result.effective_bar_count == 0
        assert result.effective_start_utc is None
        assert result.effective_end_utc is None
        assert result.net_return == 0.0
        assert result.sharpe_after_costs == 0.0
        assert result.max_drawdown == 0.0

    def test_bars_below_lookback_produce_zero_allocation(self) -> None:
        policy = _make_policy(vol_lookback_bars=5)
        analytics = {
            "A": _make_sleeve_frame("A", [0.01] * 10),
            "B": _make_sleeve_frame("B", [0.02] * 10),
        }
        target_weights = {"A": 0.6, "B": 0.4}
        result = evaluate_portfolio_sizing_run(
            analytics_by_slot=analytics,
            target_weights=target_weights,
            policy=policy,
        )

        for snapshot in result.snapshots[:5]:
            assert len(snapshot.eligible_slots) == 0
            assert snapshot.portfolio_scalar == 0.0
            assert snapshot.cash_weight == 1.0

    def test_effective_bar_count_excludes_warmup(self) -> None:
        policy = _make_policy(vol_lookback_bars=5)
        analytics = {
            "A": _make_sleeve_frame(
                "A",
                [0.01, -0.02, 0.015, -0.005, 0.02, 0.01, -0.01, 0.005, 0.015, -0.005],
            )
        }
        target_weights = {"A": 1.0}
        result = evaluate_portfolio_sizing_run(
            analytics_by_slot=analytics,
            target_weights=target_weights,
            policy=policy,
        )
        assert result.effective_bar_count == 5


class TestWeightInvariants:
    """Target weights must sum to 1.0 and effective weights must stay bounded."""

    def test_target_weights_simplex(self) -> None:
        specs = _make_strategy_specs({"A": 0.3, "B": 0.3, "C": 0.4})
        total = sum(spec.weight_frac for spec in specs)
        assert abs(total - 1.0) < 1e-9

    def test_effective_weights_bounded(self) -> None:
        policy = _make_policy(vol_lookback_bars=3)
        analytics = {
            "A": _make_sleeve_frame("A", [0.01] * 8),
            "B": _make_sleeve_frame("B", [0.01] * 8),
        }
        target_weights = {"A": 0.5, "B": 0.5}
        result = evaluate_portfolio_sizing_run(
            analytics_by_slot=analytics,
            target_weights=target_weights,
            policy=policy,
        )
        for snapshot in result.snapshots:
            effective_sum = sum(snapshot.effective_weights.values())
            assert effective_sum <= 1.0 + 1e-9
            assert snapshot.cash_weight >= -1e-9
