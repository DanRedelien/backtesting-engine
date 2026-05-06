# mypy: disable-error-code=no-untyped-def
from __future__ import annotations

from decimal import Decimal
from datetime import datetime, timezone

import pytest

from backtest_engine.application.batch.run_batch_backtests import BatchRunCommand, run_batch_backtests
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


def _build_run_spec(run_kind: RunKind, strategy_id: str, symbol: str, weight_frac: float) -> BacktestRunSpec:
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
                weight_frac=weight_frac,
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
        self.calls: list[tuple[str, str]] = []

    def run(self, command, run_spec: BacktestRunSpec) -> SingleRunResult:
        self.calls.append((command.requested_by, run_spec.run_id))
        return SingleRunResult(
            run_id=run_spec.run_id,
            bundle_id=f"bundle-{run_spec.run_id[-12:]}",
            bundle_uri=f"results/{run_spec.run_id}",
            runtime_root=f"var/runtime/nautilus/{run_spec.run_id}",
            metric_values={"sharpe": 1.1},
        )


class FakePortfolioExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def run(self, command, run_spec: BacktestRunSpec) -> PortfolioRunResult:
        self.calls.append((command.requested_by, run_spec.run_id))
        return PortfolioRunResult(
            run_id=run_spec.run_id,
            bundle_id=f"bundle-{run_spec.run_id[-12:]}",
            bundle_uri=f"results/{run_spec.run_id}",
            runtime_root=f"var/runtime/nautilus/{run_spec.run_id}",
            allocation_count=len(run_spec.strategies),
            position_count=2,
            metric_values={"net_profit": 2500.0},
        )


def test_run_batch_backtests_dispatches_single_and_portfolio_specs() -> None:
    single_spec = _build_run_spec(RunKind.SINGLE, "sma_pullback", "ES", 1.0)
    portfolio_spec = _build_run_spec(RunKind.PORTFOLIO, "breakout", "NQ", 1.0)
    single_executor = FakeSingleExecutor()
    portfolio_executor = FakePortfolioExecutor()

    result = run_batch_backtests(
        command=BatchRunCommand(
            requested_by="batch-test",
            run_specs=(single_spec, portfolio_spec),
        ),
        single_executor=single_executor,
        portfolio_executor=portfolio_executor,
    )

    assert [entry.run_kind for entry in result.results] == [RunKind.SINGLE, RunKind.PORTFOLIO]
    assert result.summary.total_runs == 2
    assert result.summary.single_runs == 1
    assert result.summary.portfolio_runs == 1
    assert single_executor.calls == [("batch-test", single_spec.run_id)]
    assert portfolio_executor.calls == [("batch-test", portfolio_spec.run_id)]
    assert result.results[1].position_count == 2


def test_run_batch_backtests_rejects_non_canonical_member() -> None:
    unsupported_spec = _build_run_spec(RunKind.WALK_FORWARD, "sma_pullback", "ES", 1.0)

    with pytest.raises(ApplicationError):
        run_batch_backtests(
            command=BatchRunCommand(run_specs=(unsupported_spec,)),
            single_executor=FakeSingleExecutor(),
            portfolio_executor=FakePortfolioExecutor(),
        )
