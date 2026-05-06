"""CLI adapter for batches of canonical walk-forward jobs."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from backtest_engine.application.optimization.run_walk_forward import WalkForwardCommand
from backtest_engine.application.optimization.run_walk_forward_batch import (
    WalkForwardBatchCommand,
    WalkForwardBatchResult,
)
from backtest_engine.core.types import NonEmptyStr
from backtest_engine.interfaces.cli.run_walk_forward import WalkForwardCliCommand


class WalkForwardBatchCliCommand(BaseModel):
    """A CLI request for multiple canonical walk-forward jobs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    correlation_id: NonEmptyStr | None = None
    jobs: tuple[WalkForwardCliCommand, ...] = Field(default_factory=tuple)


class WalkForwardBatchCliRunner(Protocol):
    """Execute a batch of walk-forward jobs through the application boundary."""

    def run_walk_forward_batch(
        self,
        command: WalkForwardBatchCommand,
    ) -> WalkForwardBatchResult:
        """Return the outcome of one canonical walk-forward batch."""
        ...


def run_walk_forward_batch_cli(
    command: WalkForwardBatchCliCommand,
    runner: WalkForwardBatchCliRunner,
) -> WalkForwardBatchResult:
    """Translate a CLI request into the canonical walk-forward batch command."""

    return runner.run_walk_forward_batch(
        WalkForwardBatchCommand(
            correlation_id=command.correlation_id,
            jobs=tuple(
                WalkForwardCommand(
                    requested_by=job.requested_by,
                    correlation_id=job.correlation_id,
                    metric_name=job.metric_name,
                    fold_run_specs=job.fold_run_specs,
                )
                for job in command.jobs
            )
        )
    )


__all__ = [
    "WalkForwardBatchCliCommand",
    "WalkForwardBatchCliRunner",
    "run_walk_forward_batch_cli",
]
