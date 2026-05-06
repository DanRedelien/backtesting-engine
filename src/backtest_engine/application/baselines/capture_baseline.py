"""Capture canonical baseline bundles during migration."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict

from backtest_engine.application.portfolio.run_portfolio_backtest import (
    PortfolioRunCommand,
    PortfolioRunResult,
)
from backtest_engine.application.single.run_single_backtest import (
    SingleRunCommand,
    SingleRunResult,
)
from backtest_engine.config.runtime import BacktestRunSpec
from backtest_engine.core.enums import RunKind
from backtest_engine.core.errors import ApplicationError
from backtest_engine.core.types import NonEmptyStr


class BaselineCaptureCommand(BaseModel):
    """A request wrapper for baseline capture."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    label: NonEmptyStr
    requested_by: NonEmptyStr = "operator"
    run_spec: BacktestRunSpec


class BaselineCaptureResult(BaseModel):
    """The outcome of one baseline capture."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    label: NonEmptyStr
    run_id: NonEmptyStr
    bundle_uri: NonEmptyStr


class BaselineSingleExecutor(Protocol):
    """Execute the canonical single-run flow."""

    def run(self, command: SingleRunCommand, run_spec: BacktestRunSpec) -> SingleRunResult:
        """Return a single-run result."""
        ...


class BaselinePortfolioExecutor(Protocol):
    """Execute the canonical portfolio flow."""

    def run(self, command: PortfolioRunCommand, run_spec: BacktestRunSpec) -> PortfolioRunResult:
        """Return a portfolio-run result."""
        ...


def capture_baseline(
    command: BaselineCaptureCommand,
    single_executor: BaselineSingleExecutor,
    portfolio_executor: BaselinePortfolioExecutor,
) -> BaselineCaptureResult:
    """Capture one baseline bundle through the canonical use-case path."""

    if command.run_spec.run_kind is RunKind.PORTFOLIO:
        portfolio_result = portfolio_executor.run(
            command=PortfolioRunCommand(requested_by=command.requested_by),
            run_spec=command.run_spec,
        )
        run_id = portfolio_result.run_id
        bundle_uri = portfolio_result.bundle_uri
    elif command.run_spec.run_kind is RunKind.SINGLE:
        single_result = single_executor.run(
            command=SingleRunCommand(requested_by=command.requested_by),
            run_spec=command.run_spec,
        )
        run_id = single_result.run_id
        bundle_uri = single_result.bundle_uri
    else:
        raise ApplicationError(
            "baseline capture supports only single or portfolio BacktestRunSpec values",
            run_kind=command.run_spec.run_kind,
        )

    return BaselineCaptureResult(
        label=command.label,
        run_id=run_id,
        bundle_uri=bundle_uri,
    )


__all__ = [
    "BaselineCaptureCommand",
    "BaselineCaptureResult",
    "capture_baseline",
]
