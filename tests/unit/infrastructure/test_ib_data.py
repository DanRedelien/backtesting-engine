# mypy: disable-error-code=no-untyped-def
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from backtest_engine.config.data import IbDataSettings
from backtest_engine.core.enums import DatasetSource
from backtest_engine.domain.market.datasets import DatasetSpec
from backtest_engine.infrastructure.data import (
    FilesystemHistoricalDataStore,
    FilesystemIbCacheStore,
    FilesystemParquetCacheStore,
    FilesystemParquetDatasetNormalizer,
    IbHistoricalDataProvider,
    IbContractResolver,
    IbHistoricalCacheIngestor,
    IbHistoricalIngestRequest,
    IbResolvedContract,
    SourceDownloadCheckpoint,
    SourceSliceManifest,
    ValidationManifest,
)
from backtest_engine.infrastructure.data.ib.provider import _build_roll_contract_windows


def _build_dataset(source_system: DatasetSource) -> DatasetSpec:
    return DatasetSpec(
        source_system=source_system,
        normalization_policy="nautilus_v1",
        schema_version="1",
        symbol_universe=("ES",),
        timeframe="30m",
        dataset_version="2026-04-04",
    )


def _build_source_frame(start_price: float = 100.0) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": [start_price, start_price + 1],
            "high": [start_price + 1, start_price + 2],
            "low": [start_price - 1, start_price],
            "close": [start_price + 0.5, start_price + 1.5],
            "volume": [10.0, 10.0],
            "average": [start_price + 0.25, start_price + 1.25],
            "barCount": [5, 5],
        },
        index=pd.to_datetime(
            [
                "2024-01-01T00:00:00Z",
                "2024-01-01T00:30:00Z",
            ],
            utc=True,
        ),
    )


class _FakeContractClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def list_contracts(
        self,
        *,
        symbol: str,
        ib_symbol: str,
        exchange: str,
    ) -> tuple[IbResolvedContract, ...]:
        self.calls.append((symbol, ib_symbol, exchange))
        return (
            IbResolvedContract(
                symbol=symbol,
                exchange=exchange,
                local_symbol="ESF4",
                expiry_utc=datetime(2024, 1, 19, tzinfo=timezone.utc),
                contract_handle=object(),
            ),
            IbResolvedContract(
                symbol=symbol,
                exchange=exchange,
                local_symbol="ESH4",
                expiry_utc=datetime(2024, 3, 15, tzinfo=timezone.utc),
                contract_handle=object(),
            ),
            IbResolvedContract(
                symbol=symbol,
                exchange=exchange,
                local_symbol="ESM4",
                expiry_utc=datetime(2024, 6, 21, tzinfo=timezone.utc),
                contract_handle=object(),
            ),
        )


class _FakeHistoricalClient:
    def __init__(self) -> None:
        self.settings = IbDataSettings(
            delayed_data_minutes=0,
            max_historical_years=1,
            pacing_delay_sec=0.0001,
        )
        self.connected = False
        self.fetch_calls: list[str] = []
        self._frames = {
            "NEW": self._make_chunk("2024-03-21T00:00:00Z", 100.0, 101.0),
            "MID": self._make_chunk("2024-03-14T00:00:00Z", 90.0, 91.0),
            "OLD": self._make_chunk("2024-03-07T00:00:00Z", 80.0, 81.0),
        }

    @staticmethod
    def _make_chunk(timestamp: str, open_price: float, close_price: float) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "open": [open_price],
                "high": [max(open_price, close_price)],
                "low": [min(open_price, close_price)],
                "close": [close_price],
                "average": [(open_price + close_price) / 2.0],
                "volume": [1.0],
            },
            index=pd.DatetimeIndex([pd.Timestamp(timestamp)]),
        )

    def connect(self) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def fetch_chunk(self, contract, *, end_utc, timeframe, duration):  # noqa: ANN001
        self.fetch_calls.append(contract.local_symbol)
        return self._frames[contract.local_symbol].copy()


class _FakeContractResolver:
    def __init__(self) -> None:
        self._contracts = (
            IbResolvedContract(
                symbol="ES",
                exchange="CME",
                local_symbol="NEW",
                expiry_utc=datetime(2024, 4, 1, tzinfo=timezone.utc),
                contract_handle=object(),
            ),
            IbResolvedContract(
                symbol="ES",
                exchange="CME",
                local_symbol="MID",
                expiry_utc=datetime(2024, 3, 20, tzinfo=timezone.utc),
                contract_handle=object(),
            ),
            IbResolvedContract(
                symbol="ES",
                exchange="CME",
                local_symbol="OLD",
                expiry_utc=datetime(2024, 3, 10, tzinfo=timezone.utc),
                contract_handle=object(),
            ),
        )
        self._by_date = {
            datetime(2024, 3, 21, tzinfo=timezone.utc): self._contracts[0],
            datetime(2024, 3, 14, tzinfo=timezone.utc): self._contracts[1],
            datetime(2024, 3, 7, tzinfo=timezone.utc): self._contracts[2],
        }

    def resolve_contract_chain(self, symbol: str) -> tuple[IbResolvedContract, ...]:
        assert symbol == "ES"
        return self._contracts

    def select_contract(
        self,
        contracts: tuple[IbResolvedContract, ...],
        *,
        target_utc: datetime,
    ) -> IbResolvedContract | None:
        assert contracts == self._contracts
        return self._by_date.get(target_utc)


class _ResumeHistoricalClient:
    def __init__(self) -> None:
        self.settings = IbDataSettings(
            delayed_data_minutes=0,
            max_historical_years=1,
            pacing_delay_sec=0.0001,
            chunk_duration="1 W",
        )
        self.connected = False
        self.fetch_calls: list[str] = []
        self._frames = {
            "MID": pd.DataFrame(
                {
                    "open": [100.0],
                    "high": [100.25],
                    "low": [99.75],
                    "close": [100.25],
                    "average": [100.125],
                    "volume": [1.0],
                },
                index=pd.to_datetime(["2024-03-14T00:00:00Z"], utc=True),
            ),
            "OLD": pd.DataFrame(
                {
                    "open": [99.0],
                    "high": [99.25],
                    "low": [98.75],
                    "close": [99.25],
                    "average": [99.125],
                    "volume": [1.0],
                },
                index=pd.to_datetime(["2024-03-07T00:00:00Z"], utc=True),
            ),
        }

    def connect(self) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def fetch_chunk(self, contract, *, end_utc, timeframe, duration):  # noqa: ANN001
        self.fetch_calls.append(contract.local_symbol)
        return self._frames[contract.local_symbol].copy()


class _ResumeContractResolver:
    def __init__(self) -> None:
        self._contracts = (
            IbResolvedContract(
                symbol="ES",
                exchange="CME",
                local_symbol="NEW",
                expiry_utc=datetime(2024, 4, 1, tzinfo=timezone.utc),
                contract_handle=object(),
            ),
            IbResolvedContract(
                symbol="ES",
                exchange="CME",
                local_symbol="MID",
                expiry_utc=datetime(2024, 3, 20, tzinfo=timezone.utc),
                contract_handle=object(),
            ),
            IbResolvedContract(
                symbol="ES",
                exchange="CME",
                local_symbol="OLD",
                expiry_utc=datetime(2024, 3, 10, tzinfo=timezone.utc),
                contract_handle=object(),
            ),
        )

    def resolve_contract_chain(self, symbol: str) -> tuple[IbResolvedContract, ...]:
        assert symbol == "ES"
        return self._contracts

    def select_contract(
        self,
        contracts: tuple[IbResolvedContract, ...],
        *,
        target_utc: datetime,
    ) -> IbResolvedContract | None:
        assert contracts == self._contracts
        if target_utc >= datetime(2024, 3, 14, tzinfo=timezone.utc):
            return self._contracts[1]
        if target_utc >= datetime(2024, 3, 7, tzinfo=timezone.utc):
            return self._contracts[2]
        return None


def test_contract_resolver_prefers_quarterly_contracts_and_active_selection() -> None:
    client = _FakeContractClient()
    resolver = IbContractResolver(client=client)  # type: ignore[arg-type]

    contracts = resolver.resolve_contract_chain("ES")
    active = resolver.select_contract(
        contracts,
        target_utc=datetime(2024, 2, 15, tzinfo=timezone.utc),
    )

    assert client.calls == [("ES", "ES", "CME")]
    assert tuple(contract.local_symbol for contract in contracts) == ("ESH4", "ESM4")
    assert active is not None
    assert active.local_symbol == "ESH4"


def test_ib_historical_ingestor_backfills_roll_adjusted_cache(tmp_path: Path) -> None:
    client = _FakeHistoricalClient()
    cache_store = FilesystemIbCacheStore(source_cache_root=tmp_path)
    ingestor = IbHistoricalCacheIngestor(
        client=client,  # type: ignore[arg-type]
        contract_resolver=_FakeContractResolver(),  # type: ignore[arg-type]
        cache_store=cache_store,
        now_provider=lambda: datetime(2024, 3, 21, tzinfo=timezone.utc),
    )

    result = ingestor.ingest(
        IbHistoricalIngestRequest(
            symbol_universe=("ES",),
            timeframe="1h",
            force_restart=True,
            start_utc=datetime(2024, 2, 29, tzinfo=timezone.utc),
            end_utc=datetime(2024, 3, 21, tzinfo=timezone.utc),
        )
    )

    saved = cache_store.load_cache("ES", "1h").sort_index()

    assert not client.connected
    assert tuple(client.fetch_calls) == ("NEW", "MID", "OLD")
    assert result.artifacts[0].cache_path.is_file()
    assert result.artifacts[0].manifest_path.is_file()
    assert saved.loc[pd.Timestamp("2024-03-14T00:00:00Z"), "close"] == 100.0
    assert saved.loc[pd.Timestamp("2024-03-07T00:00:00Z"), "close"] == 99.0
    assert result.artifacts[0].manifest.contract_codes == ("OLD", "MID", "NEW")


def test_parquet_normalizer_materializes_ib_backed_source_cache(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    store = FilesystemHistoricalDataStore(source_cache_root=source_root)
    frame = _build_source_frame()
    manifest = store.save_source_slice(
        manifest=SourceSliceManifest(
            provider_id="ib",
            source_system=DatasetSource.IB,
            canonical_symbol="ES",
            provider_symbol="ES",
            timeframe="30m",
            calendar_id="CME_INDEX_FUTURES",
            timezone_name="UTC",
            bars_path=store.bars_path("ib", "ES", "30m"),
            requested_start_utc=frame.index.min().to_pydatetime(),
            requested_end_utc=frame.index.max().to_pydatetime(),
            actual_start_utc=frame.index.min().to_pydatetime(),
            actual_end_utc=frame.index.max().to_pydatetime(),
            generated_at_utc=datetime(2026, 4, 4, tzinfo=timezone.utc),
            row_count=len(frame),
            source_fingerprint="0" * 64,
            instrument_metadata={},
        ),
        frame=frame,
    )
    store.save_validation_manifest(
        ValidationManifest(
            provider_id="ib",
            canonical_symbol="ES",
            timeframe="30m",
            source_fingerprint=manifest.source_fingerprint,
            validator_ruleset_version="market_data_rules_v5",
            verification_verdict="PASS",
            verified_at_utc=datetime(2026, 4, 4, tzinfo=timezone.utc),
        )
    )
    dataset = _build_dataset(DatasetSource.IB)
    normalizer = FilesystemParquetDatasetNormalizer(
        cache_store=FilesystemParquetCacheStore(source_cache_root=source_root),
        normalized_root=tmp_path / "normalized",
        market_data_store=store,
    )

    materialized = normalizer.materialize(dataset)

    assert materialized.dataset.dataset_id == dataset.dataset_id
    assert materialized.artifacts[0].manifest.source_system is DatasetSource.IB
    assert materialized.artifacts[0].data_path.is_file()


def test_ib_ingest_request_from_dataset_requires_ib_source() -> None:
    request = IbHistoricalIngestRequest.from_dataset(_build_dataset(DatasetSource.IB))

    assert request.symbol_universe == ("ES",)
    assert request.timeframe == "30m"

    try:
        IbHistoricalIngestRequest.from_dataset(_build_dataset(DatasetSource.PARQUET))
    except Exception as exc:  # noqa: BLE001
        assert "DatasetSource.IB" in str(exc)
    else:
        raise AssertionError("expected non-IB dataset to be rejected")


def test_roll_contract_windows_follow_chronology_across_year_boundary(tmp_path: Path) -> None:
    store = FilesystemHistoricalDataStore(source_cache_root=tmp_path)
    merged_raw_frames = {
        "ESH5": pd.DataFrame(
            {"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [1.0]},
            index=pd.to_datetime(["2025-01-03T00:00:00Z"], utc=True),
        ),
        "ESZ4": pd.DataFrame(
            {"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [1.0]},
            index=pd.to_datetime(["2024-12-06T00:00:00Z"], utc=True),
        ),
    }

    windows = _build_roll_contract_windows(
        store=store,
        provider_id="ib",
        canonical_symbol="ES",
        timeframe="1h",
        merged_raw_frames=merged_raw_frames,
    )

    assert tuple(window.contract_code for window in windows) == ("ESZ4", "ESH5")


def test_ib_provider_resumes_from_saved_raw_contract_checkpoint(tmp_path: Path) -> None:
    store = FilesystemHistoricalDataStore(source_cache_root=tmp_path / "source")
    new_raw = pd.DataFrame(
        {
            "open": [101.0],
            "high": [101.25],
            "low": [100.75],
            "close": [101.25],
            "average": [101.125],
            "volume": [1.0],
        },
        index=pd.to_datetime(["2024-03-21T00:00:00Z"], utc=True),
    )
    adjusted = new_raw.copy()
    adjusted["contract"] = ["NEW"]
    store.save_source_slice(
        manifest=SourceSliceManifest(
            provider_id="ib",
            source_system=DatasetSource.IB,
            canonical_symbol="ES",
            provider_symbol="ES",
            timeframe="1d",
            calendar_id="CME_INDEX_FUTURES",
            timezone_name="UTC",
            bars_path=store.bars_path("ib", "ES", "1d"),
            requested_start_utc=datetime(2024, 3, 7, tzinfo=timezone.utc),
            requested_end_utc=datetime(2024, 3, 21, tzinfo=timezone.utc),
            actual_start_utc=adjusted.index.min().to_pydatetime(),
            actual_end_utc=adjusted.index.max().to_pydatetime(),
            generated_at_utc=datetime(2026, 4, 12, tzinfo=timezone.utc),
            row_count=len(adjusted),
            source_fingerprint="0" * 64,
            instrument_metadata={"tick_size": 0.25, "instrument_type": "FUTURES"},
            roll_policy="additive_back_adjusted",
        ),
        frame=adjusted,
        raw_contract_frames={"NEW": new_raw},
    )
    store.save_checkpoint(
        SourceDownloadCheckpoint(
            provider_id="ib",
            canonical_symbol="ES",
            timeframe="1d",
            last_timestamp_utc=datetime(2024, 3, 21, tzinfo=timezone.utc),
            total_bars=1,
            updated_at_utc=datetime(2026, 4, 12, tzinfo=timezone.utc),
        )
    )
    client = _ResumeHistoricalClient()
    provider = IbHistoricalDataProvider(
        settings=client.settings,
        store=store,
        client=client,  # type: ignore[arg-type]
        contract_resolver=_ResumeContractResolver(),  # type: ignore[arg-type]
    )

    downloaded = provider.download_slice(
        requested_symbol="ES",
        timeframe="1d",
        start_utc=datetime(2024, 3, 7, tzinfo=timezone.utc),
        end_utc=datetime(2024, 3, 21, tzinfo=timezone.utc),
        force=False,
        dry_run=False,
        requested_by="tests",
    )

    saved = store.load_source_frame("ib", "ES", "1d")
    roll_manifest = store.load_roll_manifest("ib", "ES", "1d")

    assert not client.connected
    assert downloaded.canonical_symbol == "ES"
    assert client.fetch_calls == ["MID", "OLD"]
    assert tuple(saved.index) == (
        pd.Timestamp("2024-03-07T00:00:00Z"),
        pd.Timestamp("2024-03-14T00:00:00Z"),
        pd.Timestamp("2024-03-21T00:00:00Z"),
    )
    assert tuple(saved["contract"]) == ("OLD", "MID", "NEW")
    assert store.load_checkpoint("ib", "ES", "1d") is None
    assert roll_manifest is not None
    assert tuple(window.contract_code for window in roll_manifest.contract_windows) == ("OLD", "MID", "NEW")
