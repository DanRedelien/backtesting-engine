"""Run a scenario through the canonical portfolio use-case."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict

from backtest_engine.application.portfolio.run_portfolio_backtest import (
    PortfolioRunCommand,
    PortfolioRunResult,
)
from backtest_engine.application.scenarios.prepare_scenario import PreparedScenario
from backtest_engine.config.runtime import BacktestRunSpec
from backtest_engine.core.enums import RunKind
from backtest_engine.core.errors import ApplicationError
from backtest_engine.core.types import NonEmptyStr


class ScenarioRunCommand(BaseModel):
    """A request wrapper for scenario execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    requested_by: NonEmptyStr = "operator"
    prepared_scenario: PreparedScenario


class PortfolioScenarioExecutor(Protocol):
    """Execute the canonical portfolio use-case."""

    def run(self, command: PortfolioRunCommand, run_spec: BacktestRunSpec) -> PortfolioRunResult:
        """Return the outcome of a portfolio backtest."""
        ...


def run_scenario(
    command: ScenarioRunCommand,
    executor: PortfolioScenarioExecutor,
) -> PortfolioRunResult:
    """Reuse the canonical portfolio flow for scenario reruns."""

    if command.prepared_scenario.run_spec.run_kind is not RunKind.PORTFOLIO:
        raise ApplicationError(
            "scenario execution requires a portfolio BacktestRunSpec",
            run_kind=command.prepared_scenario.run_spec.run_kind,
        )

    return executor.run(
        command=PortfolioRunCommand(requested_by=command.requested_by),
        run_spec=command.prepared_scenario.run_spec,
    )


__all__ = ["PortfolioScenarioExecutor", "ScenarioRunCommand", "run_scenario"]
