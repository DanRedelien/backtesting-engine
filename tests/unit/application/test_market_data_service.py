# mypy: disable-error-code=no-untyped-def
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from backtest_engine.application.market_data import (
    HistoricalMarketDataRequest,
    HistoricalMarketDataService,
    MarketDataVerificationRequest,
    PartialBatchFailureError,
)
from backtest_engine.core.errors import ApplicationError
from backtest_engine.core.enums import DatasetSource
from backtest_engine.infrastructure.data import (
    DownloadedSourceSlice,
    FilesystemHistoricalDataStore,
    SourceSliceManifest,
    SymbolMappingError,
    ValidationManifestPersistenceError,
    ValidationManifest,
    VerificationFailedError,
)


class _FakeProvider:
    provider_id = "mt5"
    source_system = DatasetSource.MT5

    def __init__(self, store: FilesystemHistoricalDataStore) -> None:
        self.store = store
        self.download_calls: list[tuple[str, str]] = []

    def supported_timeframes(self) -> tuple[str, ...]:
        return ("5m",)

    def canonical_symbol_for(self, requested_symbol: str) -> str:
        return "EURUSD"

    def download_slice(self, **kwargs):  # noqa: ANN003
        self.download_calls.append((kwargs["requested_symbol"], kwargs["timeframe"]))
        raise AssertionError("download_slice should not be called when a verified canonical slice already exists")


class _FakeVerifier:
    ruleset_version = "market_data_rules_v5"

    def __init__(self, store: FilesystemHistoricalDataStore) -> None:
        self.store = store

    def validate_slice(self, **kwargs):  # noqa: ANN003
        raise AssertionError("validate_slice is not expected in this test")


class _BatchAwareProvider:
    provider_id = "mt5"
    source_system = DatasetSource.MT5

    def __init__(self, store: FilesystemHistoricalDataStore) -> None:
        self.store = store
        self.download_calls: list[tuple[str, str]] = []

    def supported_timeframes(self) -> tuple[str, ...]:
        return ("5m", "15m")

    def canonical_symbol_for(self, requested_symbol: str) -> str:
        if requested_symbol == "BAD":
            raise SymbolMappingError(
                "unknown MT5 symbol mapping",
                requested_symbol=requested_symbol,
            )
        return requested_symbol

    def download_slice(self, **kwargs):  # noqa: ANN003
        requested_symbol = kwargs["requested_symbol"]
        timeframe = kwargs["timeframe"]
        self.download_calls.append((requested_symbol, timeframe))
        return DownloadedSourceSlice(
            provider_id="mt5",
            source_system=DatasetSource.MT5,
            canonical_symbol=requested_symbol,
            timeframe=timeframe,
            bars_path=Path(f"data/cache/mt5/{requested_symbol}/{timeframe}/bars.parquet"),
            source_manifest_path=Path(f"data/cache/mt5/{requested_symbol}/{timeframe}/source_manifest.json"),
        )


class _BatchAwareVerifier:
    ruleset_version = "market_data_rules_v5"

    def __init__(self, store: FilesystemHistoricalDataStore) -> None:
        self.store = store
        self.calls: list[tuple[str, str, str]] = []

    def validate_slice(self, **kwargs):  # noqa: ANN003
        self.calls.append((kwargs["provider_id"], kwargs["canonical_symbol"], kwargs["timeframe"]))
        return ValidationManifest(
            provider_id=kwargs["provider_id"],
            canonical_symbol=kwargs["canonical_symbol"],
            timeframe=kwargs["timeframe"],
            source_fingerprint="a" * 64,
            validator_ruleset_version=self.ruleset_version,
            verification_verdict="PASS",
            verified_at_utc=datetime(2026, 4, 11, tzinfo=timezone.utc),
        )


class _PersistingFailVerifier:
    ruleset_version = "market_data_rules_v5"

    def __init__(self, store: FilesystemHistoricalDataStore) -> None:
        self.store = store

    def validate_slice(self, **kwargs):  # noqa: ANN003
        manifest = ValidationManifest(
            provider_id=kwargs["provider_id"],
            canonical_symbol=kwargs["canonical_symbol"],
            timeframe=kwargs["timeframe"],
            source_fingerprint="f" * 64,
            validator_ruleset_version=self.ruleset_version,
            verification_verdict="FAIL",
            verified_at_utc=datetime(2026, 4, 11, tzinfo=timezone.utc),
        )
        self.store.save_validation_manifest(manifest)
        raise VerificationFailedError(
            "market-data verification failed",
            validation_manifest=manifest,
            validation_manifest_path=self.store.validation_manifest_path(
                kwargs["provider_id"],
                kwargs["canonical_symbol"],
                kwargs["timeframe"],
            ),
            provider_id=kwargs["provider_id"],
            symbol=kwargs["canonical_symbol"],
            timeframe=kwargs["timeframe"],
            failure_count=1,
        )


class _PersistenceErrorVerifier:
    ruleset_version = "market_data_rules_v5"

    def __init__(self, store: FilesystemHistoricalDataStore) -> None:
        self.store = store

    def validate_slice(self, **kwargs):  # noqa: ANN003
        raise ValidationManifestPersistenceError(
            "failed to persist validation manifest",
            provider_id=kwargs["provider_id"],
            symbol=kwargs["canonical_symbol"],
            timeframe=kwargs["timeframe"],
        )


class _NonPersistingFailVerifier:
    ruleset_version = "market_data_rules_v5"

    def __init__(self, store: FilesystemHistoricalDataStore) -> None:
        self.store = store

    def validate_slice(self, **kwargs):  # noqa: ANN003
        manifest = ValidationManifest(
            provider_id=kwargs["provider_id"],
            canonical_symbol=kwargs["canonical_symbol"],
            timeframe=kwargs["timeframe"],
            source_fingerprint="f" * 64,
            validator_ruleset_version=self.ruleset_version,
            verification_verdict="FAIL",
            verified_at_utc=datetime(2026, 4, 11, tzinfo=timezone.utc),
        )
        raise VerificationFailedError(
            "market-data verification failed",
            validation_manifest=manifest,
            validation_manifest_path=Path("/virtual/validation_manifest.json"),
            provider_id=kwargs["provider_id"],
            symbol=kwargs["canonical_symbol"],
            timeframe=kwargs["timeframe"],
            failure_count=1,
        )


def test_market_data_service_skips_alias_when_verified_canonical_slice_exists(tmp_path: Path) -> None:
    store = FilesystemHistoricalDataStore(source_cache_root=tmp_path)
    frame = pd.DataFrame(
        {
            "open": [1.0, 1.1],
            "high": [1.1, 1.2],
            "low": [0.9, 1.0],
            "close": [1.05, 1.15],
            "volume": [10.0, 10.0],
        },
        index=pd.to_datetime(["2024-01-01T00:00:00Z", "2024-01-01T00:05:00Z"], utc=True),
    )
    manifest = store.save_source_slice(
        manifest=SourceSliceManifest(
            provider_id="mt5",
            source_system=DatasetSource.MT5,
            canonical_symbol="EURUSD",
            provider_symbol="EURUSD",
            timeframe="5m",
            calendar_id="FX_24_5",
            timezone_name="UTC",
            bars_path=store.bars_path("mt5", "EURUSD", "5m"),
            requested_start_utc=frame.index.min().to_pydatetime(),
            requested_end_utc=frame.index.max().to_pydatetime(),
            actual_start_utc=frame.index.min().to_pydatetime(),
            actual_end_utc=frame.index.max().to_pydatetime(),
            generated_at_utc=datetime(2026, 4, 11, tzinfo=timezone.utc),
            row_count=len(frame),
            source_fingerprint="0" * 64,
            instrument_metadata={},
        ),
        frame=frame,
    )
    store.save_validation_manifest(
        ValidationManifest(
            provider_id="mt5",
            canonical_symbol="EURUSD",
            timeframe="5m",
            source_fingerprint=manifest.source_fingerprint,
            validator_ruleset_version="market_data_rules_v5",
            verification_verdict="PASS",
            verified_at_utc=datetime(2026, 4, 11, tzinfo=timezone.utc),
        )
    )

    provider = _FakeProvider(store)
    service = HistoricalMarketDataService(
        store=store,
        providers={"mt5": provider},
        verifier=_FakeVerifier(store),
    )

    result = service.download(
        HistoricalMarketDataRequest(
            provider_id="mt5",
            symbol_universe=("EURUSDm",),
            timeframes=("5m",),
            start_utc=frame.index.min().to_pydatetime(),
            end_utc=frame.index.max().to_pydatetime(),
        )
    )

    assert result.succeeded is True
    assert result.slice_results[0].status == "skipped_verified"
    assert provider.download_calls == []


def test_market_data_service_max_available_mode_does_not_skip_existing_verified_slice(tmp_path: Path) -> None:
    store = FilesystemHistoricalDataStore(source_cache_root=tmp_path)
    frame = pd.DataFrame(
        {
            "open": [1.0, 1.1],
            "high": [1.1, 1.2],
            "low": [0.9, 1.0],
            "close": [1.05, 1.15],
            "volume": [10.0, 10.0],
        },
        index=pd.to_datetime(["2024-01-01T00:00:00Z", "2024-01-01T00:05:00Z"], utc=True),
    )
    manifest = store.save_source_slice(
        manifest=SourceSliceManifest(
            provider_id="mt5",
            source_system=DatasetSource.MT5,
            canonical_symbol="EURUSD",
            provider_symbol="EURUSD",
            timeframe="5m",
            calendar_id="FX_24_5",
            timezone_name="UTC",
            bars_path=store.bars_path("mt5", "EURUSD", "5m"),
            requested_start_utc=frame.index.min().to_pydatetime(),
            requested_end_utc=frame.index.max().to_pydatetime(),
            actual_start_utc=frame.index.min().to_pydatetime(),
            actual_end_utc=frame.index.max().to_pydatetime(),
            generated_at_utc=datetime(2026, 4, 11, tzinfo=timezone.utc),
            row_count=len(frame),
            source_fingerprint="0" * 64,
            instrument_metadata={},
        ),
        frame=frame,
    )
    store.save_validation_manifest(
        ValidationManifest(
            provider_id="mt5",
            canonical_symbol="EURUSD",
            timeframe="5m",
            source_fingerprint=manifest.source_fingerprint,
            validator_ruleset_version="market_data_rules_v5",
            verification_verdict="PASS",
            verified_at_utc=datetime(2026, 4, 11, tzinfo=timezone.utc),
        )
    )
    provider = _BatchAwareProvider(store)
    service = HistoricalMarketDataService(
        store=store,
        providers={"mt5": provider},
        verifier=_FakeVerifier(store),
    )

    result = service.download(
        HistoricalMarketDataRequest(
            provider_id="mt5",
            symbol_universe=("EURUSD",),
            timeframes=("5m",),
        )
    )

    assert result.succeeded is True
    assert result.slice_results[0].status == "downloaded"
    assert provider.download_calls == [("EURUSD", "5m")]


def test_market_data_service_download_continues_after_symbol_mapping_error(tmp_path: Path) -> None:
    store = FilesystemHistoricalDataStore(source_cache_root=tmp_path)
    service = HistoricalMarketDataService(
        store=store,
        providers={"mt5": _BatchAwareProvider(store)},
        verifier=_FakeVerifier(store),
    )

    with pytest.raises(PartialBatchFailureError) as exc_info:
        service.download(
            HistoricalMarketDataRequest(
                provider_id="mt5",
                symbol_universe=("GOOD", "BAD"),
                timeframes=("5m", "15m"),
                start_utc=datetime(2024, 1, 1, tzinfo=timezone.utc),
                end_utc=datetime(2024, 1, 2, tzinfo=timezone.utc),
            )
        )

    result = exc_info.value.batch_result
    assert result.succeeded is False
    assert tuple((item.canonical_symbol, item.timeframe, item.status) for item in result.slice_results) == (
        ("GOOD", "5m", "downloaded"),
        ("GOOD", "15m", "downloaded"),
        ("BAD", "5m", "failed"),
        ("BAD", "15m", "failed"),
    )


def test_market_data_service_verify_continues_after_symbol_mapping_error(tmp_path: Path) -> None:
    store = FilesystemHistoricalDataStore(source_cache_root=tmp_path)
    verifier = _BatchAwareVerifier(store)
    service = HistoricalMarketDataService(
        store=store,
        providers={"mt5": _BatchAwareProvider(store)},
        verifier=verifier,
    )

    with pytest.raises(PartialBatchFailureError) as exc_info:
        service.verify(
            MarketDataVerificationRequest(
                provider_id="mt5",
                symbol_universe=("GOOD", "BAD"),
                timeframes=("5m", "15m"),
            )
        )

    result = exc_info.value.batch_result
    assert result.succeeded is False
    assert tuple((item.canonical_symbol, item.timeframe, item.status) for item in result.slice_results) == (
        ("GOOD", "5m", "verified"),
        ("GOOD", "15m", "verified"),
        ("BAD", "5m", "failed"),
        ("BAD", "15m", "failed"),
    )
    assert verifier.calls == [
        ("mt5", "GOOD", "5m"),
        ("mt5", "GOOD", "15m"),
    ]


def test_market_data_service_verify_returns_persisted_manifest_on_failed_validation(tmp_path: Path) -> None:
    store = FilesystemHistoricalDataStore(source_cache_root=tmp_path)
    service = HistoricalMarketDataService(
        store=store,
        providers={"mt5": _BatchAwareProvider(store)},
        verifier=_PersistingFailVerifier(store),
    )

    with pytest.raises(PartialBatchFailureError) as exc_info:
        service.verify(
            MarketDataVerificationRequest(
                provider_id="mt5",
                symbol_universe=("GOOD",),
                timeframes=("5m",),
            )
        )

    result = exc_info.value.batch_result
    slice_result = result.slice_results[0]
    assert slice_result.error is not None
    assert slice_result.error.code == "VerificationFailedError"
    assert slice_result.validation_manifest is not None
    assert slice_result.validation_manifest.verification_verdict == "FAIL"


def test_market_data_service_verify_preserves_persistence_failure_without_manifest(tmp_path: Path) -> None:
    store = FilesystemHistoricalDataStore(source_cache_root=tmp_path)
    service = HistoricalMarketDataService(
        store=store,
        providers={"mt5": _BatchAwareProvider(store)},
        verifier=_PersistenceErrorVerifier(store),
    )

    with pytest.raises(PartialBatchFailureError) as exc_info:
        service.verify(
            MarketDataVerificationRequest(
                provider_id="mt5",
                symbol_universe=("GOOD",),
                timeframes=("5m",),
            )
        )

    result = exc_info.value.batch_result
    slice_result = result.slice_results[0]
    assert slice_result.error is not None
    assert slice_result.error.code == "ValidationManifestPersistenceError"
    assert slice_result.validation_manifest is None


def test_market_data_service_verify_uses_manifest_from_error_payload_instead_of_store_reload(tmp_path: Path) -> None:
    store = FilesystemHistoricalDataStore(source_cache_root=tmp_path)
    stale_manifest = ValidationManifest(
        provider_id="mt5",
        canonical_symbol="GOOD",
        timeframe="5m",
        source_fingerprint="s" * 64,
        validator_ruleset_version="market_data_rules_v5",
        verification_verdict="PASS",
        verified_at_utc=datetime(2026, 4, 10, tzinfo=timezone.utc),
    )
    store.save_validation_manifest(stale_manifest)
    service = HistoricalMarketDataService(
        store=store,
        providers={"mt5": _BatchAwareProvider(store)},
        verifier=_NonPersistingFailVerifier(store),
    )

    with pytest.raises(PartialBatchFailureError) as exc_info:
        service.verify(
            MarketDataVerificationRequest(
                provider_id="mt5",
                symbol_universe=("GOOD",),
                timeframes=("5m",),
            )
        )

    result = exc_info.value.batch_result
    slice_result = result.slice_results[0]
    assert slice_result.error is not None
    assert slice_result.error.code == "VerificationFailedError"
    assert slice_result.validation_manifest is not None
    assert slice_result.validation_manifest.verification_verdict == "FAIL"
    assert slice_result.validation_manifest.source_fingerprint == "f" * 64
    assert slice_result.validation_manifest_path == Path("/virtual/validation_manifest.json")


def test_market_data_service_raises_typed_error_for_unknown_provider(tmp_path: Path) -> None:
    store = FilesystemHistoricalDataStore(source_cache_root=tmp_path)
    service = HistoricalMarketDataService(
        store=store,
        providers={"mt5": _BatchAwareProvider(store)},
        verifier=_FakeVerifier(store),
    )

    with pytest.raises(ApplicationError, match="unknown market-data provider"):
        service.download(
            HistoricalMarketDataRequest(
                provider_id="unknown",
                symbol_universe=("EURUSD",),
                timeframes=("5m",),
                start_utc=datetime(2024, 1, 1, tzinfo=timezone.utc),
                end_utc=datetime(2024, 1, 2, tzinfo=timezone.utc),
            )
        )


def test_market_data_service_rejects_provider_store_mismatch(tmp_path: Path) -> None:
    service_store = FilesystemHistoricalDataStore(source_cache_root=tmp_path / "service")
    provider_store = FilesystemHistoricalDataStore(source_cache_root=tmp_path / "provider")

    with pytest.raises(ApplicationError, match="collaborators must share one store") as exc_info:
        HistoricalMarketDataService(
            store=service_store,
            providers={"mt5": _BatchAwareProvider(provider_store)},
            verifier=_FakeVerifier(service_store),
        )

    assert exc_info.value.context["collaborator"] == "provider:mt5"


def test_market_data_service_rejects_verifier_store_mismatch(tmp_path: Path) -> None:
    service_store = FilesystemHistoricalDataStore(source_cache_root=tmp_path / "service")
    verifier_store = FilesystemHistoricalDataStore(source_cache_root=tmp_path / "verifier")

    with pytest.raises(ApplicationError, match="collaborators must share one store") as exc_info:
        HistoricalMarketDataService(
            store=service_store,
            providers={"mt5": _BatchAwareProvider(service_store)},
            verifier=_FakeVerifier(verifier_store),
        )

    assert exc_info.value.context["collaborator"] == "verifier"
