"""Canonical walk-forward orchestration."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from backtest_engine.application.optimization.fold_evaluator import FoldEvaluation, evaluate_fold
from backtest_engine.application.optimization.trial_executor import TrialRuntime
from backtest_engine.config.runtime import BacktestRunSpec
from backtest_engine.core.types import NonEmptyStr


class WalkForwardCommand(BaseModel):
    """A request wrapper for walk-forward orchestration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    requested_by: NonEmptyStr = "operator"
    correlation_id: NonEmptyStr | None = None
    metric_name: NonEmptyStr = "net_profit"
    fold_run_specs: tuple[BacktestRunSpec, ...] = Field(default_factory=tuple)


class WalkForwardResult(BaseModel):
    """The outcome of one walk-forward execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fold_results: tuple[FoldEvaluation, ...]
    best_run_id: NonEmptyStr | None


def run_walk_forward(command: WalkForwardCommand, runtime: TrialRuntime) -> WalkForwardResult:
    """Evaluate each fold with the canonical trial executor."""

    fold_results = tuple(
        evaluate_fold(
            execution,
            command.metric_name,
        )
        for execution in runtime.execute_many(
            command.fold_run_specs,
            requested_by=command.requested_by,
            correlation_id=command.correlation_id,
        )
    )
    best_run = max(fold_results, key=lambda item: item.metric_value, default=None)
    return WalkForwardResult(
        fold_results=fold_results,
        best_run_id=best_run.run_id if best_run else None,
    )


__all__ = ["WalkForwardCommand", "WalkForwardResult", "run_walk_forward"]
