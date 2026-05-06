"""CLI adapter for canonical baseline capture."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict

from backtest_engine.application.baselines.capture_baseline import (
    BaselineCaptureCommand,
    BaselineCaptureResult,
)
from backtest_engine.config.runtime import BacktestRunSpec
from backtest_engine.core.types import NonEmptyStr


class BaselineCaptureCliCommand(BaseModel):
    """A CLI request for one canonical baseline capture."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    label: NonEmptyStr
    run_spec: BacktestRunSpec
    requested_by: NonEmptyStr = "cli"


class BaselineCaptureCliRunner(Protocol):
    """Capture one baseline through the application boundary."""

    def capture_baseline(self, command: BaselineCaptureCommand) -> BaselineCaptureResult:
        """Return the outcome of one canonical baseline capture."""
        ...


def capture_baseline_cli(
    command: BaselineCaptureCliCommand,
    runner: BaselineCaptureCliRunner,
) -> BaselineCaptureResult:
    """Translate a CLI request into the canonical baseline command."""

    return runner.capture_baseline(
        BaselineCaptureCommand(
            label=command.label,
            requested_by=command.requested_by,
            run_spec=command.run_spec,
        )
    )


__all__ = [
    "BaselineCaptureCliCommand",
    "BaselineCaptureCliRunner",
    "capture_baseline_cli",
]
