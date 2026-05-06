"""Internal bundle-header builder shared by export use-cases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from backtest_engine.config.runtime import BacktestRunSpec
from backtest_engine.domain.artifacts.manifests import ArtifactManifest
from backtest_engine.domain.artifacts.provenance import ProvenanceRecord


@dataclass(frozen=True)
class BundleHeader:
    """The shared header records carried by every result bundle."""

    manifest: ArtifactManifest
    provenance: ProvenanceRecord


def build_bundle_header_from_run_spec(
    run_spec: BacktestRunSpec,
    created_at_utc: datetime,
) -> BundleHeader:
    """Build the shared manifest and provenance records for one run spec."""

    run_spec_hash = run_spec.content_hash
    return BundleHeader(
        manifest=ArtifactManifest(
            run_id=run_spec.run_id,
            run_spec_hash=run_spec_hash,
            runtime_boundary=run_spec.runtime_boundary,
            dataset_id=run_spec.dataset.dataset_id,
            config_hash=run_spec_hash,
            symbol_universe=run_spec.dataset.symbol_universe,
            strategy_ids=tuple(spec.strategy.strategy_id for spec in run_spec.strategies),
            capital_base=run_spec.capital_base,
            semantic_policy_version=run_spec.semantic_policy_version,
        ),
        provenance=ProvenanceRecord(
            run_id=run_spec.run_id,
            run_spec_hash=run_spec_hash,
            dataset_id=run_spec.dataset.dataset_id,
            created_at_utc=created_at_utc,
        ),
    )


__all__ = ["BundleHeader", "build_bundle_header_from_run_spec"]
