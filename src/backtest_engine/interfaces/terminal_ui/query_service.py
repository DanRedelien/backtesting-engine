"""Filesystem-backed query orchestration for the V2 terminal UI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

from backtest_engine.analytics.read_models import BundleDashboardReadModel, BundleReadModel
from backtest_engine.core.errors import BacktestEngineError, InfrastructureError
from backtest_engine.domain.artifacts.bundles import ResultBundle
from backtest_engine.interfaces.terminal_ui.prepare_scenario_rerun import (
    ScenarioRerunPlan,
    ScenarioRerunRequest,
    prepare_scenario_rerun,
)
from backtest_engine.interfaces.terminal_ui.read_bundle_summary import (
    BundleSummaryRequest,
    read_bundle_summary,
)
from backtest_engine.analytics.read_models import (
    ConfirmedFoldCollectionReadModel,
    LiveAllocationRecommendationReadModel,
    StudyChampionReadModel,
    StudySummaryReadModel,
    load_confirmed_fold_collection_read_model,
    load_latest_live_allocation_recommendation_read_model,
    load_live_allocation_recommendation_read_model,
    load_study_champion_read_model,
    load_study_summary_read_model,
)
from backtest_engine.interfaces.terminal_ui.read_bundle_view import (
    BundleViewRequest,
    read_bundle_view,
)
from backtest_engine.interfaces.terminal_ui.view_models import (
    BundleLoadFailure,
    TerminalBundleCard,
    TerminalBundleCatalog,
    TerminalBundleDetail,
    TerminalDashboardPage,
)


_BUNDLE_FILENAME = "bundle.json"


class TerminalUiContainer(Protocol):
    """Read-only bundle access used by the terminal UI query surface."""

    def load_bundle_read_model(self, bundle_path: Path) -> BundleReadModel:
        """Return one persisted read model."""
        ...

    def load_bundle_dashboard_read_model(self, bundle_path: Path) -> BundleDashboardReadModel:
        """Return one persisted dashboard read model."""
        ...

    def load_bundle(self, bundle_path: Path) -> ResultBundle:
        """Return one persisted bundle contract."""
        ...


@dataclass(frozen=True)
class TerminalUiQueryService:
    """Load V2 bundle views for the terminal UI without legacy runtime code."""

    container: TerminalUiContainer | object
    results_root: Path

    def load_bundle_catalog(self) -> TerminalBundleCatalog:
        """Discover saved V2 bundles and project them into compact cards."""

        cards: list[TerminalBundleCard] = []
        failures: list[BundleLoadFailure] = []
        for bundle_path in self._discover_bundle_paths():
            try:
                summary = read_bundle_summary(
                    command=BundleSummaryRequest(bundle_path=bundle_path),
                    service=self._bundle_service(),
                )
            except BacktestEngineError as exc:
                failures.append(
                    BundleLoadFailure(
                        bundle_path=bundle_path,
                        message=self._format_error_message(exc),
                    )
                )
                continue
            cards.append(TerminalBundleCard.from_summary(bundle_path=bundle_path, summary=summary))

        cards.sort(key=lambda card: card.created_at_utc, reverse=True)
        return TerminalBundleCatalog(
            bundles=tuple(cards),
            load_failures=tuple(failures),
        )

    def load_bundle_detail(self, bundle_id: str) -> TerminalBundleDetail:
        """Load one detailed bundle view by bundle identifier."""

        bundle_path = self._resolve_bundle_path(bundle_id)
        view = read_bundle_view(
            command=BundleViewRequest(bundle_path=bundle_path),
            service=self._bundle_service(),
        )
        dashboard = self._bundle_service().load_bundle_dashboard_read_model(bundle_path)
        return TerminalBundleDetail(
            bundle_path=bundle_path,
            view=view,
            dashboard=dashboard,
        )

    def build_scenario_plan(
        self,
        *,
        bundle_id: str,
        scenario_name: str,
        requested_by: str,
    ) -> ScenarioRerunPlan:
        """Build one canonical scenario rerun plan for a saved bundle."""

        bundle_path = self._resolve_bundle_path(bundle_id)
        return prepare_scenario_rerun(
            command=ScenarioRerunRequest(
                bundle_path=bundle_path,
                scenario_name=scenario_name,
                requested_by=requested_by,
            ),
            service=self._bundle_service(),
        )

    def load_study_summary(self, artifact_path: Path) -> StudySummaryReadModel:
        """Load one persisted study summary artifact."""

        return load_study_summary_read_model(artifact_path)

    def load_recommendation(
        self,
        artifact_path: Path,
    ) -> LiveAllocationRecommendationReadModel:
        """Load one persisted live allocation recommendation artifact."""

        return load_live_allocation_recommendation_read_model(artifact_path)

    def load_confirmed_folds(self, artifact_path: Path) -> ConfirmedFoldCollectionReadModel:
        """Load one persisted confirmed-fold artifact."""

        return load_confirmed_fold_collection_read_model(artifact_path)

    def load_study_champion(self, artifact_path: Path) -> StudyChampionReadModel:
        """Load one persisted study champion artifact."""

        return load_study_champion_read_model(artifact_path)

    def load_latest_recommendation(self, results_root: Path) -> LiveAllocationRecommendationReadModel:
        """Load the explicit latest recommendation surface."""

        return load_latest_live_allocation_recommendation_read_model(results_root)

    def build_dashboard_page(
        self,
        *,
        selected_bundle_id: str | None = None,
        scenario_name: str = "",
        requested_by: str = "terminal_ui",
    ) -> TerminalDashboardPage:
        """Build the full dashboard page model from the current results root."""

        catalog = self.load_bundle_catalog()
        requested_bundle_id = (selected_bundle_id or "").strip()
        error_message = ""
        selected_bundle: TerminalBundleDetail | None = None
        selected_id = requested_bundle_id or self._default_bundle_id(catalog)

        if selected_id:
            try:
                selected_bundle = self.load_bundle_detail(selected_id)
            except BacktestEngineError as exc:
                error_message = self._format_error_message(exc)
                fallback_id = self._default_bundle_id(catalog)
                if fallback_id and fallback_id != selected_id:
                    selected_bundle = self.load_bundle_detail(fallback_id)
                    selected_id = fallback_id

        return TerminalDashboardPage(
            catalog=catalog,
            selected_bundle=selected_bundle,
            requested_bundle_id=selected_id,
            scenario_name=scenario_name.strip(),
            scenario_plan=None,
            scenario_plan_json="",
            error_message=error_message,
        )

    def _discover_bundle_paths(self) -> tuple[Path, ...]:
        if not self.results_root.exists():
            return tuple()

        bundle_paths: list[Path] = []
        for child in sorted(self.results_root.iterdir()):
            bundle_path = child / _BUNDLE_FILENAME
            if child.is_dir() and bundle_path.is_file():
                bundle_paths.append(bundle_path)
        return tuple(bundle_paths)

    def _resolve_bundle_path(self, bundle_id: str) -> Path:
        clean_bundle_id = bundle_id.strip()
        if not clean_bundle_id or Path(clean_bundle_id).name != clean_bundle_id:
            raise InfrastructureError("bundle id is invalid", bundle_id=bundle_id)

        bundle_path = self.results_root / clean_bundle_id / _BUNDLE_FILENAME
        if not bundle_path.is_file():
            raise InfrastructureError(
                "result bundle was not found",
                bundle_id=clean_bundle_id,
                bundle_path=str(bundle_path),
            )
        return bundle_path

    @staticmethod
    def _default_bundle_id(catalog: TerminalBundleCatalog) -> str:
        if not catalog.bundles:
            return ""
        return catalog.bundles[0].bundle_id

    @staticmethod
    def _format_error_message(exc: BacktestEngineError) -> str:
        if not exc.context:
            return exc.message
        context_parts = ", ".join(f"{key}={value}" for key, value in sorted(exc.context.items()))
        return f"{exc.message} ({context_parts})"

    def _bundle_service(self) -> TerminalUiContainer:
        return cast(TerminalUiContainer, self.container)


__all__ = ["TerminalUiQueryService"]
