"""Artifact builders and publication policy for portfolio-weight studies."""

from __future__ import annotations

from datetime import datetime, timedelta

from backtest_engine.application.optimization.study_contracts import (
    PortfolioWeightStudyCommand,
)
from backtest_engine.application.optimization.study_verdict import (
    is_stable_recommendation_candidate,
    median_metric,
)
from backtest_engine.core.enums import RecommendationStatus, StudyVerdict
from backtest_engine.core.time import ensure_utc
from backtest_engine.domain.artifacts.studies import (
    LiveAllocationRecommendationArtifact,
    PortfolioWeightStudyArtifact,
    PortfolioWeightStudyFoldResult,
    StudyChampionArtifact,
    build_recommendation_artifact_id,
)


def build_study_artifact(
    *,
    command: PortfolioWeightStudyCommand,
    created_at_utc: datetime,
    fold_results: tuple[PortfolioWeightStudyFoldResult, ...],
    source_bundle_uris: tuple[str, ...],
) -> PortfolioWeightStudyArtifact:
    """Build the persisted study summary payload."""

    confirmed_fold_weights = tuple(fold.champion_weights for fold in fold_results if fold.champion_weights)
    champion_weights = confirmed_fold_weights[-1] if confirmed_fold_weights else {}
    return PortfolioWeightStudyArtifact(
        study_id=command.study_spec.study_id,
        created_at_utc=ensure_utc(created_at_utc),
        objective_metric=command.study_spec.objective_metric,
        verdict=StudyVerdict.FAIL,
        fold_count=len(fold_results),
        trial_count=0,
        median_oos_score=median_metric(tuple(fold.sharpe_after_costs for fold in fold_results)),
        median_oos_sharpe=median_metric(tuple(fold.sharpe_after_costs for fold in fold_results)),
        pass_folds=sum(1 for fold in fold_results if fold.quality_profitable),
        warning_folds=sum(1 for fold in fold_results if not fold.execution_failed and not fold.quality_profitable),
        fail_folds=sum(1 for fold in fold_results if fold.execution_failed),
        champion_weights=champion_weights,
        source_bundle_uris=tuple(dict.fromkeys(source_bundle_uris)),
        summary={
            "requested_by": command.requested_by,
            "seed": command.study_spec.seed,
            "weight_step_frac": command.study_spec.control.weight_step_frac,
            "max_sleeve_weight_frac": command.study_spec.control.max_sleeve_weight_frac,
            "top_k_confirm": command.study_spec.control.top_k_confirm,
            "trial_budget_mode": (
                "fixed"
                if command.study_spec.control.trial_budget is not None
                else "adaptive_by_eligible_sleeves"
            ),
            "stable_recommendation_candidate": is_stable_recommendation_candidate(
                confirmed_fold_weights=confirmed_fold_weights,
                weight_step_frac=command.study_spec.control.weight_step_frac,
            ),
        },
    )


def apply_study_verdict(
    *,
    artifact: PortfolioWeightStudyArtifact,
    verdict: StudyVerdict,
    trial_count: int,
) -> PortfolioWeightStudyArtifact:
    """Apply verdict and trial-count fields after orchestration finishes."""

    return artifact.model_copy(update={"verdict": verdict, "trial_count": int(trial_count)})


def build_champion_artifact(
    *,
    study_id: str,
    created_at_utc: datetime,
    verdict: StudyVerdict,
    latest_confirmed_fold: PortfolioWeightStudyFoldResult | None,
) -> StudyChampionArtifact:
    """Build the explicit champion artifact for delivery surfaces."""

    champion_weights = latest_confirmed_fold.champion_weights if latest_confirmed_fold else {}
    return StudyChampionArtifact(
        study_id=study_id,
        created_at_utc=ensure_utc(created_at_utc),
        verdict=verdict,
        champion_weights=champion_weights,
        source_fold_id=latest_confirmed_fold.fold_id if latest_confirmed_fold else None,
        source_candidate_id=latest_confirmed_fold.selected_candidate_id if latest_confirmed_fold else None,
        summary={
            "effective_end_utc": (
                latest_confirmed_fold.effective_end_utc.isoformat()
                if latest_confirmed_fold and latest_confirmed_fold.effective_end_utc is not None
                else None
            ),
        },
    )


def build_recommendation_artifact(
    *,
    command: PortfolioWeightStudyCommand,
    created_at_utc: datetime,
    latest_confirmed_fold: PortfolioWeightStudyFoldResult | None,
    verdict: StudyVerdict,
) -> LiveAllocationRecommendationArtifact:
    """Build the fail-closed recommendation payload."""

    study_spec = command.study_spec
    control = study_spec.control
    source_window_start_utc = (
        latest_confirmed_fold.effective_start_utc
        if latest_confirmed_fold and latest_confirmed_fold.effective_start_utc is not None
        else study_spec.folds[-1].out_of_sample_run_spec.execution_window.start_utc
    )
    source_window_end_utc = (
        latest_confirmed_fold.effective_end_utc
        if latest_confirmed_fold and latest_confirmed_fold.effective_end_utc is not None
        else study_spec.folds[-1].out_of_sample_run_spec.execution_window.end_utc
    )
    stale_cutoff = ensure_utc(created_at_utc) - timedelta(
        days=study_spec.control.verdict_thresholds.max_recommendation_age_days
    )
    is_stale = ensure_utc(source_window_end_utc) < stale_cutoff
    champion_weights = latest_confirmed_fold.champion_weights if latest_confirmed_fold else {}

    status = RecommendationStatus.BLOCKED
    publication_blockers: list[str] = ["runtime_policy_parity_pending"]
    if verdict is StudyVerdict.FAIL:
        publication_blockers.append("study_verdict_fail")
    elif verdict is StudyVerdict.WARNING:
        publication_blockers.append("study_verdict_warning")
    if is_stale:
        publication_blockers.append("stale_confirmatory_analytics")
    if not champion_weights:
        publication_blockers.append("missing_champion_weights")

    recommendation_id = build_recommendation_artifact_id(
        study_id=study_spec.study_id,
        created_at_utc=ensure_utc(created_at_utc),
        source_window_start_utc=ensure_utc(source_window_start_utc),
        source_window_end_utc=ensure_utc(source_window_end_utc),
        status=status,
        target_portfolio_vol_frac=study_spec.execution_policy.target_portfolio_vol_frac,
        weight_step_frac=control.weight_step_frac,
        max_sleeve_weight_frac=control.max_sleeve_weight_frac,
        top_k_confirm=control.top_k_confirm,
        champion_weights=champion_weights,
    )
    return LiveAllocationRecommendationArtifact(
        recommendation_id=recommendation_id,
        study_id=study_spec.study_id,
        as_of_utc=ensure_utc(created_at_utc),
        source_window_start_utc=ensure_utc(source_window_start_utc),
        source_window_end_utc=ensure_utc(source_window_end_utc),
        status=status,
        target_portfolio_vol_frac=study_spec.execution_policy.target_portfolio_vol_frac,
        weight_step_frac=control.weight_step_frac,
        max_sleeve_weight_frac=control.max_sleeve_weight_frac,
        top_k_confirm=control.top_k_confirm,
        champion_weights=champion_weights,
        summary={
            "requested_by": command.requested_by,
            "stale_source_window": is_stale,
            "operator_override_required": False,
            "publication_blockers": publication_blockers,
        },
    )


__all__ = [
    "apply_study_verdict",
    "build_champion_artifact",
    "build_recommendation_artifact",
    "build_study_artifact",
]
