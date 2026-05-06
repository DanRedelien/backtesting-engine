from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from backtest_engine.core.enums import DatasetSource
from backtest_engine.domain.market.datasets import DatasetSpec
from backtest_engine.infrastructure.data import (
    FilesystemHistoricalDataStore,
    FilesystemParquetCacheStore,
    FilesystemParquetDatasetNormalizer,
    MaterializationBlockedError,
    ValidationManifest,
)

from _market_data_pipeline_support import build_frame, build_manifest


def build_dataset() -> DatasetSpec:
    return DatasetSpec(
        source_system=DatasetSource.MT5,
        normalization_policy="nautilus_v1",
        schema_version="1",
        symbol_universe=("EURUSD",),
        timeframe="30m",
        dataset_version="2026-04-11",
    )


def build_pass_validation_manifest(
    *,
    source_fingerprint: str,
    validator_ruleset_version: str = "market_data_rules_v5",
    verified_at_utc: datetime | None = None,
) -> ValidationManifest:
    return ValidationManifest(
        provider_id="mt5",
        canonical_symbol="EURUSD",
        timeframe="30m",
        source_fingerprint=source_fingerprint,
        validator_ruleset_version=validator_ruleset_version,
        verification_verdict="PASS",
        verified_at_utc=verified_at_utc or datetime(2026, 4, 11, tzinfo=timezone.utc),
    )


def build_normalizer(
    *,
    source_root: Path,
    normalized_root: Path,
    store: FilesystemHistoricalDataStore,
) -> FilesystemParquetDatasetNormalizer:
    return FilesystemParquetDatasetNormalizer(
        cache_store=FilesystemParquetCacheStore(source_cache_root=source_root),
        normalized_root=normalized_root,
        market_data_store=store,
    )


def test_source_overwrite_clears_stale_validation_manifest(tmp_path: Path) -> None:
    store = FilesystemHistoricalDataStore(source_cache_root=tmp_path)
    manifest = store.save_source_slice(
        manifest=build_manifest(
            store,
            provider_id="mt5",
            source_system=DatasetSource.MT5,
            canonical_symbol="EURUSD",
            timeframe="30m",
        ),
        frame=build_frame(),
    )
    store.save_validation_manifest(
        build_pass_validation_manifest(source_fingerprint=manifest.source_fingerprint)
    )

    store.save_source_slice(
        manifest=build_manifest(
            store,
            provider_id="mt5",
            source_system=DatasetSource.MT5,
            canonical_symbol="EURUSD",
            timeframe="30m",
        ),
        frame=build_frame(prices=(102.0, 103.0)),
    )

    assert store.load_validation_manifest("mt5", "EURUSD", "30m") is None


def test_materializer_blocks_unverified_mt5_sources(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    store = FilesystemHistoricalDataStore(source_cache_root=source_root)
    store.save_source_slice(
        manifest=build_manifest(
            store,
            provider_id="mt5",
            source_system=DatasetSource.MT5,
            canonical_symbol="EURUSD",
            timeframe="30m",
        ),
        frame=build_frame(),
    )
    normalizer = build_normalizer(
        source_root=source_root,
        normalized_root=tmp_path / "normalized",
        store=store,
    )

    with pytest.raises(MaterializationBlockedError):
        normalizer.materialize(build_dataset())


def test_cached_managed_materialization_does_not_bypass_missing_validation(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    store = FilesystemHistoricalDataStore(source_cache_root=source_root)
    initial_manifest = store.save_source_slice(
        manifest=build_manifest(
            store,
            provider_id="mt5",
            source_system=DatasetSource.MT5,
            canonical_symbol="EURUSD",
            timeframe="30m",
        ),
        frame=build_frame(),
    )
    store.save_validation_manifest(
        build_pass_validation_manifest(source_fingerprint=initial_manifest.source_fingerprint)
    )
    normalizer = build_normalizer(
        source_root=source_root,
        normalized_root=tmp_path / "normalized",
        store=store,
    )

    first = normalizer.materialize(build_dataset())
    assert first.artifacts[0].manifest.source_fingerprint == initial_manifest.source_fingerprint

    store.save_source_slice(
        manifest=build_manifest(
            store,
            provider_id="mt5",
            source_system=DatasetSource.MT5,
            canonical_symbol="EURUSD",
            timeframe="30m",
        ),
        frame=build_frame(prices=(102.0, 103.0)),
    )

    with pytest.raises(MaterializationBlockedError):
        normalizer.materialize(build_dataset())


def test_cached_managed_materialization_rebuilds_after_revalidated_source_change(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    store = FilesystemHistoricalDataStore(source_cache_root=source_root)
    initial_manifest = store.save_source_slice(
        manifest=build_manifest(
            store,
            provider_id="mt5",
            source_system=DatasetSource.MT5,
            canonical_symbol="EURUSD",
            timeframe="30m",
        ),
        frame=build_frame(),
    )
    store.save_validation_manifest(
        build_pass_validation_manifest(source_fingerprint=initial_manifest.source_fingerprint)
    )
    normalizer = build_normalizer(
        source_root=source_root,
        normalized_root=tmp_path / "normalized",
        store=store,
    )

    first = normalizer.materialize(build_dataset())
    updated_source_manifest = store.save_source_slice(
        manifest=build_manifest(
            store,
            provider_id="mt5",
            source_system=DatasetSource.MT5,
            canonical_symbol="EURUSD",
            timeframe="30m",
        ),
        frame=build_frame(prices=(105.0, 106.0)),
    )
    store.save_validation_manifest(
        build_pass_validation_manifest(
            source_fingerprint=updated_source_manifest.source_fingerprint,
            verified_at_utc=datetime(2026, 4, 12, tzinfo=timezone.utc),
        )
    )

    second = normalizer.materialize(build_dataset())
    rebuilt = pd.read_parquet(second.artifacts[0].data_path)

    assert second.artifacts[0].manifest.source_fingerprint == updated_source_manifest.source_fingerprint
    assert second.artifacts[0].manifest.source_fingerprint != first.artifacts[0].manifest.source_fingerprint
    assert tuple(rebuilt["open"]) == (105.0, 106.0)


def test_missing_source_parquet_is_treated_as_incomplete_or_blocked(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    store = FilesystemHistoricalDataStore(source_cache_root=source_root)
    manifest = store.save_source_slice(
        manifest=build_manifest(
            store,
            provider_id="mt5",
            source_system=DatasetSource.MT5,
            canonical_symbol="EURUSD",
            timeframe="30m",
        ),
        frame=build_frame(),
    )
    store.save_validation_manifest(
        build_pass_validation_manifest(source_fingerprint=manifest.source_fingerprint)
    )
    manifest.bars_path.unlink()

    assert (
        store.has_complete_verified_slice(
            provider_id="mt5",
            canonical_symbol="EURUSD",
            timeframe="30m",
            requested_start_utc=manifest.requested_start_utc,
            requested_end_utc=manifest.requested_end_utc,
            validator_ruleset_version="market_data_rules_v5",
        )
        is False
    )

    normalizer = build_normalizer(
        source_root=source_root,
        normalized_root=tmp_path / "normalized",
        store=store,
    )

    with pytest.raises(MaterializationBlockedError):
        normalizer.materialize(build_dataset())


def test_materializer_blocks_source_manifest_path_drift(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    store = FilesystemHistoricalDataStore(source_cache_root=source_root)
    manifest = store.save_source_slice(
        manifest=build_manifest(
            store,
            provider_id="mt5",
            source_system=DatasetSource.MT5,
            canonical_symbol="EURUSD",
            timeframe="30m",
        ),
        frame=build_frame(),
    )
    store.save_validation_manifest(
        build_pass_validation_manifest(source_fingerprint=manifest.source_fingerprint)
    )
    drifted_manifest = manifest.model_copy(update={"bars_path": tmp_path / "other" / "bars.parquet"})
    store.source_manifest_path("mt5", "EURUSD", "30m").write_text(
        drifted_manifest.model_dump_json(indent=2),
        encoding="utf-8",
    )
    normalizer = build_normalizer(
        source_root=source_root,
        normalized_root=tmp_path / "normalized",
        store=store,
    )

    with pytest.raises(MaterializationBlockedError, match="path drift"):
        normalizer.materialize(build_dataset())


def test_old_validation_manifest_becomes_stale_after_ruleset_bump(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    store = FilesystemHistoricalDataStore(source_cache_root=source_root)
    manifest = store.save_source_slice(
        manifest=build_manifest(
            store,
            provider_id="mt5",
            source_system=DatasetSource.MT5,
            canonical_symbol="EURUSD",
            timeframe="30m",
        ),
        frame=build_frame(),
    )
    store.save_validation_manifest(
        build_pass_validation_manifest(
            source_fingerprint=manifest.source_fingerprint,
            validator_ruleset_version="market_data_rules_v3",
        )
    )

    assert (
        store.has_complete_verified_slice(
            provider_id="mt5",
            canonical_symbol="EURUSD",
            timeframe="30m",
            requested_start_utc=manifest.requested_start_utc,
            requested_end_utc=manifest.requested_end_utc,
            validator_ruleset_version="market_data_rules_v5",
        )
        is False
    )
