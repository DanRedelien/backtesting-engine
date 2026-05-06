"""Terminal UI adapter for read-only study champion artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from backtest_engine.analytics.read_models import StudyChampionReadModel


class StudyChampionRequest(BaseModel):
    """A terminal UI request for one persisted study champion artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_path: Path


class StudyChampionService(Protocol):
    """Load study champion artifacts for delivery surfaces."""

    def load_study_champion(self, artifact_path: Path) -> StudyChampionReadModel:
        """Return the typed champion artifact for one path."""
        ...


def read_study_champion(
    command: StudyChampionRequest,
    service: StudyChampionService,
) -> StudyChampionReadModel:
    """Delegate champion reads to the canonical read-model path."""

    return service.load_study_champion(command.artifact_path)


__all__ = [
    "StudyChampionRequest",
    "StudyChampionService",
    "read_study_champion",
]
