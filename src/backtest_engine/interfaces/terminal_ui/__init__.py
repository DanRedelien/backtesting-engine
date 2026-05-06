"""Terminal UI delivery adapters and app factory live here."""

from backtest_engine.interfaces.terminal_ui.app import app, create_terminal_ui_app
from backtest_engine.interfaces.terminal_ui.prepare_scenario_rerun import (
    ScenarioRerunPlan,
    ScenarioRerunRequest,
    ScenarioRerunService,
    prepare_scenario_rerun,
)
from backtest_engine.interfaces.terminal_ui.read_recommendation import (
    RecommendationRequest,
    RecommendationService,
    read_recommendation,
)
from backtest_engine.interfaces.terminal_ui.read_confirmed_folds import (
    ConfirmedFoldsRequest,
    ConfirmedFoldsService,
    read_confirmed_folds,
)
from backtest_engine.interfaces.terminal_ui.read_latest_recommendation import (
    LatestRecommendationRequest,
    LatestRecommendationService,
    read_latest_recommendation,
)
from backtest_engine.interfaces.terminal_ui.read_study_champion import (
    StudyChampionRequest,
    StudyChampionService,
    read_study_champion,
)
from backtest_engine.interfaces.terminal_ui.read_bundle_summary import (
    BundleSummaryRequest,
    BundleSummaryService,
    read_bundle_summary,
)
from backtest_engine.interfaces.terminal_ui.read_study_summary import (
    StudySummaryRequest,
    StudySummaryService,
    read_study_summary,
)
from backtest_engine.interfaces.terminal_ui.read_bundle_view import (
    BundleViewRequest,
    BundleViewService,
    TerminalBundleView,
    read_bundle_view,
)

__all__ = [
    "BundleSummaryRequest",
    "BundleSummaryService",
    "BundleViewRequest",
    "BundleViewService",
    "ConfirmedFoldsRequest",
    "ConfirmedFoldsService",
    "LatestRecommendationRequest",
    "LatestRecommendationService",
    "RecommendationRequest",
    "RecommendationService",
    "ScenarioRerunPlan",
    "ScenarioRerunRequest",
    "ScenarioRerunService",
    "StudyChampionRequest",
    "StudyChampionService",
    "StudySummaryRequest",
    "StudySummaryService",
    "TerminalBundleView",
    "app",
    "create_terminal_ui_app",
    "prepare_scenario_rerun",
    "read_confirmed_folds",
    "read_latest_recommendation",
    "read_recommendation",
    "read_bundle_summary",
    "read_study_champion",
    "read_bundle_view",
    "read_study_summary",
]
