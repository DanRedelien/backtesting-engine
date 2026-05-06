"""CLI adapter for read-only live allocation recommendations."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from backtest_engine.analytics.read_models import LiveAllocationRecommendationReadModel


class RecommendationCliCommand(BaseModel):
    """A CLI request for one persisted live allocation recommendation artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_path: Path


class RecommendationCliRunner(Protocol):
    """Load one recommendation through the application boundary."""

    def load_recommendation(
        self,
        artifact_path: Path,
    ) -> LiveAllocationRecommendationReadModel:
        """Return the typed recommendation for one artifact file."""
        ...


def read_recommendation_cli(
    command: RecommendationCliCommand,
    runner: RecommendationCliRunner,
) -> LiveAllocationRecommendationReadModel:
    """Translate a CLI request into a typed recommendation read."""

    return runner.load_recommendation(command.artifact_path)


__all__ = [
    "RecommendationCliCommand",
    "RecommendationCliRunner",
    "read_recommendation_cli",
]
