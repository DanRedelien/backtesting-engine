from __future__ import annotations

from decimal import Decimal
from datetime import datetime, timezone

from backtest_engine.application.scenarios.run_scenario import ScenarioRunCommand
from backtest_engine.application.portfolio.run_portfolio_backtest import PortfolioRunResult
from backtest_engine.config.runtime import BacktestRunSpec, ExecutionWindow
from backtest_engine.core.enums import DatasetSource, RunKind
from backtest_engine.core.money import Money
from backtest_engine.domain.market.datasets import DatasetSpec
from backtest_engine.domain.strategy.specifications import (
    PortfolioStrategySpec,
    StrategyLegSpec,
    StrategySpec,
)
from backtest_engine.interfaces.workers.run_scenario_job import ScenarioJobCommand, run_scenario_job


def _build_portfolio_run_spec() -> BacktestRunSpec:
    return BacktestRunSpec(
        run_kind=RunKind.PORTFOLIO,
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


class FakeScenarioRunner:
    def __init__(self) -> None:
        self.commands: list[ScenarioRunCommand] = []

    def run_scenario(self, command: ScenarioRunCommand) -> PortfolioRunResult:
        self.commands.append(command)
        return PortfolioRunResult(
            run_id=command.prepared_scenario.run_spec.run_id,
            bundle_id="bundle-worker-test",
            bundle_uri="results/bundle-worker-test",
            runtime_root="var/runtime/nautilus/run_worker_test",
            allocation_count=1,
            position_count=2,
            metric_values={"net_profit": 500.0},
        )


def test_run_scenario_job_reuses_the_canonical_scenario_flow() -> None:
    runner = FakeScenarioRunner()
    command = ScenarioJobCommand(
        scenario_name="stress-drawdown",
        base_run_spec=_build_portfolio_run_spec(),
        requested_by="worker-test",
    )

    result = run_scenario_job(command=command, runner=runner)

    assert len(runner.commands) == 1
    assert runner.commands[0].requested_by == "worker-test"
    assert runner.commands[0].prepared_scenario.scenario_name == "stress-drawdown"
    assert runner.commands[0].prepared_scenario.run_spec.tags[-1] == "stress-drawdown"
    assert result.scenario_name == "stress-drawdown"
    assert result.metric_values == {"net_profit": 500.0}
