"""Terminal UI adapter for read-only bundle summaries."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from backtest_engine.analytics.read_models import BundleReadModel


class BundleSummaryRequest(BaseModel):
    """A terminal UI request for one persisted bundle summary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    bundle_path: Path


class BundleSummaryService(Protocol):
    """Load read-only bundle summaries for delivery surfaces."""

    def load_bundle_read_model(self, bundle_path: Path) -> BundleReadModel:
        """Return the read model for one persisted bundle."""
        ...


def read_bundle_summary(
    command: BundleSummaryRequest,
    service: BundleSummaryService,
) -> BundleReadModel:
    """Delegate bundle summary reads to the canonical read-model path."""

    return service.load_bundle_read_model(command.bundle_path)


__all__ = ["BundleSummaryRequest", "BundleSummaryService", "read_bundle_summary"]
