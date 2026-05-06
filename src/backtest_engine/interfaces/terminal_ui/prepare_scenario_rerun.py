"""Terminal UI adapter for canonical scenario rerun requests."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from backtest_engine.core.enums import RunKind
from backtest_engine.core.errors import ApplicationError
from backtest_engine.core.types import NonEmptyStr
from backtest_engine.domain.artifacts.bundles import ResultBundle
from backtest_engine.interfaces.workers.run_scenario_job import ScenarioJobCommand


class ScenarioRerunRequest(BaseModel):
    """A terminal UI request to rerun one saved bundle as a scenario."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    bundle_path: Path
    scenario_name: NonEmptyStr
    requested_by: NonEmptyStr = "terminal_ui"


class ScenarioRerunService(Protocol):
    """Load replayable bundles for terminal scenario actions."""

    def load_bundle(self, bundle_path: Path) -> ResultBundle:
        """Return the persisted bundle contract."""
        ...


class ScenarioRerunPlan(BaseModel):
    """A terminal UI plan for one canonical scenario worker job."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_bundle_id: NonEmptyStr
    source_run_id: NonEmptyStr
    job_command: ScenarioJobCommand


def prepare_scenario_rerun(
    command: ScenarioRerunRequest,
    service: ScenarioRerunService,
) -> ScenarioRerunPlan:
    """Build the canonical worker request for one saved portfolio bundle."""

    bundle = service.load_bundle(command.bundle_path)
    if bundle.run_spec.run_kind is not RunKind.PORTFOLIO:
        raise ApplicationError(
            "scenario reruns are only available for portfolio bundles",
            run_kind=bundle.run_spec.run_kind,
            bundle_id=bundle.bundle_id,
        )

    return ScenarioRerunPlan(
        source_bundle_id=bundle.bundle_id,
        source_run_id=bundle.manifest.run_id,
        job_command=ScenarioJobCommand(
            scenario_name=command.scenario_name,
            base_run_spec=bundle.run_spec,
            requested_by=command.requested_by,
        ),
    )


__all__ = ["ScenarioRerunPlan", "ScenarioRerunRequest", "ScenarioRerunService", "prepare_scenario_rerun"]
