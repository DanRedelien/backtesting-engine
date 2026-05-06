# mypy: disable-error-code=no-untyped-def
from __future__ import annotations

from decimal import Decimal
from datetime import datetime, timezone

import pytest

from backtest_engine.application.baselines.capture_baseline import (
    BaselineCaptureCommand,
    capture_baseline,
)
from backtest_engine.application.portfolio.run_portfolio_backtest import PortfolioRunResult
from backtest_engine.application.single.run_single_backtest import SingleRunResult
from backtest_engine.config.runtime import BacktestRunSpec, ExecutionWindow
from backtest_engine.core.enums import DatasetSource, RunKind
from backtest_engine.core.errors import ApplicationError
from backtest_engine.core.money import Money
from backtest_engine.domain.market.datasets import DatasetSpec
from backtest_engine.domain.strategy.specifications import (
    PortfolioStrategySpec,
    StrategyLegSpec,
    StrategySpec,
)


def _build_run_spec(run_kind: RunKind) -> BacktestRunSpec:
    return BacktestRunSpec(
        run_kind=run_kind,
        execution_window=ExecutionWindow(
            start_utc=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end_utc=datetime(2024, 2, 1, tzinfo=timezone.utc),
        ),
        dataset=DatasetSpec(
            source_system=DatasetSource.PARQUET,
            normalization_policy="nautilus_v1",
            schema_version="1",
            symbol_universe=("ES",),
            timeframe="30m",
            dataset_version="2026-04-03",
        ),
        strategies=(
            PortfolioStrategySpec(
                slot_id="slot-1",
                weight_frac=1.0,
                strategy=StrategySpec(
                    strategy_id="sma_pullback",
                    implementation_id="sma_pullback",
                    policy_version="v1",
                ),
                legs=(StrategyLegSpec(symbol="ES"),),
            ),
        ),
        capital_base=Money(amount=Decimal("100000"), currency="USD"),
    )


class FakeSingleExecutor:
    def run(self, command, run_spec: BacktestRunSpec) -> SingleRunResult:
        return SingleRunResult(
            run_id=run_spec.run_id,
            bundle_id=f"bundle-{run_spec.run_id[-12:]}",
            bundle_uri=f"results/{run_spec.run_id}",
            runtime_root=f"var/runtime/nautilus/{run_spec.run_id}",
            metric_values={"sharpe": 1.0},
        )


class FakePortfolioExecutor:
    def run(self, command, run_spec: BacktestRunSpec) -> PortfolioRunResult:
        return PortfolioRunResult(
            run_id=run_spec.run_id,
            bundle_id=f"bundle-{run_spec.run_id[-12:]}",
            bundle_uri=f"results/{run_spec.run_id}",
            runtime_root=f"var/runtime/nautilus/{run_spec.run_id}",
            allocation_count=1,
            position_count=1,
            metric_values={"net_profit": 25.0},
        )


def test_capture_baseline_uses_the_single_flow_for_single_runs() -> None:
    run_spec = _build_run_spec(RunKind.SINGLE)

    result = capture_baseline(
        command=BaselineCaptureCommand(label="baseline-a", run_spec=run_spec),
        single_executor=FakeSingleExecutor(),
        portfolio_executor=FakePortfolioExecutor(),
    )

    assert result.label == "baseline-a"
    assert result.run_id == run_spec.run_id
    assert result.bundle_uri == f"results/{run_spec.run_id}"


def test_capture_baseline_rejects_non_canonical_run_kinds() -> None:
    run_spec = _build_run_spec(RunKind.BATCH)

    with pytest.raises(ApplicationError):
        capture_baseline(
            command=BaselineCaptureCommand(label="baseline-a", run_spec=run_spec),
            single_executor=FakeSingleExecutor(),
            portfolio_executor=FakePortfolioExecutor(),
        )
