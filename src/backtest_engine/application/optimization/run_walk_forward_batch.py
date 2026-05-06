"""Batch orchestration for walk-forward runs."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from backtest_engine.application.optimization.run_walk_forward import (
    WalkForwardCommand,
    WalkForwardResult,
    run_walk_forward,
)
from backtest_engine.application.optimization.trial_executor import TrialRuntime
from backtest_engine.core.types import NonEmptyStr


class WalkForwardBatchCommand(BaseModel):
    """A request wrapper for multiple walk-forward jobs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    correlation_id: NonEmptyStr | None = None
    jobs: tuple[WalkForwardCommand, ...] = Field(default_factory=tuple)


class WalkForwardBatchResult(BaseModel):
    """The outcome of a walk-forward batch."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    job_results: tuple[WalkForwardResult, ...]


def run_walk_forward_batch(
    command: WalkForwardBatchCommand,
    runtime: TrialRuntime,
) -> WalkForwardBatchResult:
    """Execute multiple walk-forward jobs through the same trial executor."""

    return WalkForwardBatchResult(
        job_results=tuple(
            run_walk_forward(_apply_batch_correlation(job, command.correlation_id), runtime)
            for job in command.jobs
        ),
    )


def _apply_batch_correlation(
    job: WalkForwardCommand,
    correlation_id: NonEmptyStr | None,
) -> WalkForwardCommand:
    if job.correlation_id is not None or correlation_id is None:
        return job
    return job.model_copy(update={"correlation_id": correlation_id})


__all__ = ["WalkForwardBatchCommand", "WalkForwardBatchResult", "run_walk_forward_batch"]
