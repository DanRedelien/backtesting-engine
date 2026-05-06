"""Prepare a scenario run around the canonical portfolio flow."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from backtest_engine.application.scenarios.mutate_portfolio_config import mutate_portfolio_config
from backtest_engine.config.runtime import BacktestRunSpec
from backtest_engine.core.types import NonEmptyStr


class ScenarioPreparationCommand(BaseModel):
    """A request wrapper for scenario preparation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario_name: NonEmptyStr
    base_run_spec: BacktestRunSpec


class PreparedScenario(BaseModel):
    """A prepared scenario with a mutated canonical run spec."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario_name: NonEmptyStr
    run_spec: BacktestRunSpec


def prepare_scenario(command: ScenarioPreparationCommand) -> PreparedScenario:
    """Prepare a scenario without introducing alternate execution semantics."""

    return PreparedScenario(
        scenario_name=command.scenario_name,
        run_spec=mutate_portfolio_config(
            run_spec=command.base_run_spec,
            scenario_name=command.scenario_name,
        ),
    )


__all__ = ["PreparedScenario", "ScenarioPreparationCommand", "prepare_scenario"]
