"""CLI adapter for canonical walk-forward orchestration."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from backtest_engine.application.optimization.run_walk_forward import (
    WalkForwardCommand,
    WalkForwardResult,
)
from backtest_engine.config.runtime import BacktestRunSpec
from backtest_engine.core.types import NonEmptyStr


class WalkForwardCliCommand(BaseModel):
    """A CLI request for one canonical walk-forward job."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    requested_by: NonEmptyStr = "cli"
    correlation_id: NonEmptyStr | None = None
    metric_name: NonEmptyStr = "net_profit"
    fold_run_specs: tuple[BacktestRunSpec, ...] = Field(default_factory=tuple)


class WalkForwardCliRunner(Protocol):
    """Execute one walk-forward job through the application boundary."""

    def run_walk_forward(self, command: WalkForwardCommand) -> WalkForwardResult:
        """Return the outcome of one canonical walk-forward job."""
        ...


def run_walk_forward_cli(
    command: WalkForwardCliCommand,
    runner: WalkForwardCliRunner,
) -> WalkForwardResult:
    """Translate a CLI request into the canonical walk-forward command."""

    return runner.run_walk_forward(
        WalkForwardCommand(
            requested_by=command.requested_by,
            correlation_id=command.correlation_id,
            metric_name=command.metric_name,
            fold_run_specs=command.fold_run_specs,
        )
    )


__all__ = [
    "WalkForwardCliCommand",
    "WalkForwardCliRunner",
    "run_walk_forward_cli",
]
