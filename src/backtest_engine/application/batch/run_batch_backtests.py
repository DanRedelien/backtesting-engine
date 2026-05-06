"""Canonical batch orchestration built on the single and portfolio use-cases."""

from __future__ import annotations

from typing import cast
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from backtest_engine.application.portfolio.run_portfolio_backtest import (
    PortfolioRunCommand,
    PortfolioRunResult,
)
from backtest_engine.application.batch.summarize_batch_results import (
    BatchResultView,
    BatchSummary,
    summarize_batch_results,
)
from backtest_engine.application.single.run_single_backtest import (
    SingleRunCommand,
    SingleRunResult,
)
from backtest_engine.config.runtime import BacktestRunSpec
from backtest_engine.core.enums import RunKind
from backtest_engine.core.errors import ApplicationError
from backtest_engine.core.types import NonEmptyStr


class BatchRunCommand(BaseModel):
    """A request wrapper for batch orchestration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    requested_by: NonEmptyStr = "operator"
    correlation_id: NonEmptyStr | None = None
    run_specs: tuple[BacktestRunSpec, ...] = Field(default_factory=tuple)


class BatchEntryResult(BaseModel):
    """A normalized batch member result across canonical run kinds."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: NonEmptyStr
    run_kind: RunKind
    bundle_id: NonEmptyStr
    bundle_uri: NonEmptyStr
    runtime_root: NonEmptyStr
    metric_values: dict[str, float] = Field(default_factory=dict)
    allocation_count: int | None = None
    position_count: int | None = None


class BatchRunResult(BaseModel):
    """The outcome of one batch execution request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    results: tuple[BatchEntryResult, ...]
    summary: BatchSummary


class BatchSingleExecutor(Protocol):
    """Execute one canonical single backtest."""

    def run(self, command: SingleRunCommand, run_spec: BacktestRunSpec) -> SingleRunResult:
        """Return the outcome of one single backtest."""
        ...


class BatchPortfolioExecutor(Protocol):
    """Execute one canonical portfolio backtest."""

    def run(
        self,
        command: PortfolioRunCommand,
        run_spec: BacktestRunSpec,
    ) -> PortfolioRunResult:
        """Return the outcome of one portfolio backtest."""
        ...


def run_batch_backtests(
    command: BatchRunCommand,
    single_executor: BatchSingleExecutor,
    portfolio_executor: BatchPortfolioExecutor,
) -> BatchRunResult:
    """Reuse canonical use-cases for each batch member."""

    results = tuple(
        _run_batch_member(
            command=command,
            run_spec=run_spec,
            single_executor=single_executor,
            portfolio_executor=portfolio_executor,
        )
        for run_spec in command.run_specs
    )
    return BatchRunResult(
        results=results,
        summary=summarize_batch_results(cast(tuple[BatchResultView, ...], results)),
    )


def _run_batch_member(
    command: BatchRunCommand,
    run_spec: BacktestRunSpec,
    single_executor: BatchSingleExecutor,
    portfolio_executor: BatchPortfolioExecutor,
) -> BatchEntryResult:
    if run_spec.run_kind is RunKind.SINGLE:
        single_result = single_executor.run(
            command=SingleRunCommand(
                requested_by=command.requested_by,
                correlation_id=command.correlation_id,
            ),
            run_spec=run_spec,
        )
        return BatchEntryResult(
            run_id=single_result.run_id,
            run_kind=run_spec.run_kind,
            bundle_id=single_result.bundle_id,
            bundle_uri=single_result.bundle_uri,
            runtime_root=single_result.runtime_root,
            metric_values=single_result.metric_values,
        )

    if run_spec.run_kind is RunKind.PORTFOLIO:
        portfolio_result = portfolio_executor.run(
            command=PortfolioRunCommand(
                requested_by=command.requested_by,
                correlation_id=command.correlation_id,
            ),
            run_spec=run_spec,
        )
        return BatchEntryResult(
            run_id=portfolio_result.run_id,
            run_kind=run_spec.run_kind,
            bundle_id=portfolio_result.bundle_id,
            bundle_uri=portfolio_result.bundle_uri,
            runtime_root=portfolio_result.runtime_root,
            metric_values=portfolio_result.metric_values,
            allocation_count=portfolio_result.allocation_count,
            position_count=portfolio_result.position_count,
        )

    raise ApplicationError(
        "run_batch_backtests supports only single or portfolio BacktestRunSpec values",
        run_kind=run_spec.run_kind,
    )


__all__ = [
    "BatchEntryResult",
    "BatchPortfolioExecutor",
    "BatchRunCommand",
    "BatchRunResult",
    "BatchSingleExecutor",
    "run_batch_backtests",
]
