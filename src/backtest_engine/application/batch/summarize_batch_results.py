"""Summaries for batch-run outcomes."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from backtest_engine.core.enums import RunKind


class BatchSummary(BaseModel):
    """A compact summary of batch execution outcomes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    total_runs: int
    succeeded_runs: int
    single_runs: int
    portfolio_runs: int
    bundle_uris: tuple[str, ...]


class BatchResultView(Protocol):
    """The subset of batch-result fields used by summary projection."""

    run_kind: RunKind
    bundle_uri: str


def summarize_batch_results(results: Sequence[BatchResultView]) -> BatchSummary:
    """Summarize a completed batch of canonical run results."""

    return BatchSummary(
        total_runs=len(results),
        succeeded_runs=len(results),
        single_runs=sum(result.run_kind is RunKind.SINGLE for result in results),
        portfolio_runs=sum(result.run_kind is RunKind.PORTFOLIO for result in results),
        bundle_uris=tuple(result.bundle_uri for result in results),
    )


__all__ = ["BatchSummary", "summarize_batch_results"]
