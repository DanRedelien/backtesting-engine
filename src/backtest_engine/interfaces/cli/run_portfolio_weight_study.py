"""CLI adapter for canonical portfolio-weight studies."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict

from backtest_engine.application.optimization.portfolio_weight_study import (
    PortfolioWeightStudyCommand,
    PortfolioWeightStudyRunResult,
    PortfolioWeightStudySpec,
)
from backtest_engine.core.types import NonEmptyStr


class PortfolioWeightStudyCliCommand(BaseModel):
    """A CLI request for one portfolio-weight study."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    study_spec: PortfolioWeightStudySpec
    requested_by: NonEmptyStr = "cli"
    correlation_id: NonEmptyStr | None = None


class PortfolioWeightStudyCliRunner(Protocol):
    """Execute one portfolio-weight study through the application boundary."""

    def run_portfolio_weight_study(
        self,
        command: PortfolioWeightStudyCommand,
    ) -> PortfolioWeightStudyRunResult:
        """Return the outcome of one portfolio-weight study."""
        ...


def run_portfolio_weight_study_cli(
    command: PortfolioWeightStudyCliCommand,
    runner: PortfolioWeightStudyCliRunner,
) -> PortfolioWeightStudyRunResult:
    """Translate a CLI request into the canonical study command."""

    return runner.run_portfolio_weight_study(
        PortfolioWeightStudyCommand(
            study_spec=command.study_spec,
            requested_by=command.requested_by,
            correlation_id=command.correlation_id,
        )
    )


__all__ = [
    "PortfolioWeightStudyCliCommand",
    "PortfolioWeightStudyCliRunner",
    "run_portfolio_weight_study_cli",
]
