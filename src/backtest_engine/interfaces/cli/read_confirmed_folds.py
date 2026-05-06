"""CLI adapter for confirmed fold artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from backtest_engine.analytics.read_models import ConfirmedFoldCollectionReadModel


class ConfirmedFoldsCliCommand(BaseModel):
    """A CLI request for one persisted confirmed-fold collection."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_path: Path


class ConfirmedFoldsCliRunner(Protocol):
    """Load confirmed fold artifacts through the canonical read path."""

    def load_confirmed_folds(self, artifact_path: Path) -> ConfirmedFoldCollectionReadModel:
        """Return one typed fold collection."""
        ...


def read_confirmed_folds_cli(
    command: ConfirmedFoldsCliCommand,
    runner: ConfirmedFoldsCliRunner,
) -> ConfirmedFoldCollectionReadModel:
    """Delegate confirmed-fold reads to the canonical read model path."""

    return runner.load_confirmed_folds(command.artifact_path)


__all__ = [
    "ConfirmedFoldsCliCommand",
    "ConfirmedFoldsCliRunner",
    "read_confirmed_folds_cli",
]
