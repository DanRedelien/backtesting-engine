# mypy: disable-error-code=no-untyped-def
from __future__ import annotations

from decimal import Decimal
from datetime import datetime, timezone

import pytest

from backtest_engine.application.portfolio.run_portfolio_backtest import PortfolioRunResult
from backtest_engine.application.scenarios.prepare_scenario import (
    PreparedScenario,
    ScenarioPreparationCommand,
    prepare_scenario,
)
from backtest_engine.application.scenarios.run_scenario import ScenarioRunCommand, run_scenario
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
            allocation_count=1,
            position_count=1,
            metric_values={"net_profit": 10.0},
        )


def test_prepare_scenario_tags_the_portfolio_run_spec() -> None:
    portfolio_spec = _build_run_spec(RunKind.PORTFOLIO)

    prepared = prepare_scenario(
        ScenarioPreparationCommand(
            scenario_name="stress-drawdown",
            base_run_spec=portfolio_spec,
        )
    )

    assert prepared.scenario_name == "stress-drawdown"
    assert prepared.run_spec.tags[-1] == "stress-drawdown"


def test_prepare_scenario_rejects_non_portfolio_run_specs() -> None:
    single_spec = _build_run_spec(RunKind.SINGLE)

    with pytest.raises(ApplicationError):
        prepare_scenario(
            ScenarioPreparationCommand(
                scenario_name="stress-drawdown",
                base_run_spec=single_spec,
            )
        )


def test_run_scenario_reuses_the_canonical_portfolio_flow() -> None:
    portfolio_spec = _build_run_spec(RunKind.PORTFOLIO)
    prepared = PreparedScenario(scenario_name="stress-drawdown", run_spec=portfolio_spec)
    executor = FakePortfolioExecutor()

    result = run_scenario(
        command=ScenarioRunCommand(requested_by="scenario-test", prepared_scenario=prepared),
        executor=executor,
    )

    assert result.run_id == portfolio_spec.run_id
    assert executor.calls == [("scenario-test", portfolio_spec.run_id)]
