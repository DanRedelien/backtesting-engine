"""Terminal UI adapter for the explicit latest recommendation surface."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from backtest_engine.analytics.read_models import LiveAllocationRecommendationReadModel


class LatestRecommendationRequest(BaseModel):
    """A terminal UI request for the latest persisted recommendation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    results_root: Path


class LatestRecommendationService(Protocol):
    """Load the latest recommendation artifact for delivery surfaces."""

    def load_latest_recommendation(
        self,
        results_root: Path,
    ) -> LiveAllocationRecommendationReadModel:
        """Return the latest typed recommendation artifact."""
        ...


def read_latest_recommendation(
    command: LatestRecommendationRequest,
    service: LatestRecommendationService,
) -> LiveAllocationRecommendationReadModel:
    """Delegate latest recommendation reads to the canonical read-model path."""

    return service.load_latest_recommendation(command.results_root)


__all__ = [
    "LatestRecommendationRequest",
    "LatestRecommendationService",
    "read_latest_recommendation",
]
