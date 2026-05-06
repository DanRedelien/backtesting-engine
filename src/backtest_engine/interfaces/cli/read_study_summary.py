"""CLI adapter for read-only study summary artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from backtest_engine.analytics.read_models import StudySummaryReadModel


class StudySummaryCliCommand(BaseModel):
    """A CLI request for one persisted study summary artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_path: Path


class StudySummaryCliRunner(Protocol):
    """Load one study summary through the application boundary."""

    def load_study_summary(self, artifact_path: Path) -> StudySummaryReadModel:
        """Return the typed study summary for one artifact file."""
        ...


def read_study_summary_cli(
    command: StudySummaryCliCommand,
    runner: StudySummaryCliRunner,
) -> StudySummaryReadModel:
    """Translate a CLI request into a typed study summary read."""

    return runner.load_study_summary(command.artifact_path)


__all__ = [
    "StudySummaryCliCommand",
    "StudySummaryCliRunner",
    "read_study_summary_cli",
]
