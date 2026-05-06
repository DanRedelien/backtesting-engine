"""CLI adapter for the canonical portfolio backtest use-case."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict

from backtest_engine.application.portfolio.run_portfolio_backtest import (
    PortfolioRunCommand,
    PortfolioRunResult,
)
from backtest_engine.config.runtime import BacktestRunSpec
from backtest_engine.core.types import NonEmptyStr


class PortfolioBacktestCliCommand(BaseModel):
    """A CLI request for one canonical portfolio backtest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_spec: BacktestRunSpec
    requested_by: NonEmptyStr = "cli"
    correlation_id: NonEmptyStr | None = None


class PortfolioBacktestCliRunner(Protocol):
    """Execute one portfolio backtest through the application boundary."""

    def run_portfolio_backtest(
        self,
        command: PortfolioRunCommand,
        run_spec: BacktestRunSpec,
    ) -> PortfolioRunResult:
        """Return the outcome of one canonical portfolio backtest."""
        ...


def run_portfolio_backtest_cli(
    command: PortfolioBacktestCliCommand,
    runner: PortfolioBacktestCliRunner,
) -> PortfolioRunResult:
    """Translate a CLI request into the canonical portfolio-run command."""

    return runner.run_portfolio_backtest(
        command=PortfolioRunCommand(
            requested_by=command.requested_by,
            correlation_id=command.correlation_id,
        ),
        run_spec=command.run_spec,
    )


__all__ = [
    "PortfolioBacktestCliCommand",
    "PortfolioBacktestCliRunner",
    "run_portfolio_backtest_cli",
]
