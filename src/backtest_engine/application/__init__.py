"""Application use-cases for the rewrite."""

from backtest_engine.application.backtests.dry_run_backtest import (
    BacktestDryRunCommand,
    BacktestDryRunResult,
)
from backtest_engine.application.batch.run_batch_backtests import BatchRunCommand, BatchRunResult
from backtest_engine.application.portfolio.run_portfolio_backtest import (
    PortfolioRunCommand,
    PortfolioRunResult,
)
from backtest_engine.application.single.run_single_backtest import (
    SingleRunCommand,
    SingleRunResult,
)

__all__ = [
    "BacktestDryRunCommand",
    "BacktestDryRunResult",
    "BatchRunCommand",
    "BatchRunResult",
    "PortfolioRunCommand",
    "PortfolioRunResult",
    "SingleRunCommand",
    "SingleRunResult",
]
