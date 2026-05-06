"""Presentation models for the V2 terminal UI."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from backtest_engine.analytics.read_models import BundleDashboardReadModel, BundleReadModel
from backtest_engine.core.enums import RunKind
from backtest_engine.core.types import NonEmptyStr
from backtest_engine.interfaces.terminal_ui.prepare_scenario_rerun import ScenarioRerunPlan
from backtest_engine.interfaces.terminal_ui.read_bundle_view import TerminalBundleView


class TerminalBundleCard(BaseModel):
    """A compact bundle card rendered in the terminal UI index."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    bundle_id: NonEmptyStr
    bundle_path: Path
    run_id: NonEmptyStr
    run_kind: RunKind
    dataset_id: NonEmptyStr
    created_at_utc: datetime
    strategy_ids: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)
    symbol_universe: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)
    metric_values: dict[str, float] = Field(default_factory=dict)
    can_run_scenario: bool

    @classmethod
    def from_summary(
        cls,
        *,
        bundle_path: Path,
        summary: BundleReadModel,
    ) -> "TerminalBundleCard":
        """Project one read model into a compact card for the dashboard."""

        return cls(
            bundle_id=summary.bundle_id,
            bundle_path=bundle_path,
            run_id=summary.run_id,
            run_kind=summary.run_kind,
            dataset_id=summary.dataset_id,
            created_at_utc=summary.created_at_utc,
            strategy_ids=summary.strategy_ids,
            symbol_universe=summary.symbol_universe,
            metric_values=summary.metric_values,
            can_run_scenario=summary.run_kind is RunKind.PORTFOLIO,
        )


class BundleLoadFailure(BaseModel):
    """A non-fatal bundle load failure surfaced to the UI."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    bundle_path: Path
    message: NonEmptyStr


class TerminalBundleCatalog(BaseModel):
    """The terminal UI catalog of discovered saved bundles."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    bundles: tuple[TerminalBundleCard, ...] = Field(default_factory=tuple)
    load_failures: tuple[BundleLoadFailure, ...] = Field(default_factory=tuple)


class TerminalBundleDetail(BaseModel):
    """A detailed bundle view rendered by the terminal UI."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    bundle_path: Path
    view: TerminalBundleView
    dashboard: BundleDashboardReadModel


class TerminalDashboardPage(BaseModel):
    """The full page model for the terminal UI dashboard."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    catalog: TerminalBundleCatalog
    selected_bundle: TerminalBundleDetail | None = None
    requested_bundle_id: str = ""
    scenario_name: str = ""
    scenario_plan: ScenarioRerunPlan | None = None
    scenario_plan_json: str = ""
    error_message: str = ""


__all__ = [
    "BundleLoadFailure",
    "TerminalBundleCard",
    "TerminalBundleCatalog",
    "TerminalBundleDetail",
    "TerminalDashboardPage",
]
