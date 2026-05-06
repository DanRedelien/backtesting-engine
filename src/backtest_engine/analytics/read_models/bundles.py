"""Read models derived from persisted result bundles."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from backtest_engine.core.enums import RunKind, RuntimeBoundary
from backtest_engine.core.money import Money
from backtest_engine.core.types import NonEmptyStr
from backtest_engine.domain.artifacts.bundles import ResultBundle
from backtest_engine.infrastructure.artifacts.bundle_loader import BundleLoader


class BundleReadModel(BaseModel):
    """A thin read model for delivery surfaces."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    bundle_id: NonEmptyStr
    run_id: NonEmptyStr
    dataset_id: NonEmptyStr
    run_kind: RunKind
    runtime_boundary: RuntimeBoundary
    strategy_ids: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)
    symbol_universe: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)
    capital_base: Money
    semantic_policy_version: NonEmptyStr
    created_at_utc: datetime
    metric_values: dict[str, float] = Field(default_factory=dict)
    artifact_locations: dict[str, NonEmptyStr] = Field(default_factory=dict)


def build_bundle_read_model(bundle: ResultBundle) -> BundleReadModel:
    """Project a minimal read model from a persisted bundle."""

    return BundleReadModel(
        bundle_id=bundle.bundle_id,
        run_id=bundle.manifest.run_id,
        dataset_id=bundle.manifest.dataset_id,
        run_kind=bundle.run_spec.run_kind,
        runtime_boundary=bundle.manifest.runtime_boundary,
        strategy_ids=bundle.manifest.strategy_ids,
        symbol_universe=bundle.manifest.symbol_universe,
        capital_base=bundle.manifest.capital_base,
        semantic_policy_version=bundle.manifest.semantic_policy_version,
        created_at_utc=bundle.provenance.created_at_utc,
        metric_values=bundle.metric_values,
        artifact_locations=bundle.artifact_locations,
    )


def load_bundle_read_model(bundle_path: Path, loader: BundleLoader) -> BundleReadModel:
    """Load one persisted bundle and project it into a delivery read model."""

    return build_bundle_read_model(loader.load_bundle(bundle_path))


__all__ = ["BundleReadModel", "build_bundle_read_model", "load_bundle_read_model"]
