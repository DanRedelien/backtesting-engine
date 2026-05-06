"""CLI adapter for study champion artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from backtest_engine.analytics.read_models import StudyChampionReadModel


class StudyChampionCliCommand(BaseModel):
    """A CLI request for one persisted study champion artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_path: Path


class StudyChampionCliRunner(Protocol):
    """Load study champion artifacts through the canonical read path."""

    def load_study_champion(self, artifact_path: Path) -> StudyChampionReadModel:
        """Return one typed study champion artifact."""
        ...


def read_study_champion_cli(
    command: StudyChampionCliCommand,
    runner: StudyChampionCliRunner,
) -> StudyChampionReadModel:
    """Delegate champion reads to the canonical read model path."""

    return runner.load_study_champion(command.artifact_path)


__all__ = [
    "StudyChampionCliCommand",
    "StudyChampionCliRunner",
    "read_study_champion_cli",
]
