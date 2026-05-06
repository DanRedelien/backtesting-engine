"""Confirmatory evaluation helpers for portfolio-weight studies."""

from __future__ import annotations

import json

from backtest_engine.application.optimization.study_contracts import (
    PortfolioWeightStudyControlSpec,
    PortfolioWeightStudyThresholds,
    StudyPortfolioExecutor,
)
from backtest_engine.application.portfolio.run_portfolio_backtest import PortfolioRunCommand
from backtest_engine.config.runtime import BacktestRunSpec
from backtest_engine.core.types import JsonValue
from backtest_engine.domain.artifacts.studies import PortfolioWeightStudyFoldResult
from backtest_engine.domain.portfolio.sizing import PortfolioSizingRun


def build_weighted_portfolio_run_spec(
    *,
    run_spec: BacktestRunSpec,
    candidate_weights: dict[str, float],
) -> BacktestRunSpec:
    """Materialize one weighted portfolio run spec for a confirmatory rerun."""

    updated_strategies = tuple(
        strategy.model_copy(update={"weight_frac": float(candidate_weights[strategy.slot_id])})
        for strategy in run_spec.strategies
    )
    return run_spec.model_copy(update={"strategies": updated_strategies})


def confirm_candidate(
    *,
    study_id: str,
    fold_id: str,
    candidate_rank: int,
    candidate_id: str,
    candidate_weights: dict[str, float],
    evaluation: PortfolioSizingRun,
    eligible_slots: tuple[str, ...],
    thresholds: PortfolioWeightStudyThresholds,
    control: PortfolioWeightStudyControlSpec,
    portfolio_executor: StudyPortfolioExecutor,
    out_of_sample_run_spec: BacktestRunSpec,
    requested_by: str,
    correlation_id: str | None,
) -> tuple[PortfolioWeightStudyFoldResult | None, dict[str, JsonValue]]:
    """Run one confirmatory evaluation without using bundle summary returns as truth."""

    trial_row: dict[str, JsonValue] = {
        "schema_version": 1,
        "study_id": study_id,
        "fold_id": fold_id,
        "phase": "confirmatory",
        "rank": candidate_rank,
        "candidate_id": candidate_id,
        "candidate_weights_json": json.dumps(
            candidate_weights,
            sort_keys=True,
            separators=(",", ":"),
        ),
        "effective_bar_count": float(evaluation.effective_bar_count),
        "net_return": evaluation.net_return,
        "sharpe_after_costs": evaluation.sharpe_after_costs,
        "max_drawdown": evaluation.max_drawdown,
    }
    min_effective_oos_bars = control.min_effective_oos_bars
    if min_effective_oos_bars is None:
        raise ValueError("control.min_effective_oos_bars must resolve to a concrete value")
    if evaluation.effective_bar_count < min_effective_oos_bars:
        trial_row["execution_failed"] = True
        trial_row["failure_reason"] = "insufficient_effective_oos_bars"
        return None, trial_row

    try:
        confirm_result = portfolio_executor.run(
            command=PortfolioRunCommand(
                requested_by=requested_by,
                correlation_id=correlation_id,
            ),
            run_spec=build_weighted_portfolio_run_spec(
                run_spec=out_of_sample_run_spec,
                candidate_weights=candidate_weights,
            ),
        )
    except Exception as exc:
        trial_row["execution_failed"] = True
        trial_row["error_type"] = type(exc).__name__
        return None, trial_row

    trade_count = int(
        confirm_result.metric_values.get(
            "trade_count",
            confirm_result.metric_values.get("total_trades", 0.0),
        )
    )
    quality_profitable = (
        evaluation.net_return > 0.0
        and evaluation.sharpe_after_costs >= thresholds.quality_sharpe_floor
    )
    fold_result = PortfolioWeightStudyFoldResult(
        study_id=study_id,
        fold_id=fold_id,
        selected_candidate_id=candidate_id,
        selected_candidate_rank=candidate_rank,
        selected_run_id=confirm_result.run_id,
        selected_bundle_uri=confirm_result.bundle_uri,
        champion_weights=dict(candidate_weights),
        eligible_slots=eligible_slots,
        execution_failed=False,
        trade_insufficient=trade_count < thresholds.min_trades_per_fold,
        quality_profitable=quality_profitable,
        effective_bar_count=evaluation.effective_bar_count,
        effective_start_utc=evaluation.effective_start_utc,
        effective_end_utc=evaluation.effective_end_utc,
        net_return=evaluation.net_return,
        sharpe_after_costs=evaluation.sharpe_after_costs,
        max_drawdown=evaluation.max_drawdown,
        trade_count=trade_count,
        summary={
            "confirm_rank": candidate_rank,
            "runtime_policy_parity_pending": True,
        },
    )
    trial_row.update(
        {
            "execution_failed": False,
            "run_id": confirm_result.run_id,
            "bundle_uri": confirm_result.bundle_uri,
            "trade_count": float(trade_count),
            "effective_start_utc": (
                evaluation.effective_start_utc.isoformat()
                if evaluation.effective_start_utc is not None
                else None
            ),
            "effective_end_utc": (
                evaluation.effective_end_utc.isoformat()
                if evaluation.effective_end_utc is not None
                else None
            ),
        }
    )
    return fold_result, trial_row


__all__ = [
    "build_weighted_portfolio_run_spec",
    "confirm_candidate",
]
