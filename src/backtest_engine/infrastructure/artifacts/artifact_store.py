"""Artifact-store contracts."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict

from backtest_engine.core.types import NonEmptyStr
from backtest_engine.domain.artifacts.bundles import ResultBundle


class SavedBundle(BaseModel):
    """The persisted location of one result bundle."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    bundle_id: NonEmptyStr
    bundle_uri: NonEmptyStr


class ArtifactStore(Protocol):
    """Persist user-facing result bundles."""

    def save_bundle(self, bundle: ResultBundle) -> SavedBundle:
        """Persist the bundle and return its durable location."""
        ...


__all__ = ["ArtifactStore", "SavedBundle"]
