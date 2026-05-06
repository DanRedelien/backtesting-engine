"""Portfolio-weight study orchestration with shared causal sizing semantics."""

from __future__ import annotations

from typing import Any

from backtest_engine.application.optimization.study_confirm import confirm_candidate
from backtest_engine.application.optimization.study_contracts import (
    PortfolioWeightStudyCommand,
    PortfolioWeightStudyControlSpec,
    PortfolioWeightStudyDependencies,
    PortfolioWeightStudyFoldSpec,
    PortfolioWeightStudyRunResult,
    PortfolioWeightStudySpec,
    PortfolioWeightStudyThresholds,
    StudyArtifactStore,
    StudyPortfolioExecutor,
    StudySingleExecutor,
)
from backtest_engine.application.optimization.study_publication import (
    apply_study_verdict,
    build_champion_artifact,
    build_recommendation_artifact,
    build_study_artifact,
)
from backtest_engine.application.optimization.study_search import (
    build_approximate_trial_row,
    candidate_id,
    load_fold_sleeve_analytics,
    normalize_capped_simplex,
    returns_frame_is_eligible,
    select_confirm_candidates,
    simulate_candidate,
)
from backtest_engine.application.optimization.study_verdict import compute_study_verdict
from backtest_engine.core.types import JsonValue
from backtest_engine.domain.artifacts.studies import PortfolioWeightStudyFoldResult
from backtest_engine.infrastructure.optimization.optuna_runtime import require_optuna, silence_optuna_logs


def run_portfolio_weight_study(
    command: PortfolioWeightStudyCommand,
    dependencies: PortfolioWeightStudyDependencies,
) -> PortfolioWeightStudyRunResult:
    """Run staged portfolio-weight search and persist typed study artifacts."""

    optuna = require_optuna()
    created_at_utc = dependencies.clock.now_utc()
    trial_rows: list[dict[str, JsonValue]] = []
    fold_results: list[PortfolioWeightStudyFoldResult] = []
    source_bundle_uris: list[str] = []

    with silence_optuna_logs():
        for fold in command.study_spec.folds:
            fold_result, fold_trial_rows, fold_sources = _run_fold_study(
                fold=fold,
                command=command,
                dependencies=dependencies,
                optuna=optuna,
            )
            fold_results.append(fold_result)
            trial_rows.extend(fold_trial_rows)
            source_bundle_uris.extend(fold_sources)

    verdict = compute_study_verdict(
        fold_results=tuple(fold_results),
        thresholds=command.study_spec.control.verdict_thresholds,
        control=command.study_spec.control,
    )
    latest_confirmed_fold = next(
        (fold for fold in reversed(fold_results) if not fold.execution_failed and fold.champion_weights),
        None,
    )
    study_artifact = apply_study_verdict(
        artifact=build_study_artifact(
            command=command,
            created_at_utc=created_at_utc,
            fold_results=tuple(fold_results),
            source_bundle_uris=tuple(source_bundle_uris),
        ),
        verdict=verdict,
        trial_count=len(trial_rows),
    )
    champion = build_champion_artifact(
        study_id=command.study_spec.study_id,
        created_at_utc=created_at_utc,
        verdict=verdict,
        latest_confirmed_fold=latest_confirmed_fold,
    )
    saved_study = dependencies.artifact_store.save_study(
        study_artifact,
        folds=tuple(fold_results),
        champion=champion,
        trial_rows=tuple(trial_rows),
    )
    recommendation = build_recommendation_artifact(
        command=command,
        created_at_utc=created_at_utc,
        latest_confirmed_fold=latest_confirmed_fold,
        verdict=verdict,
    )
    saved_recommendation = dependencies.artifact_store.save_recommendation(recommendation)
    return PortfolioWeightStudyRunResult(
        study_id=saved_study.study_id,
        study_uri=saved_study.study_uri,
        champion_uri=saved_study.champion_uri,
        recommendation_id=saved_recommendation.recommendation_id,
        recommendation_uri=saved_recommendation.recommendation_uri,
        latest_recommendation_uri=saved_recommendation.latest_recommendation_uri,
        verdict=verdict,
        recommendation_status=recommendation.status,
        champion_weights=recommendation.champion_weights,
    )


def _run_fold_study(
    *,
    fold: PortfolioWeightStudyFoldSpec,
    command: PortfolioWeightStudyCommand,
    dependencies: PortfolioWeightStudyDependencies,
    optuna: Any,
) -> tuple[PortfolioWeightStudyFoldResult, list[dict[str, JsonValue]], list[str]]:
    study_spec = command.study_spec
    control = study_spec.control
    execution_policy = study_spec.execution_policy
    slot_ids = tuple(strategy.slot_id for strategy in fold.in_sample_run_spec.strategies)

    in_sample_analytics, in_sample_sources = load_fold_sleeve_analytics(
        fold=fold,
        single_executor=dependencies.single_executor,
        bundle_loader=dependencies.bundle_loader,
        requested_by=command.requested_by,
        correlation_id=command.correlation_id,
        phase="in_sample",
    )
    out_of_sample_analytics, out_of_sample_sources = load_fold_sleeve_analytics(
        fold=fold,
        single_executor=dependencies.single_executor,
        bundle_loader=dependencies.bundle_loader,
        requested_by=command.requested_by,
        correlation_id=command.correlation_id,
        phase="out_of_sample",
    )
    source_bundle_uris = list(in_sample_sources) + list(out_of_sample_sources)
    eligible_slots = tuple(
        slot_id
        for slot_id in slot_ids
        if returns_frame_is_eligible(
            in_sample_analytics[slot_id],
            lookback_bars=execution_policy.vol_lookback_bars,
        )
    )
    if not eligible_slots:
        return (
            PortfolioWeightStudyFoldResult(
                study_id=study_spec.study_id,
                fold_id=fold.fold_id,
                eligible_slots=tuple(),
                execution_failed=True,
                summary={"reason": "no eligible sleeves"},
            ),
            [],
            source_bundle_uris,
        )
    if len(eligible_slots) * float(control.max_sleeve_weight_frac) + 1e-9 < 1.0:
        return (
            PortfolioWeightStudyFoldResult(
                study_id=study_spec.study_id,
                fold_id=fold.fold_id,
                eligible_slots=eligible_slots,
                execution_failed=True,
                summary={"reason": "eligible sleeves cannot satisfy max_sleeve_weight_frac"},
            ),
            [],
            source_bundle_uris,
        )

    completed_trials: list[dict[str, JsonValue]] = []
    sampler = optuna.samplers.TPESampler(seed=study_spec.seed)
    fold_study = optuna.create_study(direction="maximize", sampler=sampler)
    trial_budget = control.resolve_trial_budget(eligible_sleeves=len(eligible_slots))

    def _objective(trial: Any) -> float:
        raw_alphas: dict[str, float] = {}
        for slot_id in slot_ids:
            if slot_id not in eligible_slots:
                raw_alphas[slot_id] = 0.0
                continue
            raw_alphas[slot_id] = float(
                trial.suggest_float(
                    f"alpha_{slot_id}",
                    0.0,
                    control.max_sleeve_weight_frac,
                    step=control.weight_step_frac,
                )
            )
        candidate_weights = normalize_capped_simplex(
            raw_alphas=raw_alphas,
            eligible_slots=eligible_slots,
            base_weights={
                strategy.slot_id: float(strategy.weight_frac)
                for strategy in fold.in_sample_run_spec.strategies
            },
            max_weight_frac=control.max_sleeve_weight_frac,
        )
        evaluation = simulate_candidate(
            analytics_by_slot=in_sample_analytics,
            target_weights=candidate_weights,
            execution_policy=execution_policy,
        )
        objective_value = evaluation.sharpe_after_costs
        min_effective_oos_bars = control.min_effective_oos_bars
        if min_effective_oos_bars is None:
            raise ValueError("control.min_effective_oos_bars must resolve to a concrete value")
        if evaluation.effective_bar_count < min_effective_oos_bars:
            objective_value = -1e9
        trial.set_user_attr("candidate_id", candidate_id(candidate_weights))
        trial.set_user_attr("candidate_weights", candidate_weights)
        trial.set_user_attr("effective_bar_count", evaluation.effective_bar_count)
        completed_trials.append(
            build_approximate_trial_row(
                study_id=study_spec.study_id,
                fold_id=fold.fold_id,
                trial_number=int(trial.number),
                candidate_weights=candidate_weights,
                evaluation=evaluation,
            )
            | {
                "objective_value": objective_value,
                "resolved_trial_budget": float(trial_budget),
            }
        )
        return objective_value

    fold_study.optimize(_objective, n_trials=trial_budget)
    confirm_candidates = select_confirm_candidates(
        fold_study=fold_study,
        top_k_confirm=control.top_k_confirm,
    )
    confirmed_rows: list[dict[str, JsonValue]] = []
    confirmed_results: list[PortfolioWeightStudyFoldResult] = []
    for candidate in confirm_candidates:
        candidate_weights = dict(candidate["candidate_weights"])
        evaluation = simulate_candidate(
            analytics_by_slot=out_of_sample_analytics,
            target_weights=candidate_weights,
            execution_policy=execution_policy,
        )
        confirmed_fold, confirm_row = confirm_candidate(
            study_id=study_spec.study_id,
            fold_id=fold.fold_id,
            candidate_rank=candidate["is_rank"],
            candidate_id=candidate["candidate_id"],
            candidate_weights=candidate_weights,
            evaluation=evaluation,
            eligible_slots=eligible_slots,
            thresholds=control.verdict_thresholds,
            control=control,
            portfolio_executor=dependencies.portfolio_executor,
            out_of_sample_run_spec=fold.out_of_sample_run_spec,
            requested_by=command.requested_by,
            correlation_id=command.correlation_id,
        )
        confirmed_rows.append(confirm_row)
        if confirmed_fold is not None:
            confirmed_results.append(confirmed_fold)

    if not confirmed_results:
        return (
            PortfolioWeightStudyFoldResult(
                study_id=study_spec.study_id,
                fold_id=fold.fold_id,
                eligible_slots=eligible_slots,
                execution_failed=True,
                summary={"reason": "no confirmed candidate"},
            ),
            completed_trials + confirmed_rows,
            source_bundle_uris,
        )
    selected_fold = confirmed_results[0]
    return selected_fold, completed_trials + confirmed_rows, source_bundle_uris


__all__ = [
    "PortfolioWeightStudyCommand",
    "PortfolioWeightStudyControlSpec",
    "PortfolioWeightStudyDependencies",
    "PortfolioWeightStudyFoldSpec",
    "PortfolioWeightStudyRunResult",
    "PortfolioWeightStudySpec",
    "PortfolioWeightStudyThresholds",
    "StudyArtifactStore",
    "StudyPortfolioExecutor",
    "StudySingleExecutor",
    "run_portfolio_weight_study",
]
