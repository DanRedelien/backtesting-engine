"""Background worker adapter for canonical scenario reruns."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict

from backtest_engine.application.scenarios.prepare_scenario import (
    ScenarioPreparationCommand,
    prepare_scenario,
)
from backtest_engine.application.scenarios.run_scenario import ScenarioRunCommand
from backtest_engine.application.portfolio.run_portfolio_backtest import PortfolioRunResult
from backtest_engine.config.runtime import BacktestRunSpec
from backtest_engine.core.types import NonEmptyStr


class ScenarioJobCommand(BaseModel):
    """A worker request for one canonical scenario rerun."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario_name: NonEmptyStr
    base_run_spec: BacktestRunSpec
    requested_by: NonEmptyStr = "worker"


class ScenarioJobResult(BaseModel):
    """The worker-facing result for one scenario rerun."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario_name: NonEmptyStr
    run_id: NonEmptyStr
    bundle_id: NonEmptyStr
    bundle_uri: NonEmptyStr
    runtime_root: NonEmptyStr
    allocation_count: int
    position_count: int
    metric_values: dict[str, float]


class ScenarioJobRunner(Protocol):
    """Execute a prepared scenario through the application boundary."""

    def run_scenario(self, command: ScenarioRunCommand) -> PortfolioRunResult:
        """Return the outcome of a scenario rerun."""
        ...


def run_scenario_job(
    command: ScenarioJobCommand,
    runner: ScenarioJobRunner,
) -> ScenarioJobResult:
    """Prepare then execute one scenario without adding worker-specific semantics."""

    prepared = prepare_scenario(
        ScenarioPreparationCommand(
            scenario_name=command.scenario_name,
            base_run_spec=command.base_run_spec,
        )
    )
    result = runner.run_scenario(
        ScenarioRunCommand(
            requested_by=command.requested_by,
            prepared_scenario=prepared,
        )
    )
    return ScenarioJobResult(
        scenario_name=command.scenario_name,
        run_id=result.run_id,
        bundle_id=result.bundle_id,
        bundle_uri=result.bundle_uri,
        runtime_root=result.runtime_root,
        allocation_count=result.allocation_count,
        position_count=result.position_count,
        metric_values=result.metric_values,
    )


__all__ = ["ScenarioJobCommand", "ScenarioJobResult", "ScenarioJobRunner", "run_scenario_job"]
