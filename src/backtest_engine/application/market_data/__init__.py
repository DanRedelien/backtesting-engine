"""Public application surface for historical market data."""

from backtest_engine.application.market_data.contracts import (
    HistoricalMarketDataBatchResult,
    HistoricalMarketDataRequest,
    HistoricalMarketDataSliceResult,
    MarketDataDryRunMetadata,
    MarketDataErrorDetail,
    MarketDataValidationCheckDetail,
    MarketDataValidationReport,
    MarketDataValidationScoreSummary,
    MarketDataValidationWindowSummary,
    MarketDataVerificationBatchResult,
    MarketDataVerificationRequest,
    MarketDataVerificationSliceResult,
)
from backtest_engine.application.market_data.errors import PartialBatchFailureError
from backtest_engine.application.market_data.ports import HistoricalDataStore
from backtest_engine.application.market_data.service import (
    HistoricalDataProvider,
    HistoricalDataVerifier,
    HistoricalMarketDataService,
)

__all__ = [
    "HistoricalDataProvider",
    "HistoricalDataStore",
    "HistoricalDataVerifier",
    "HistoricalMarketDataBatchResult",
    "HistoricalMarketDataRequest",
    "HistoricalMarketDataService",
    "HistoricalMarketDataSliceResult",
    "MarketDataDryRunMetadata",
    "MarketDataErrorDetail",
    "MarketDataValidationCheckDetail",
    "MarketDataValidationReport",
    "MarketDataValidationScoreSummary",
    "MarketDataValidationWindowSummary",
    "MarketDataVerificationBatchResult",
    "MarketDataVerificationRequest",
    "MarketDataVerificationSliceResult",
    "PartialBatchFailureError",
]
