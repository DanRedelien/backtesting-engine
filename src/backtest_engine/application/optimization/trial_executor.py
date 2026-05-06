"""Trial-execution contracts for walk-forward orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

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


class TrialExecution(BaseModel):
    """A normalized trial result used by walk-forward orchestration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: NonEmptyStr
    run_kind: RunKind
    bundle_uri: NonEmptyStr
    metric_values: dict[str, float] = Field(default_factory=dict)


class TrialSingleExecutor(Protocol):
    """Execute one canonical single backtest."""

    def run(self, command: SingleRunCommand, run_spec: BacktestRunSpec) -> SingleRunResult:
        """Return one canonical single-run outcome."""
        ...


class TrialPortfolioExecutor(Protocol):
    """Execute one canonical portfolio backtest."""

    def run(
        self,
        command: PortfolioRunCommand,
        run_spec: BacktestRunSpec,
    ) -> PortfolioRunResult:
        """Return one canonical portfolio-run outcome."""
        ...


class TrialExecutor(Protocol):
    """Execute one trial and return normalized metrics."""

    def execute(
        self,
        run_spec: BacktestRunSpec,
        *,
        requested_by: NonEmptyStr,
        correlation_id: NonEmptyStr | None = None,
    ) -> TrialExecution:
        """Return trial metrics for one fold."""
        ...


class TrialRuntime(Protocol):
    """Execute one ordered fold sequence through the canonical trial executor."""

    def execute_many(
        self,
        run_specs: tuple[BacktestRunSpec, ...],
        *,
        requested_by: NonEmptyStr,
        correlation_id: NonEmptyStr | None = None,
    ) -> tuple[TrialExecution, ...]:
        """Return normalized trial metrics in the same order as the input folds."""
        ...


@dataclass(frozen=True)
class CanonicalTrialExecutor:
    """Dispatch walk-forward folds through canonical backtest use-cases."""

    single_executor: TrialSingleExecutor
    portfolio_executor: TrialPortfolioExecutor

    def execute(
        self,
        run_spec: BacktestRunSpec,
        *,
        requested_by: NonEmptyStr,
        correlation_id: NonEmptyStr | None = None,
    ) -> TrialExecution:
        if run_spec.run_kind is RunKind.SINGLE:
            single_result = self.single_executor.run(
                command=SingleRunCommand(
                    requested_by=requested_by,
                    correlation_id=correlation_id,
                ),
                run_spec=run_spec,
            )
            return _from_single_result(run_spec=run_spec, result=single_result)

        if run_spec.run_kind is RunKind.PORTFOLIO:
            portfolio_result = self.portfolio_executor.run(
                command=PortfolioRunCommand(
                    requested_by=requested_by,
                    correlation_id=correlation_id,
                ),
                run_spec=run_spec,
            )
            return _from_portfolio_result(run_spec=run_spec, result=portfolio_result)

        raise ApplicationError(
            "walk-forward folds must reuse the canonical single or portfolio use-cases",
            run_kind=run_spec.run_kind,
        )


def _from_single_result(run_spec: BacktestRunSpec, result: SingleRunResult) -> TrialExecution:
    return TrialExecution(
        run_id=result.run_id,
        run_kind=run_spec.run_kind,
        bundle_uri=result.bundle_uri,
        metric_values=result.metric_values,
    )


def _from_portfolio_result(
    run_spec: BacktestRunSpec,
    result: PortfolioRunResult,
) -> TrialExecution:
    return TrialExecution(
        run_id=result.run_id,
        run_kind=run_spec.run_kind,
        bundle_uri=result.bundle_uri,
        metric_values=result.metric_values,
    )


__all__ = [
    "CanonicalTrialExecutor",
    "TrialExecution",
    "TrialExecutor",
    "TrialPortfolioExecutor",
    "TrialRuntime",
    "TrialSingleExecutor",
]
