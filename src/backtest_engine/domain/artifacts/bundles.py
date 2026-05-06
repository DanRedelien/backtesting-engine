"""Result bundle contracts."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, computed_field

from backtest_engine.config.runtime import BacktestRunSpec
from backtest_engine.core.ids import build_bundle_id, stable_hash
from backtest_engine.core.types import JsonValue, NonEmptyStr
from backtest_engine.domain.artifacts.manifests import ArtifactManifest
from backtest_engine.domain.artifacts.provenance import ProvenanceRecord


class ResultBundle(BaseModel):
    """A persisted user-facing bundle built from runtime truth and replay context."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest: ArtifactManifest
    provenance: ProvenanceRecord
    run_spec: BacktestRunSpec
    artifact_locations: dict[str, NonEmptyStr] = Field(default_factory=dict)
    summary: dict[str, JsonValue] = Field(default_factory=dict)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def metric_values(self) -> dict[str, float]:
        """Return numeric metrics extracted from the user-facing summary."""

        metric_values: dict[str, float] = {}
        for key, value in self.summary.items():
            if isinstance(value, bool):
                continue
            if isinstance(value, int | float):
                metric_values[key] = float(value)
        return metric_values

    @computed_field  # type: ignore[prop-decorator]
    @property
    def bundle_id(self) -> str:
        payload = self.model_dump(
            mode="json",
            exclude={"bundle_id", "metric_values"},
            exclude_computed_fields=True,
        )
        return build_bundle_id(stable_hash(payload))


__all__ = ["ResultBundle"]
