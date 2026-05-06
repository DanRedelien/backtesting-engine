"""Terminal UI adapter for read-only study summary artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from backtest_engine.analytics.read_models import StudySummaryReadModel


class StudySummaryRequest(BaseModel):
    """A terminal UI request for one persisted study summary artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_path: Path


class StudySummaryService(Protocol):
    """Load study summaries for delivery surfaces."""

    def load_study_summary(self, artifact_path: Path) -> StudySummaryReadModel:
        """Return the typed study summary for one artifact file."""
        ...


def read_study_summary(
    command: StudySummaryRequest,
    service: StudySummaryService,
) -> StudySummaryReadModel:
    """Delegate study summary reads to the canonical read-model path."""

    return service.load_study_summary(command.artifact_path)


__all__ = [
    "StudySummaryRequest",
    "StudySummaryService",
    "read_study_summary",
]
