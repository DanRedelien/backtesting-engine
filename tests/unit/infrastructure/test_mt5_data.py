from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from backtest_engine.config.data import Mt5DataSettings
from backtest_engine.core.enums import DatasetSource
from backtest_engine.core.errors import InfrastructureError
from backtest_engine.infrastructure.data import (
    FilesystemHistoricalDataStore,
    ProviderUnavailableError,
    SourceDownloadCheckpoint,
    SourceSliceManifest,
)
from backtest_engine.infrastructure.data.mt5.provider import Mt5HistoricalDataProvider


class _ScriptedMt5Client:
    def __init__(self, responses: list[pd.DataFrame | Exception]) -> None:
        self.settings = Mt5DataSettings(
            broker_timezone_name="Europe/Riga",
            max_poll_attempts=1,
            poll_delay_sec=0.0001,
            chunk_days=1,
        )
        self._responses = list(responses)
        self.fetch_calls: list[tuple[str, str, datetime, datetime]] = []
        self.connected = False

    def connect(self) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def session_metadata(self) -> dict[str, str | int | float | bool | None]:
        return {
            "account_server": "Pepperstone-Demo",
            "account_login": 123456,
            "timestamp_semantics": "broker_local_epoch_seconds_normalized_to_utc",
        }

    def fetch_with_poll(
        self,
        *,
        provider_symbol: str,
        timeframe: str,
        start_utc: datetime,
        end_utc: datetime,
    ) -> pd.DataFrame:
        self.fetch_calls.append((provider_symbol, timeframe, start_utc, end_utc))
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response.copy()


def _write_mt5_symbol_map(path: Path) -> Path:
    symbol_map_path = path / "symbol_map.yaml"
    symbol_map_path.write_text(
        """
schema_version: 2
owner: tests
description: MT5 provider test symbol map
defaults: {}
mappings:
  - mt5_symbol: EURUSD
    provider_symbol: EURUSD.raw
    aliases:
      - EURUSDm
    nautilus_symbol: EUR/USD
    nautilus_instrument_id: EUR/USD.SIM
    instrument_type: CURRENCY_PAIR
    venue: SIM
    asset_class: FX
    base_currency: EUR
    quote_currency: USD
    price_precision: 5
    size_precision: 2
    tick_size: 0.00001
    point_size: 0.00001
    size_increment: 0.01
    lot_size: 100000
""".strip(),
        encoding="utf-8",
    )
    return symbol_map_path


def _build_daily_frame(timestamp: str, price: float) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": [price],
            "high": [price + 0.0010],
            "low": [price - 0.0010],
            "close": [price + 0.0005],
            "volume": [10.0],
        },
        index=pd.to_datetime([timestamp], utc=True),
    )


def _build_manifest(
    store: FilesystemHistoricalDataStore,
    *,
    frame: pd.DataFrame,
) -> SourceSliceManifest:
    return SourceSliceManifest(
        provider_id="mt5",
        source_system=DatasetSource.MT5,
        canonical_symbol="EURUSD",
        provider_symbol="EURUSD.raw",
        timeframe="1d",
        calendar_id="FX_24_5",
        timezone_name="Europe/Riga",
        bars_path=store.bars_path("mt5", "EURUSD", "1d"),
        requested_start_utc=datetime(2024, 1, 1, tzinfo=timezone.utc),
        requested_end_utc=datetime(2024, 1, 3, tzinfo=timezone.utc),
        actual_start_utc=frame.index.min().to_pydatetime(),
        actual_end_utc=frame.index.max().to_pydatetime(),
        generated_at_utc=datetime(2026, 4, 12, tzinfo=timezone.utc),
        row_count=len(frame),
        source_fingerprint="0" * 64,
        instrument_metadata={
            "provider_symbol": "EURUSD.raw",
            "instrument_type": "CURRENCY_PAIR",
            "tick_size": 0.00001,
        },
    )


def test_mt5_provider_uses_resolved_provider_symbol_and_resumes_from_checkpoint(tmp_path: Path) -> None:
    store = FilesystemHistoricalDataStore(source_cache_root=tmp_path / "source")
    symbol_map_path = _write_mt5_symbol_map(tmp_path)
    existing = _build_daily_frame("2024-01-03T00:00:00Z", 1.1030)
    store.save_source_slice(manifest=_build_manifest(store, frame=existing), frame=existing)
    store.save_checkpoint(
        SourceDownloadCheckpoint(
            provider_id="mt5",
            canonical_symbol="EURUSD",
            timeframe="1d",
            last_timestamp_utc=datetime(2024, 1, 3, tzinfo=timezone.utc),
            total_bars=1,
            updated_at_utc=datetime(2026, 4, 12, tzinfo=timezone.utc),
        )
    )
    first_client = _ScriptedMt5Client(
        responses=[
            _build_daily_frame("2024-01-02T00:00:00Z", 1.1020),
            ProviderUnavailableError("MT5 terminal dropped during resume"),
        ]
    )
    provider = Mt5HistoricalDataProvider(
        settings=first_client.settings,
        store=store,
        client=first_client,
        symbol_map_path=symbol_map_path,
    )

    with pytest.raises(ProviderUnavailableError):
        provider.download_slice(
            requested_symbol="EURUSDm",
            timeframe="1d",
            start_utc=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end_utc=datetime(2024, 1, 3, tzinfo=timezone.utc),
            force=False,
            dry_run=False,
            requested_by="tests",
        )

    partial = store.load_source_frame("mt5", "EURUSD", "1d")
    checkpoint = store.load_checkpoint("mt5", "EURUSD", "1d")
    assert tuple(partial.index) == (
        pd.Timestamp("2024-01-02T00:00:00Z"),
        pd.Timestamp("2024-01-03T00:00:00Z"),
    )
    assert checkpoint is not None
    assert checkpoint.last_timestamp_utc == datetime(2024, 1, 2, tzinfo=timezone.utc)
    assert all(call[0] == "EURUSD.raw" for call in first_client.fetch_calls)

    second_client = _ScriptedMt5Client(responses=[_build_daily_frame("2024-01-01T00:00:00Z", 1.1010)])
    resumed_provider = Mt5HistoricalDataProvider(
        settings=second_client.settings,
        store=store,
        client=second_client,
        symbol_map_path=symbol_map_path,
    )

    downloaded = resumed_provider.download_slice(
        requested_symbol="EURUSDm",
        timeframe="1d",
        start_utc=datetime(2024, 1, 1, tzinfo=timezone.utc),
        end_utc=datetime(2024, 1, 3, tzinfo=timezone.utc),
        force=False,
        dry_run=False,
        requested_by="tests",
    )

    source_manifest = store.load_source_manifest("mt5", "EURUSD", "1d")
    recovered = store.load_source_frame("mt5", "EURUSD", "1d")

    assert downloaded.canonical_symbol == "EURUSD"
    assert source_manifest.provider_symbol == "EURUSD.raw"
    assert tuple(recovered.index) == (
        pd.Timestamp("2024-01-01T00:00:00Z"),
        pd.Timestamp("2024-01-02T00:00:00Z"),
        pd.Timestamp("2024-01-03T00:00:00Z"),
    )
    assert tuple(recovered["open"]) == (1.1010, 1.1020, 1.1030)
    assert store.load_checkpoint("mt5", "EURUSD", "1d") is None
    assert all(call[0] == "EURUSD.raw" for call in second_client.fetch_calls)


def test_mt5_provider_rejects_missing_broker_timezone(tmp_path: Path) -> None:
    """Plan requires explicit BTE_DATA__MT5__BROKER_TIMEZONE_NAME."""
    store = FilesystemHistoricalDataStore(source_cache_root=tmp_path / "source")
    symbol_map_path = _write_mt5_symbol_map(tmp_path)
    settings_without_tz = Mt5DataSettings(
        broker_timezone_name=None,
        max_poll_attempts=1,
        poll_delay_sec=0.0001,
        chunk_days=1,
    )
    provider = Mt5HistoricalDataProvider(
        settings=settings_without_tz,
        store=store,
        symbol_map_path=symbol_map_path,
    )

    with pytest.raises(InfrastructureError, match="broker timezone"):
        provider.download_slice(
            requested_symbol="EURUSDm",
            timeframe="1d",
            start_utc=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end_utc=datetime(2024, 1, 3, tzinfo=timezone.utc),
            force=False,
            dry_run=False,
            requested_by="tests",
        )


def test_mt5_provider_dry_run_surfaces_metadata(tmp_path: Path) -> None:
    """Dry-run must surface provider symbol, timeframes, window, and calendar."""
    store = FilesystemHistoricalDataStore(source_cache_root=tmp_path / "source")
    symbol_map_path = _write_mt5_symbol_map(tmp_path)
    settings = Mt5DataSettings(
        broker_timezone_name=None,
        max_poll_attempts=1,
        poll_delay_sec=0.0001,
        chunk_days=1,
    )
    provider = Mt5HistoricalDataProvider(
        settings=settings,
        store=store,
        symbol_map_path=symbol_map_path,
    )

    result = provider.download_slice(
        requested_symbol="EURUSDm",
        timeframe="1d",
        start_utc=datetime(2024, 1, 1, tzinfo=timezone.utc),
        end_utc=datetime(2024, 1, 3, tzinfo=timezone.utc),
        force=False,
        dry_run=True,
        requested_by="tests",
    )

    assert result.dry_run is True
    assert result.dry_run_metadata is not None
    assert result.dry_run_metadata.provider_symbol == "EURUSD.raw"
    assert "1d" in result.dry_run_metadata.supported_timeframes
    assert result.dry_run_metadata.window_mode == "explicit"
    assert result.dry_run_metadata.requested_start_utc == datetime(2024, 1, 1, tzinfo=timezone.utc)
    assert result.dry_run_metadata.requested_end_utc == datetime(2024, 1, 3, tzinfo=timezone.utc)
    assert result.dry_run_metadata.calendar_id == "FX_24_5"


def test_mt5_provider_dry_run_without_dates_marks_max_available(tmp_path: Path) -> None:
    store = FilesystemHistoricalDataStore(source_cache_root=tmp_path / "source")
    symbol_map_path = _write_mt5_symbol_map(tmp_path)
    settings = Mt5DataSettings(
        broker_timezone_name=None,
        max_poll_attempts=1,
        poll_delay_sec=0.0001,
        chunk_days=1,
    )
    provider = Mt5HistoricalDataProvider(
        settings=settings,
        store=store,
        symbol_map_path=symbol_map_path,
    )

    result = provider.download_slice(
        requested_symbol="EURUSDm",
        timeframe="1d",
        start_utc=None,
        end_utc=None,
        force=False,
        dry_run=True,
        requested_by="tests",
    )

    assert result.dry_run_metadata is not None
    assert result.dry_run_metadata.window_mode == "max_available"


def test_mt5_provider_force_redownload_replaces_existing_source_slice(tmp_path: Path) -> None:
    store = FilesystemHistoricalDataStore(source_cache_root=tmp_path / "source")
    symbol_map_path = _write_mt5_symbol_map(tmp_path)
    existing = pd.concat(
        [
            _build_daily_frame("2024-01-01T00:00:00Z", 1.2010),
            _build_daily_frame("2024-01-02T00:00:00Z", 1.2020),
            _build_daily_frame("2024-01-03T00:00:00Z", 1.2030),
        ]
    )
    store.save_source_slice(manifest=_build_manifest(store, frame=existing), frame=existing)
    client = _ScriptedMt5Client(
        responses=[
            _build_daily_frame("2024-01-03T00:00:00Z", 1.1030),
            _build_daily_frame("2024-01-02T00:00:00Z", 1.1020),
            _build_daily_frame("2024-01-01T00:00:00Z", 1.1010),
        ]
    )
    provider = Mt5HistoricalDataProvider(
        settings=client.settings,
        store=store,
        client=client,
        symbol_map_path=symbol_map_path,
    )

    provider.download_slice(
        requested_symbol="EURUSDm",
        timeframe="1d",
        start_utc=datetime(2024, 1, 1, tzinfo=timezone.utc),
        end_utc=datetime(2024, 1, 3, tzinfo=timezone.utc),
        force=True,
        dry_run=False,
        requested_by="tests",
    )

    recovered = store.load_source_frame("mt5", "EURUSD", "1d")
    assert tuple(recovered["open"]) == (1.1010, 1.1020, 1.1030)
    assert len(client.fetch_calls) == 3
