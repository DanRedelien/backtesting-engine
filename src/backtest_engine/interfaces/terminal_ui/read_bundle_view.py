"""Terminal UI adapter for bundle views and rerun eligibility."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from backtest_engine.analytics.read_models import BundleReadModel
from backtest_engine.core.enums import RunKind
from backtest_engine.domain.artifacts.bundles import ResultBundle

_PORTFOLIO_ONLY_MESSAGE = "Scenario reruns are only available for portfolio bundles."


class BundleViewRequest(BaseModel):
    """A terminal UI request for one bundle view."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    bundle_path: Path


class BundleViewService(Protocol):
    """Load bundle truth and read models for the terminal UI."""

    def load_bundle(self, bundle_path: Path) -> ResultBundle:
        """Return the persisted bundle contract."""
        ...

    def load_bundle_read_model(self, bundle_path: Path) -> BundleReadModel:
        """Return the delivery read model for one persisted bundle."""
        ...


class TerminalBundleView(BaseModel):
    """A terminal UI view model for one saved bundle."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    summary: BundleReadModel
    can_run_scenario: bool
    scenario_block_reason: str = ""


def read_bundle_view(
    command: BundleViewRequest,
    service: BundleViewService,
) -> TerminalBundleView:
    """Load the bundle view and compute rerun eligibility without legacy runtime code."""

    bundle = service.load_bundle(command.bundle_path)
    summary = service.load_bundle_read_model(command.bundle_path)
    can_run_scenario = bundle.run_spec.run_kind is RunKind.PORTFOLIO
    return TerminalBundleView(
        summary=summary,
        can_run_scenario=can_run_scenario,
        scenario_block_reason="" if can_run_scenario else _PORTFOLIO_ONLY_MESSAGE,
    )


__all__ = ["BundleViewRequest", "BundleViewService", "TerminalBundleView", "read_bundle_view"]
