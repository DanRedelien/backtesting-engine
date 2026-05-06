from __future__ import annotations

from decimal import Decimal
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backtest_engine.config.runtime import BacktestRunSpec, ExecutionWindow
from backtest_engine.core.enums import DatasetSource, RunKind, RuntimeBoundary
from backtest_engine.core.errors import InfrastructureError
from backtest_engine.core.money import Money
from backtest_engine.domain.artifacts.bundles import ResultBundle
from backtest_engine.domain.artifacts.manifests import ArtifactManifest
from backtest_engine.domain.artifacts.provenance import ProvenanceRecord
from backtest_engine.domain.market.datasets import DatasetSpec
from backtest_engine.domain.strategy.specifications import (
    PortfolioStrategySpec,
    StrategyLegSpec,
    StrategySpec,
)
from backtest_engine.infrastructure.artifacts import (
    FilesystemArtifactStore,
    FilesystemBundleLoader,
)


def _build_run_spec() -> BacktestRunSpec:
    return BacktestRunSpec(
        run_kind=RunKind.SINGLE,
        execution_window=ExecutionWindow(
            start_utc=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end_utc=datetime(2024, 2, 1, tzinfo=timezone.utc),
        ),
        dataset=DatasetSpec(
            source_system=DatasetSource.PARQUET,
            normalization_policy="nautilus_v1",
            schema_version="1",
            symbol_universe=("ES",),
            timeframe="30m",
            dataset_version="2026-04-03",
        ),
        strategies=(
            PortfolioStrategySpec(
                slot_id="slot-1",
                weight_frac=1.0,
                strategy=StrategySpec(
                    strategy_id="sma_pullback",
                    implementation_id="sma_pullback",
                    policy_version="v1",
                ),
                legs=(StrategyLegSpec(symbol="ES"),),
            ),
        ),
        capital_base=Money(amount=Decimal("100000"), currency="USD"),
    )


def _build_bundle() -> ResultBundle:
    run_spec = _build_run_spec()
    return ResultBundle(
        manifest=ArtifactManifest(
            run_id=run_spec.run_id,
            run_spec_hash=run_spec.content_hash,
            runtime_boundary=RuntimeBoundary.NAUTILUS,
            dataset_id=run_spec.dataset.dataset_id,
            config_hash=run_spec.content_hash,
            symbol_universe=("ES",),
            strategy_ids=("sma_pullback",),
            capital_base=Money(amount=Decimal("100000"), currency="USD"),
            semantic_policy_version="v1",
        ),
        provenance=ProvenanceRecord(
            run_id=run_spec.run_id,
            run_spec_hash=run_spec.content_hash,
            dataset_id=run_spec.dataset.dataset_id,
            created_at_utc=datetime(2026, 4, 3, tzinfo=timezone.utc),
        ),
        run_spec=run_spec,
        artifact_locations={"runtime_root": f"var/runtime/nautilus/{run_spec.run_id}"},
        summary={"net_profit": 1250.0},
    )


def test_filesystem_artifact_store_persists_bundle_json(tmp_path: Path) -> None:
    store = FilesystemArtifactStore(results_root=tmp_path / "results")
    bundle = _build_bundle()

    saved = store.save_bundle(bundle)
    saved_path = Path(saved.bundle_uri)

    assert saved.bundle_id == bundle.bundle_id
    assert saved_path.name == "bundle.json"
    assert saved_path.is_file()


def test_filesystem_bundle_loader_reads_bundle_file_or_directory(tmp_path: Path) -> None:
    results_root = tmp_path / "results"
    bundle = _build_bundle()
    saved = FilesystemArtifactStore(results_root=results_root).save_bundle(bundle)
    loader = FilesystemBundleLoader()

    loaded_from_file = loader.load_bundle(Path(saved.bundle_uri))
    loaded_from_directory = loader.load_bundle(results_root / bundle.bundle_id)

    assert loaded_from_file == bundle
    assert loaded_from_directory == bundle


def test_filesystem_bundle_loader_raises_typed_error_for_invalid_payload(tmp_path: Path) -> None:
    bundle_path = tmp_path / "results" / "broken" / "bundle.json"
    bundle_path.parent.mkdir(parents=True)
    bundle_path.write_text('{"manifest": "not-a-bundle"}', encoding="utf-8")

    loader = FilesystemBundleLoader()

    with pytest.raises(InfrastructureError, match="failed validation"):
        loader.load_bundle(bundle_path)
