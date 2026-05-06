"""Terminal UI adapter for read-only confirmed fold artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from backtest_engine.analytics.read_models import ConfirmedFoldCollectionReadModel


class ConfirmedFoldsRequest(BaseModel):
    """A terminal UI request for one persisted fold collection artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_path: Path


class ConfirmedFoldsService(Protocol):
    """Load confirmed fold artifacts for delivery surfaces."""

    def load_confirmed_folds(self, artifact_path: Path) -> ConfirmedFoldCollectionReadModel:
        """Return the typed fold collection for one artifact path."""
        ...


def read_confirmed_folds(
    command: ConfirmedFoldsRequest,
    service: ConfirmedFoldsService,
) -> ConfirmedFoldCollectionReadModel:
    """Delegate confirmed fold reads to the canonical read-model path."""

    return service.load_confirmed_folds(command.artifact_path)


__all__ = [
    "ConfirmedFoldsRequest",
    "ConfirmedFoldsService",
    "read_confirmed_folds",
]
