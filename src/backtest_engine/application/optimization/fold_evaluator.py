"""Fold-evaluation helpers for walk-forward orchestration."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from backtest_engine.application.optimization.trial_executor import TrialExecution
from backtest_engine.core.types import NonEmptyStr


class FoldEvaluation(BaseModel):
    """An evaluated walk-forward fold."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: NonEmptyStr
    metric_name: NonEmptyStr
    metric_value: float


def evaluate_fold(execution: TrialExecution, metric_name: NonEmptyStr) -> FoldEvaluation:
    """Extract one named metric from a trial execution."""

    return FoldEvaluation(
        run_id=execution.run_id,
        metric_name=metric_name,
        metric_value=execution.metric_values.get(metric_name, 0.0),
    )


__all__ = ["FoldEvaluation", "evaluate_fold"]
