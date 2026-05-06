"""CLI delivery adapters live here.

Package exports stay lazy so isolated entrypoints such as
`python -m backtest_engine.interfaces.cli.market_data` do not import unrelated
study or runtime flows during package initialization.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from backtest_engine.interfaces.cli.capture_baseline import (
        BaselineCaptureCliCommand,
        BaselineCaptureCliRunner,
        capture_baseline_cli,
    )
    from backtest_engine.interfaces.cli.read_confirmed_folds import (
        ConfirmedFoldsCliCommand,
        ConfirmedFoldsCliRunner,
        read_confirmed_folds_cli,
    )
    from backtest_engine.interfaces.cli.read_latest_recommendation import (
        LatestRecommendationCliCommand,
        LatestRecommendationCliRunner,
        read_latest_recommendation_cli,
    )
    from backtest_engine.interfaces.cli.read_recommendation import (
        RecommendationCliCommand,
        RecommendationCliRunner,
        read_recommendation_cli,
    )
    from backtest_engine.interfaces.cli.read_study_champion import (
        StudyChampionCliCommand,
        StudyChampionCliRunner,
        read_study_champion_cli,
    )
    from backtest_engine.interfaces.cli.read_study_summary import (
        StudySummaryCliCommand,
        StudySummaryCliRunner,
        read_study_summary_cli,
    )
    from backtest_engine.interfaces.cli.run_batch_backtests import (
        BatchBacktestsCliCommand,
        BatchBacktestsCliRunner,
        run_batch_backtests_cli,
    )
    from backtest_engine.interfaces.cli.run_portfolio_backtest import (
        PortfolioBacktestCliCommand,
        PortfolioBacktestCliRunner,
        run_portfolio_backtest_cli,
    )
    from backtest_engine.interfaces.cli.run_portfolio_weight_study import (
        PortfolioWeightStudyCliCommand,
        PortfolioWeightStudyCliRunner,
        run_portfolio_weight_study_cli,
    )
    from backtest_engine.interfaces.cli.run_single_backtest import (
        SingleBacktestCliCommand,
        SingleBacktestCliRunner,
        run_single_backtest_cli,
    )
    from backtest_engine.interfaces.cli.run_spread_calibration import (
        SpreadCalibrationCliCommand,
        SpreadCalibrationDatasetMaterializer,
        run_spread_calibration_cli,
    )
    from backtest_engine.interfaces.cli.run_walk_forward import (
        WalkForwardCliCommand,
        WalkForwardCliRunner,
        run_walk_forward_cli,
    )
    from backtest_engine.interfaces.cli.run_walk_forward_batch import (
        WalkForwardBatchCliCommand,
        WalkForwardBatchCliRunner,
        run_walk_forward_batch_cli,
    )


_EXPORTS: dict[str, tuple[str, str]] = {
    "BaselineCaptureCliCommand": (
        "backtest_engine.interfaces.cli.capture_baseline",
        "BaselineCaptureCliCommand",
    ),
    "BaselineCaptureCliRunner": (
        "backtest_engine.interfaces.cli.capture_baseline",
        "BaselineCaptureCliRunner",
    ),
    "BatchBacktestsCliCommand": (
        "backtest_engine.interfaces.cli.run_batch_backtests",
        "BatchBacktestsCliCommand",
    ),
    "BatchBacktestsCliRunner": (
        "backtest_engine.interfaces.cli.run_batch_backtests",
        "BatchBacktestsCliRunner",
    ),
    "ConfirmedFoldsCliCommand": (
        "backtest_engine.interfaces.cli.read_confirmed_folds",
        "ConfirmedFoldsCliCommand",
    ),
    "ConfirmedFoldsCliRunner": (
        "backtest_engine.interfaces.cli.read_confirmed_folds",
        "ConfirmedFoldsCliRunner",
    ),
    "LatestRecommendationCliCommand": (
        "backtest_engine.interfaces.cli.read_latest_recommendation",
        "LatestRecommendationCliCommand",
    ),
    "LatestRecommendationCliRunner": (
        "backtest_engine.interfaces.cli.read_latest_recommendation",
        "LatestRecommendationCliRunner",
    ),
    "PortfolioBacktestCliCommand": (
        "backtest_engine.interfaces.cli.run_portfolio_backtest",
        "PortfolioBacktestCliCommand",
    ),
    "PortfolioBacktestCliRunner": (
        "backtest_engine.interfaces.cli.run_portfolio_backtest",
        "PortfolioBacktestCliRunner",
    ),
    "PortfolioWeightStudyCliCommand": (
        "backtest_engine.interfaces.cli.run_portfolio_weight_study",
        "PortfolioWeightStudyCliCommand",
    ),
    "PortfolioWeightStudyCliRunner": (
        "backtest_engine.interfaces.cli.run_portfolio_weight_study",
        "PortfolioWeightStudyCliRunner",
    ),
    "RecommendationCliCommand": (
        "backtest_engine.interfaces.cli.read_recommendation",
        "RecommendationCliCommand",
    ),
    "RecommendationCliRunner": (
        "backtest_engine.interfaces.cli.read_recommendation",
        "RecommendationCliRunner",
    ),
    "SingleBacktestCliCommand": (
        "backtest_engine.interfaces.cli.run_single_backtest",
        "SingleBacktestCliCommand",
    ),
    "SingleBacktestCliRunner": (
        "backtest_engine.interfaces.cli.run_single_backtest",
        "SingleBacktestCliRunner",
    ),
    "SpreadCalibrationCliCommand": (
        "backtest_engine.interfaces.cli.run_spread_calibration",
        "SpreadCalibrationCliCommand",
    ),
    "SpreadCalibrationDatasetMaterializer": (
        "backtest_engine.interfaces.cli.run_spread_calibration",
        "SpreadCalibrationDatasetMaterializer",
    ),
    "StudyChampionCliCommand": (
        "backtest_engine.interfaces.cli.read_study_champion",
        "StudyChampionCliCommand",
    ),
    "StudyChampionCliRunner": (
        "backtest_engine.interfaces.cli.read_study_champion",
        "StudyChampionCliRunner",
    ),
    "StudySummaryCliCommand": (
        "backtest_engine.interfaces.cli.read_study_summary",
        "StudySummaryCliCommand",
    ),
    "StudySummaryCliRunner": (
        "backtest_engine.interfaces.cli.read_study_summary",
        "StudySummaryCliRunner",
    ),
    "WalkForwardBatchCliCommand": (
        "backtest_engine.interfaces.cli.run_walk_forward_batch",
        "WalkForwardBatchCliCommand",
    ),
    "WalkForwardBatchCliRunner": (
        "backtest_engine.interfaces.cli.run_walk_forward_batch",
        "WalkForwardBatchCliRunner",
    ),
    "WalkForwardCliCommand": (
        "backtest_engine.interfaces.cli.run_walk_forward",
        "WalkForwardCliCommand",
    ),
    "WalkForwardCliRunner": (
        "backtest_engine.interfaces.cli.run_walk_forward",
        "WalkForwardCliRunner",
    ),
    "capture_baseline_cli": (
        "backtest_engine.interfaces.cli.capture_baseline",
        "capture_baseline_cli",
    ),
    "read_confirmed_folds_cli": (
        "backtest_engine.interfaces.cli.read_confirmed_folds",
        "read_confirmed_folds_cli",
    ),
    "read_latest_recommendation_cli": (
        "backtest_engine.interfaces.cli.read_latest_recommendation",
        "read_latest_recommendation_cli",
    ),
    "read_recommendation_cli": (
        "backtest_engine.interfaces.cli.read_recommendation",
        "read_recommendation_cli",
    ),
    "read_study_champion_cli": (
        "backtest_engine.interfaces.cli.read_study_champion",
        "read_study_champion_cli",
    ),
    "read_study_summary_cli": (
        "backtest_engine.interfaces.cli.read_study_summary",
        "read_study_summary_cli",
    ),
    "run_batch_backtests_cli": (
        "backtest_engine.interfaces.cli.run_batch_backtests",
        "run_batch_backtests_cli",
    ),
    "run_portfolio_backtest_cli": (
        "backtest_engine.interfaces.cli.run_portfolio_backtest",
        "run_portfolio_backtest_cli",
    ),
    "run_portfolio_weight_study_cli": (
        "backtest_engine.interfaces.cli.run_portfolio_weight_study",
        "run_portfolio_weight_study_cli",
    ),
    "run_single_backtest_cli": (
        "backtest_engine.interfaces.cli.run_single_backtest",
        "run_single_backtest_cli",
    ),
    "run_spread_calibration_cli": (
        "backtest_engine.interfaces.cli.run_spread_calibration",
        "run_spread_calibration_cli",
    ),
    "run_walk_forward_batch_cli": (
        "backtest_engine.interfaces.cli.run_walk_forward_batch",
        "run_walk_forward_batch_cli",
    ),
    "run_walk_forward_cli": (
        "backtest_engine.interfaces.cli.run_walk_forward",
        "run_walk_forward_cli",
    ),
}

__all__ = [
    "BaselineCaptureCliCommand",
    "BaselineCaptureCliRunner",
    "BatchBacktestsCliCommand",
    "BatchBacktestsCliRunner",
    "ConfirmedFoldsCliCommand",
    "ConfirmedFoldsCliRunner",
    "LatestRecommendationCliCommand",
    "LatestRecommendationCliRunner",
    "PortfolioBacktestCliCommand",
    "PortfolioBacktestCliRunner",
    "PortfolioWeightStudyCliCommand",
    "PortfolioWeightStudyCliRunner",
    "RecommendationCliCommand",
    "RecommendationCliRunner",
    "SingleBacktestCliCommand",
    "SingleBacktestCliRunner",
    "SpreadCalibrationCliCommand",
    "SpreadCalibrationDatasetMaterializer",
    "StudyChampionCliCommand",
    "StudyChampionCliRunner",
    "StudySummaryCliCommand",
    "StudySummaryCliRunner",
    "WalkForwardBatchCliCommand",
    "WalkForwardBatchCliRunner",
    "WalkForwardCliCommand",
    "WalkForwardCliRunner",
    "capture_baseline_cli",
    "read_confirmed_folds_cli",
    "read_latest_recommendation_cli",
    "read_recommendation_cli",
    "read_study_champion_cli",
    "read_study_summary_cli",
    "run_batch_backtests_cli",
    "run_portfolio_backtest_cli",
    "run_portfolio_weight_study_cli",
    "run_single_backtest_cli",
    "run_spread_calibration_cli",
    "run_walk_forward_batch_cli",
    "run_walk_forward_cli",
]


def __getattr__(name: str) -> Any:
    try:
        module_path, attribute_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    module = import_module(module_path)
    value = getattr(module, attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
