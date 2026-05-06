"""Verdict and stability helpers for portfolio-weight studies."""

from __future__ import annotations

from statistics import median

from backtest_engine.application.optimization.study_contracts import (
    PortfolioWeightStudyControlSpec,
    PortfolioWeightStudyThresholds,
)
from backtest_engine.core.enums import StudyVerdict
from backtest_engine.domain.artifacts.studies import PortfolioWeightStudyFoldResult


def compute_study_verdict(
    *,
    fold_results: tuple[PortfolioWeightStudyFoldResult, ...],
    thresholds: PortfolioWeightStudyThresholds,
    control: PortfolioWeightStudyControlSpec,
) -> StudyVerdict:
    """Compute the deterministic PASS/WARNING/FAIL verdict for the study."""

    scored_folds = tuple(fold for fold in fold_results if not fold.execution_failed)
    if not scored_folds:
        return StudyVerdict.FAIL
    majority_threshold = len(scored_folds) // 2
    trade_insufficient_count = sum(1 for fold in scored_folds if fold.trade_insufficient)
    execution_failures = sum(1 for fold in fold_results if fold.execution_failed)
    hard_drawdown_breach = any(
        fold.max_drawdown >= thresholds.hard_drawdown_frac for fold in scored_folds
    )
    median_oos_sharpe = median_metric(tuple(fold.sharpe_after_costs for fold in scored_folds))
    stable_recommendation = is_stable_recommendation_candidate(
        confirmed_fold_weights=tuple(fold.champion_weights for fold in scored_folds if fold.champion_weights),
        weight_step_frac=control.weight_step_frac,
    )
    if (
        hard_drawdown_breach
        or median_oos_sharpe <= 0.0
        or trade_insufficient_count > majority_threshold
        or execution_failures > majority_threshold
        or not any(fold.champion_weights for fold in scored_folds)
    ):
        return StudyVerdict.FAIL
    quality_profitable_flags = tuple(fold.quality_profitable for fold in scored_folds)
    quality_profitable_count = sum(1 for value in quality_profitable_flags if value)
    if (
        quality_profitable_count >= thresholds.min_quality_profitable_folds
        and max_consecutive_true(quality_profitable_flags)
        >= thresholds.min_consecutive_quality_profitable_folds
        and stable_recommendation
    ):
        return StudyVerdict.PASS
    return StudyVerdict.WARNING


def is_stable_recommendation_candidate(
    *,
    confirmed_fold_weights: tuple[dict[str, float], ...],
    weight_step_frac: float,
) -> bool:
    """Check whether the latest champion is stable relative to fold medians."""

    if not confirmed_fold_weights:
        return False
    if len(confirmed_fold_weights) == 1:
        return True
    latest = confirmed_fold_weights[-1]
    slot_ids = tuple(latest.keys())
    medians = {
        slot_id: median(tuple(weights.get(slot_id, 0.0) for weights in confirmed_fold_weights))
        for slot_id in slot_ids
    }
    tolerance = max(weight_step_frac * 5.0, 0.10)
    return all(abs(float(latest[slot_id]) - float(medians[slot_id])) <= tolerance for slot_id in slot_ids)


def median_metric(values: tuple[float, ...]) -> float:
    """Return a numeric median with an empty-sequence fallback."""

    if not values:
        return 0.0
    return float(median(values))


def max_consecutive_true(values: tuple[bool, ...]) -> int:
    """Return the longest consecutive run of truthy values."""

    max_run = 0
    current_run = 0
    for value in values:
        if value:
            current_run += 1
            max_run = max(max_run, current_run)
        else:
            current_run = 0
    return max_run


__all__ = [
    "compute_study_verdict",
    "is_stable_recommendation_candidate",
    "max_consecutive_true",
    "median_metric",
]
