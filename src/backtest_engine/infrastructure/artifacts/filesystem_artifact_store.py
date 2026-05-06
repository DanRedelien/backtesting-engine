"""Filesystem-backed persistence for result bundles."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from backtest_engine.core.errors import InfrastructureError
from backtest_engine.domain.artifacts.bundles import ResultBundle
from backtest_engine.infrastructure.artifacts.artifact_store import SavedBundle


_BUNDLE_FILENAME = "bundle.json"


@dataclass(frozen=True)
class FilesystemArtifactStore:
    """Persist result bundles under one deterministic results root."""

    results_root: Path

    def save_bundle(self, bundle: ResultBundle) -> SavedBundle:
        """Write one bundle to disk and return its persisted location."""

        bundle_path = self.results_root / bundle.bundle_id / _BUNDLE_FILENAME
        try:
            bundle_path.parent.mkdir(parents=True, exist_ok=True)
            bundle_path.write_text(
                bundle.model_dump_json(
                    indent=2,
                    exclude={"bundle_id", "metric_values"},
                    exclude_computed_fields=True,
                ),
                encoding="utf-8",
            )
        except OSError as exc:
            raise InfrastructureError(
                "failed to persist result bundle",
                bundle_id=bundle.bundle_id,
                bundle_path=str(bundle_path),
            ) from exc

        return SavedBundle(
            bundle_id=bundle.bundle_id,
            bundle_uri=bundle_path.as_posix(),
        )


__all__ = ["FilesystemArtifactStore"]
