# mypy: disable-error-code=no-untyped-def
from __future__ import annotations

from decimal import Decimal
from datetime import datetime, timezone

import pytest

from backtest_engine.application.optimization.run_walk_forward import WalkForwardCommand, run_walk_forward
from backtest_engine.application.optimization.run_walk_forward_batch import (
    WalkForwardBatchCommand,
    run_walk_forward_batch,
)
from backtest_engine.application.optimization.trial_executor import CanonicalTrialExecutor
from backtest_engine.application.optimization.trial_runtime import CanonicalTrialRuntime
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


def _build_run_spec(run_kind: RunKind, strategy_id: str, symbol: str) -> BacktestRunSpec:
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
            symbol_universe=(symbol,),
            timeframe="30m",
            dataset_version="2026-04-03",
        ),
        strategies=(
            PortfolioStrategySpec(
                slot_id="slot-1",
                weight_frac=1.0,
                strategy=StrategySpec(
                    strategy_id=strategy_id,
                    implementation_id=strategy_id,
                    policy_version="v1",
                ),
                legs=(StrategyLegSpec(symbol=symbol),),
            ),
        ),
        capital_base=Money(amount=Decimal("100000"), currency="USD"),
    )


class FakeSingleExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None, str]] = []

    def run(self, command, run_spec: BacktestRunSpec) -> SingleRunResult:
        self.calls.append((command.requested_by, command.correlation_id, run_spec.run_id))
        return SingleRunResult(
            run_id=run_spec.run_id,
            bundle_id=f"bundle-{run_spec.run_id[-12:]}",
            bundle_uri=f"results/{run_spec.run_id}",
            runtime_root=f"var/runtime/nautilus/{run_spec.run_id}",
            metric_values={"net_profit": 100.0},
        )


class FakePortfolioExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None, str]] = []

    def run(self, command, run_spec: BacktestRunSpec) -> PortfolioRunResult:
        self.calls.append(
            (
                command.requested_by,
                command.correlation_id,
                run_spec.run_id,
            )
        )
        return PortfolioRunResult(
            run_id=run_spec.run_id,
            bundle_id=f"bundle-{run_spec.run_id[-12:]}",
            bundle_uri=f"results/{run_spec.run_id}",
            runtime_root=f"var/runtime/nautilus/{run_spec.run_id}",
            allocation_count=1,
            position_count=3,
            metric_values={"net_profit": 250.0},
        )


def test_run_walk_forward_dispatches_single_and_portfolio_specs() -> None:
    single_spec = _build_run_spec(RunKind.SINGLE, "sma_pullback", "ES")
    portfolio_spec = _build_run_spec(RunKind.PORTFOLIO, "breakout", "NQ")
    single_executor = FakeSingleExecutor()
    portfolio_executor = FakePortfolioExecutor()

    result = run_walk_forward(
        command=WalkForwardCommand(
            requested_by="wfo-test",
            correlation_id="wf-correlation",
            metric_name="net_profit",
            fold_run_specs=(single_spec, portfolio_spec),
        ),
        runtime=CanonicalTrialRuntime(
            executor=CanonicalTrialExecutor(
                single_executor=single_executor,
                portfolio_executor=portfolio_executor,
            ),
        ),
    )

    assert len(result.fold_results) == 2
    assert result.best_run_id == portfolio_spec.run_id
    assert single_executor.calls == [("wfo-test", "wf-correlation", single_spec.run_id)]
    assert portfolio_executor.calls == [("wfo-test", "wf-correlation", portfolio_spec.run_id)]


def test_run_walk_forward_batch_reuses_the_same_trial_executor() -> None:
    job_a = WalkForwardCommand(
        metric_name="net_profit",
        fold_run_specs=(_build_run_spec(RunKind.SINGLE, "sma_pullback", "ES"),),
    )
    job_b = WalkForwardCommand(
        metric_name="net_profit",
        fold_run_specs=(_build_run_spec(RunKind.PORTFOLIO, "breakout", "NQ"),),
    )

    result = run_walk_forward_batch(
        command=WalkForwardBatchCommand(
            correlation_id="batch-correlation",
            jobs=(job_a, job_b),
        ),
        runtime=CanonicalTrialRuntime(
            executor=CanonicalTrialExecutor(
                single_executor=FakeSingleExecutor(),
                portfolio_executor=FakePortfolioExecutor(),
            ),
        ),
    )

    assert len(result.job_results) == 2
    assert result.job_results[0].fold_results[0].metric_value == 100.0
    assert result.job_results[1].fold_results[0].metric_value == 250.0


def test_canonical_trial_executor_rejects_non_canonical_specs() -> None:
    unsupported_spec = _build_run_spec(RunKind.WALK_FORWARD, "sma_pullback", "ES")
    executor = CanonicalTrialExecutor(
        single_executor=FakeSingleExecutor(),
        portfolio_executor=FakePortfolioExecutor(),
    )

    with pytest.raises(ApplicationError):
        executor.execute(
            unsupported_spec,
            requested_by="wfo-test",
            correlation_id="wf-correlation",
        )
