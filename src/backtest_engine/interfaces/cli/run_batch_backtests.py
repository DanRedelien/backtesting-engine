"""CLI adapter for canonical batch orchestration."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from backtest_engine.application.batch.run_batch_backtests import (
    BatchRunCommand,
    BatchRunResult,
)
from backtest_engine.config.runtime import BacktestRunSpec
from backtest_engine.core.types import NonEmptyStr


class BatchBacktestsCliCommand(BaseModel):
    """A CLI request for one canonical batch run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    requested_by: NonEmptyStr = "cli"
    correlation_id: NonEmptyStr | None = None
    run_specs: tuple[BacktestRunSpec, ...] = Field(default_factory=tuple)


class BatchBacktestsCliRunner(Protocol):
    """Execute one batch orchestration request."""

    def run_batch_backtests(self, command: BatchRunCommand) -> BatchRunResult:
        """Return the outcome of one canonical batch run."""
        ...


def run_batch_backtests_cli(
    command: BatchBacktestsCliCommand,
    runner: BatchBacktestsCliRunner,
) -> BatchRunResult:
    """Translate a CLI request into the canonical batch command."""

    return runner.run_batch_backtests(
        BatchRunCommand(
            requested_by=command.requested_by,
            correlation_id=command.correlation_id,
            run_specs=command.run_specs,
        )
    )


__all__ = [
    "BatchBacktestsCliCommand",
    "BatchBacktestsCliRunner",
    "run_batch_backtests_cli",
]
