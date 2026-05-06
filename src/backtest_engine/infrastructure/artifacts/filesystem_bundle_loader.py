"""Filesystem-backed loading for persisted result bundles."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from backtest_engine.core.errors import InfrastructureError
from backtest_engine.domain.artifacts.bundles import ResultBundle


_BUNDLE_FILENAME = "bundle.json"


@dataclass(frozen=True)
class FilesystemBundleLoader:
    """Load typed bundles from the filesystem results area."""

    def load_bundle(self, path: Path) -> ResultBundle:
        """Read and validate one persisted result bundle."""

        bundle_path = _resolve_bundle_path(path)
        try:
            payload = bundle_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise InfrastructureError(
                "failed to load result bundle",
                bundle_path=str(bundle_path),
            ) from exc

        try:
            return ResultBundle.model_validate_json(payload)
        except ValidationError as exc:
            raise InfrastructureError(
                "persisted result bundle failed validation",
                bundle_path=str(bundle_path),
            ) from exc


def _resolve_bundle_path(path: Path) -> Path:
    if path.suffix:
        return path
    return path / _BUNDLE_FILENAME


__all__ = ["FilesystemBundleLoader"]
