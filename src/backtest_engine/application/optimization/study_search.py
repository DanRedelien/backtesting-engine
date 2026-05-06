"""Search helpers for portfolio-weight studies."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TypedDict

import pandas as pd

from backtest_engine.application.optimization.study_contracts import (
    PortfolioWeightStudyControlSpec,
    PortfolioWeightStudyFoldSpec,
    StudySingleExecutor,
)
from backtest_engine.application.single.run_single_backtest import SingleRunCommand
from backtest_engine.config.runtime import BacktestRunSpec, PortfolioExecutionPolicy
from backtest_engine.core.errors import ApplicationError, InfrastructureError
from backtest_engine.core.types import JsonValue
from backtest_engine.domain.portfolio.sizing import (
    PortfolioSizingRun,
    SleeveAnalyticsFrame,
    build_sleeve_analytics_frame,
    evaluate_portfolio_sizing_run,
)
from backtest_engine.domain.strategy.specifications import PortfolioStrategySpec
from backtest_engine.infrastructure.artifacts.bundle_loader import BundleLoader


class ConfirmCandidate(TypedDict):
    """Typed confirmatory candidate projection from Optuna user attrs."""

    candidate_id: str
    candidate_weights: dict[str, float]
    is_rank: int


def build_sleeve_run_spec(
    run_spec: BacktestRunSpec,
    strategy_spec: PortfolioStrategySpec,
) -> BacktestRunSpec:
    """Build a canonical single-sleeve run spec from one portfolio slot."""

    from backtest_engine.core.enums import RunKind

    return BacktestRunSpec(
        run_kind=RunKind.SINGLE,
        runtime_boundary=run_spec.runtime_boundary,
        execution_window=run_spec.execution_window,
        dataset=run_spec.dataset,
        strategies=(strategy_spec,),
        capital_base=run_spec.capital_base,
        semantic_policy_version=run_spec.semantic_policy_version,
        tags=run_spec.tags,
    )


def load_fold_sleeve_analytics(
    *,
    fold: PortfolioWeightStudyFoldSpec,
    single_executor: StudySingleExecutor,
    bundle_loader: BundleLoader,
    requested_by: str,
    correlation_id: str | None,
    phase: str,
) -> tuple[dict[str, SleeveAnalyticsFrame], list[str]]:
    """Run single-sleeve executions and load normalized analytics frames."""

    if phase not in {"in_sample", "out_of_sample"}:
        raise ValueError("phase must be in_sample or out_of_sample")
    fold_run_spec = (
        fold.in_sample_run_spec if phase == "in_sample" else fold.out_of_sample_run_spec
    )
    analytics_by_slot: dict[str, SleeveAnalyticsFrame] = {}
    source_bundle_uris: list[str] = []
    for strategy_spec in fold_run_spec.strategies:
        single_result = single_executor.run(
            command=SingleRunCommand(
                requested_by=requested_by,
                correlation_id=correlation_id,
            ),
            run_spec=build_sleeve_run_spec(fold_run_spec, strategy_spec),
        )
        source_bundle_uris.append(single_result.bundle_uri)
        analytics_by_slot[strategy_spec.slot_id] = load_sleeve_analytics_from_bundle(
            bundle_loader=bundle_loader,
            bundle_uri=single_result.bundle_uri,
            slot_id=strategy_spec.slot_id,
        )
    return analytics_by_slot, source_bundle_uris


def load_sleeve_analytics_from_bundle(
    *,
    bundle_loader: BundleLoader,
    bundle_uri: str,
    slot_id: str,
) -> SleeveAnalyticsFrame:
    """Load one normalized sleeve analytics frame from a bundle returns report."""

    bundle = bundle_loader.load_bundle(Path(bundle_uri))
    returns_report_uri = bundle.artifact_locations.get("returns_report")
    if returns_report_uri is None:
        raise InfrastructureError(
            "bundle does not contain returns_report artifact",
            bundle_uri=bundle_uri,
        )
    frame = pd.read_parquet(Path(returns_report_uri))
    if "timestamp_utc" not in frame.columns:
        frame = frame.copy()
        frame["timestamp_utc"] = pd.RangeIndex(start=0, stop=len(frame))
    if "return_after_costs" not in frame.columns:
        raise InfrastructureError(
            "returns_report is missing return_after_costs column",
            bundle_uri=bundle_uri,
            artifact_path=returns_report_uri,
        )
    normalized = pd.DataFrame(
        {
            "timestamp_utc": frame["timestamp_utc"],
            "unit_return_after_costs": pd.to_numeric(frame["return_after_costs"], errors="coerce"),
            "unit_turnover": pd.to_numeric(
                frame["turnover"] if "turnover" in frame.columns else pd.Series(0.0, index=frame.index),
                errors="coerce",
            ).fillna(0.0),
            "is_active": pd.to_numeric(frame["return_after_costs"], errors="coerce").notna(),
            "has_valid_history": True,
            "gross_exposure": pd.to_numeric(
                frame["gross_exposure"]
                if "gross_exposure" in frame.columns
                else pd.Series(1.0, index=frame.index),
                errors="coerce",
            ).fillna(1.0),
            "costs": pd.to_numeric(
                frame["costs"] if "costs" in frame.columns else pd.Series(0.0, index=frame.index),
                errors="coerce",
            ).fillna(0.0),
        }
    )
    return build_sleeve_analytics_frame(slot_id=slot_id, frame=normalized)


def returns_frame_is_eligible(frame: SleeveAnalyticsFrame, *, lookback_bars: int) -> bool:
    """Check whether a sleeve has enough valid history to enter the search universe."""

    valid_count = int(frame.frame["unit_return_after_costs"].dropna().shape[0])
    return valid_count >= lookback_bars


def normalize_capped_simplex(
    *,
    raw_alphas: dict[str, float],
    eligible_slots: tuple[str, ...],
    base_weights: dict[str, float],
    max_weight_frac: float,
) -> dict[str, float]:
    """Normalize candidate weights into a capped long-only simplex."""

    if len(eligible_slots) * max_weight_frac + 1e-9 < 1.0:
        raise ApplicationError(
            "eligible sleeve universe cannot satisfy max_sleeve_weight_frac",
            eligible_sleeves=len(eligible_slots),
            max_sleeve_weight_frac=max_weight_frac,
        )
    working_raw = {
        slot_id: max(float(raw_alphas.get(slot_id, 0.0)), 0.0)
        for slot_id in eligible_slots
    }
    if sum(working_raw.values()) <= 1e-12:
        working_raw = {
            slot_id: max(float(base_weights.get(slot_id, 0.0)), 0.0)
            for slot_id in eligible_slots
        }
    weights: dict[str, float] = {slot_id: 0.0 for slot_id in raw_alphas}
    remaining_slots = list(eligible_slots)
    remaining_budget = 1.0
    while remaining_slots:
        total_raw = float(sum(working_raw.get(slot_id, 0.0) for slot_id in remaining_slots))
        if total_raw <= 1e-12:
            equal_weight = remaining_budget / float(len(remaining_slots))
            if equal_weight - max_weight_frac > 1e-9:
                raise ApplicationError(
                    "eligible sleeve universe cannot satisfy max_sleeve_weight_frac",
                    eligible_sleeves=len(eligible_slots),
                    max_sleeve_weight_frac=max_weight_frac,
                )
            for slot_id in remaining_slots:
                weights[slot_id] = equal_weight
            break
        proposed = {
            slot_id: remaining_budget * (working_raw.get(slot_id, 0.0) / total_raw)
            for slot_id in remaining_slots
        }
        capped_slots = [
            slot_id for slot_id, value in proposed.items() if value - max_weight_frac > 1e-9
        ]
        if not capped_slots:
            for slot_id, value in proposed.items():
                weights[slot_id] = value
            break
        for slot_id in capped_slots:
            weights[slot_id] = max_weight_frac
            remaining_budget -= max_weight_frac
            remaining_slots.remove(slot_id)
    total_weight = sum(weights.values())
    if abs(total_weight - 1.0) > 1e-6:
        raise ApplicationError(
            "normalized candidate weights must sum to 1.0",
            total_weight=total_weight,
        )
    return weights


def candidate_id(candidate_weights: dict[str, float]) -> str:
    """Build a stable candidate identifier from one normalized weight vector."""

    from backtest_engine.core.ids import stable_hash

    return f"candidate-{stable_hash(candidate_weights)[:12]}"


def simulate_candidate(
    *,
    analytics_by_slot: dict[str, SleeveAnalyticsFrame],
    target_weights: dict[str, float],
    execution_policy: PortfolioExecutionPolicy,
) -> PortfolioSizingRun:
    """Run the shared causal sizing engine for one candidate."""

    return evaluate_portfolio_sizing_run(
        analytics_by_slot=analytics_by_slot,
        target_weights=target_weights,
        policy=execution_policy,
    )


def select_confirm_candidates(*, fold_study: Any, top_k_confirm: int) -> list[ConfirmCandidate]:
    """Pick the top unique IS candidates for confirmatory evaluation."""

    seen_candidate_ids: set[str] = set()
    candidates: list[ConfirmCandidate] = []
    completed_trials = [
        trial
        for trial in fold_study.trials
        if getattr(trial, "value", None) is not None and trial.user_attrs.get("candidate_id") is not None
    ]
    completed_trials.sort(key=lambda trial: float(trial.value), reverse=True)
    for trial in completed_trials:
        resolved_candidate_id = str(trial.user_attrs["candidate_id"])
        if resolved_candidate_id in seen_candidate_ids:
            continue
        seen_candidate_ids.add(resolved_candidate_id)
        candidates.append(
            {
                "candidate_id": resolved_candidate_id,
                "candidate_weights": _coerce_candidate_weights(trial.user_attrs["candidate_weights"]),
                "is_rank": len(candidates) + 1,
            }
        )
        if len(candidates) >= top_k_confirm:
            break
    return candidates


def _coerce_candidate_weights(raw_value: object) -> dict[str, float]:
    if not isinstance(raw_value, dict):
        raise InfrastructureError("candidate_weights must be a mapping", raw_type=type(raw_value).__name__)
    return {str(slot_id): float(weight) for slot_id, weight in raw_value.items()}


def build_approximate_trial_row(
    *,
    study_id: str,
    fold_id: str,
    trial_number: int,
    candidate_weights: dict[str, float],
    evaluation: PortfolioSizingRun,
) -> dict[str, JsonValue]:
    """Build one schema-versioned approximate trial row."""

    return {
        "schema_version": 1,
        "study_id": study_id,
        "fold_id": fold_id,
        "phase": "approximate",
        "trial_number": int(trial_number),
        "candidate_id": candidate_id(candidate_weights),
        "objective_value": evaluation.sharpe_after_costs,
        "effective_bar_count": float(evaluation.effective_bar_count),
        "net_return": evaluation.net_return,
        "sharpe_after_costs": evaluation.sharpe_after_costs,
        "max_drawdown": evaluation.max_drawdown,
        "candidate_weights_json": json.dumps(
            candidate_weights,
            sort_keys=True,
            separators=(",", ":"),
        ),
    }


def default_candidate_summary(
    *,
    control: PortfolioWeightStudyControlSpec,
    eligible_slots: tuple[str, ...],
) -> dict[str, JsonValue]:
    """Build common trial metadata for a fold."""

    return {
        "weight_step_frac": control.weight_step_frac,
        "max_sleeve_weight_frac": control.max_sleeve_weight_frac,
        "top_k_confirm": control.top_k_confirm,
        "eligible_slots": list(eligible_slots),
    }


__all__ = [
    "build_approximate_trial_row",
    "build_sleeve_run_spec",
    "candidate_id",
    "default_candidate_summary",
    "load_fold_sleeve_analytics",
    "load_sleeve_analytics_from_bundle",
    "normalize_capped_simplex",
    "returns_frame_is_eligible",
    "select_confirm_candidates",
    "simulate_candidate",
]
