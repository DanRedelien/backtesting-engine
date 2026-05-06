"""Application-layer error taxonomy for the market-data boundary."""

from __future__ import annotations

from typing import Any

from backtest_engine.core.errors import ApplicationError


class PartialBatchFailureError(ApplicationError):
    """Raised when a batch request finishes with one or more failed slices.

    ``batch_result`` carries the full per-slice outcome
    (``HistoricalMarketDataBatchResult`` or
    ``MarketDataVerificationBatchResult``) so callers can inspect
    which slices succeeded and which failed.
    """

    def __init__(self, message: str, *, batch_result: Any, **context: Any) -> None:
        self.batch_result = batch_result
        super().__init__(message, **context)


__all__ = ["PartialBatchFailureError"]
