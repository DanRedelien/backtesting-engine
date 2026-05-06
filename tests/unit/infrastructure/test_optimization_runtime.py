from __future__ import annotations

from decimal import Decimal
from datetime import datetime, timezone

import pytest

from backtest_engine.application.optimization.trial_executor import TrialExecution
from backtest_engine.application.optimization.trial_runtime import CanonicalTrialRuntime
from backtest_engine.config.runtime import BacktestRunSpec, ExecutionWindow
from backtest_engine.core.enums import DatasetSource, RunKind
from backtest_engine.core.errors import InfrastructureError
from backtest_engine.core.money import Money
from backtest_engine.domain.market.datasets import DatasetSpec
from backtest_engine.domain.strategy.specifications import (
    PortfolioStrategySpec,
    StrategyLegSpec,
    StrategySpec,
)
from backtest_engine.infrastructure.observability import InMemoryDiagnosticsSink
from backtest_engine.infrastructure.optimization import optuna_is_available, require_optuna


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


class FakeTrialExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None, str]] = []

    def execute(
        self,
        run_spec: BacktestRunSpec,
        *,
        requested_by: str,
        correlation_id: str | None = None,
    ) -> TrialExecution:
        self.calls.append((requested_by, correlation_id, run_spec.run_id))
        return TrialExecution(
            run_id=run_spec.run_id,
            run_kind=run_spec.run_kind,
            bundle_uri=f"results/{run_spec.run_id}",
            metric_values={"net_profit": float(len(self.calls))},
        )


def test_canonical_trial_runtime_preserves_order_and_emits_diagnostics() -> None:
    first = _build_run_spec(RunKind.SINGLE, "sma_pullback", "ES")
    second = _build_run_spec(RunKind.PORTFOLIO, "channel_breakout_long", "NQ")
    diagnostics = InMemoryDiagnosticsSink()
    executor = FakeTrialExecutor()
    runtime = CanonicalTrialRuntime(
        executor=executor,
        max_parallel_trials=2,
        diagnostics=diagnostics,
    )

    executions = runtime.execute_many(
        (first, second),
        requested_by="wfo-test",
        correlation_id="wf-correlation",
    )

    assert [execution.run_id for execution in executions] == [first.run_id, second.run_id]
    assert executor.calls == [
        ("wfo-test", "wf-correlation", first.run_id),
        ("wfo-test", "wf-correlation", second.run_id),
    ]
    assert diagnostics.events[0].stage == "optimization.execute_many"
    assert diagnostics.events[0].status == "started"
    assert diagnostics.events[-1].stage == "optimization.execute_many"
    assert diagnostics.events[-1].status == "succeeded"
    assert any(event.run_id == first.run_id for event in diagnostics.events)
    assert any(event.run_id == second.run_id for event in diagnostics.events)


def test_require_optuna_reports_missing_optional_dependency() -> None:
    if optuna_is_available():
        assert require_optuna() is not None
        return

    with pytest.raises(InfrastructureError):
        require_optuna()
