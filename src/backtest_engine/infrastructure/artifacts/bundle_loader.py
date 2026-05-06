"""Bundle loader contracts."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from backtest_engine.domain.artifacts.bundles import ResultBundle


class BundleLoader(Protocol):
    """Load a persisted result bundle from storage."""

    def load_bundle(self, path: Path) -> ResultBundle:
        """Return a typed result bundle."""
        ...


__all__ = ["BundleLoader"]
