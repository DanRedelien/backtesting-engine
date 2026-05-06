"""CLI adapter for the canonical single backtest use-case."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict

from backtest_engine.application.single.run_single_backtest import (
    SingleRunCommand,
    SingleRunResult,
)
from backtest_engine.config.runtime import BacktestRunSpec
from backtest_engine.core.types import NonEmptyStr


class SingleBacktestCliCommand(BaseModel):
    """A CLI request for one canonical single backtest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_spec: BacktestRunSpec
    requested_by: NonEmptyStr = "cli"
    correlation_id: NonEmptyStr | None = None
    bundle_label: NonEmptyStr | None = None


class SingleBacktestCliRunner(Protocol):
    """Execute one single backtest through the application boundary."""

    def run_single_backtest(
        self,
        command: SingleRunCommand,
        run_spec: BacktestRunSpec,
    ) -> SingleRunResult:
        """Return the outcome of one canonical single backtest."""
        ...


def run_single_backtest_cli(
    command: SingleBacktestCliCommand,
    runner: SingleBacktestCliRunner,
) -> SingleRunResult:
    """Translate a CLI request into the canonical single-run command."""

    return runner.run_single_backtest(
        command=SingleRunCommand(
            requested_by=command.requested_by,
            correlation_id=command.correlation_id,
            bundle_label=command.bundle_label,
        ),
        run_spec=command.run_spec,
    )


__all__ = [
    "SingleBacktestCliCommand",
    "SingleBacktestCliRunner",
    "run_single_backtest_cli",
]
