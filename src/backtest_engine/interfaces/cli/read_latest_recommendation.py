"""CLI adapter for the explicit latest recommendation surface."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from backtest_engine.analytics.read_models import LiveAllocationRecommendationReadModel


class LatestRecommendationCliCommand(BaseModel):
    """A CLI request for the latest persisted recommendation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    results_root: Path


class LatestRecommendationCliRunner(Protocol):
    """Load the latest recommendation through the canonical read path."""

    def load_latest_recommendation(
        self,
        results_root: Path,
    ) -> LiveAllocationRecommendationReadModel:
        """Return the latest typed recommendation artifact."""
        ...


def read_latest_recommendation_cli(
    command: LatestRecommendationCliCommand,
    runner: LatestRecommendationCliRunner,
) -> LiveAllocationRecommendationReadModel:
    """Delegate latest recommendation reads to the canonical read model path."""

    return runner.load_latest_recommendation(command.results_root)


__all__ = [
    "LatestRecommendationCliCommand",
    "LatestRecommendationCliRunner",
    "read_latest_recommendation_cli",
]
