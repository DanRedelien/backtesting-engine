"""Terminal UI adapter for read-only live allocation recommendation artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from backtest_engine.analytics.read_models import LiveAllocationRecommendationReadModel


class RecommendationRequest(BaseModel):
    """A terminal UI request for one persisted recommendation artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_path: Path


class RecommendationService(Protocol):
    """Load recommendation artifacts for delivery surfaces."""

    def load_recommendation(self, artifact_path: Path) -> LiveAllocationRecommendationReadModel:
        """Return the typed recommendation for one artifact file."""
        ...


def read_recommendation(
    command: RecommendationRequest,
    service: RecommendationService,
) -> LiveAllocationRecommendationReadModel:
    """Delegate recommendation reads to the canonical read-model path."""

    return service.load_recommendation(command.artifact_path)


__all__ = ["RecommendationRequest", "RecommendationService", "read_recommendation"]
