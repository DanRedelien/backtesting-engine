from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from backtest_engine.core.enums import DatasetSource
from backtest_engine.infrastructure.data import (
    FilesystemHistoricalDataStore,
    RollAdjustmentEvent,
    RollContractWindow,
    RollManifest,
    SourceSliceManifest,
)


def build_frame(*, prices: tuple[float, ...] = (100.0, 101.0)) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": list(prices),
            "high": [price + 0.5 for price in prices],
            "low": [price - 0.5 for price in prices],
            "close": [price + 0.25 for price in prices],
            "volume": [10.0 for _ in prices],
        },
        index=pd.to_datetime(
            ["2024-01-01T00:00:00Z", "2024-01-01T00:30:00Z"][: len(prices)],
            utc=True,
        ),
    )


def build_manifest(
    store: FilesystemHistoricalDataStore,
    *,
    provider_id: str,
    source_system: DatasetSource,
    canonical_symbol: str,
    timeframe: str,
    frame: pd.DataFrame | None = None,
    instrument_metadata: dict[str, str | int | float | bool | None] | None = None,
) -> SourceSliceManifest:
    active_frame = build_frame() if frame is None else frame
    return SourceSliceManifest(
        provider_id=provider_id,
        source_system=source_system,
        canonical_symbol=canonical_symbol,
        provider_symbol=canonical_symbol,
        timeframe=timeframe,
        calendar_id="FX_24_5" if source_system is DatasetSource.MT5 else "CME_INDEX_FUTURES",
        timezone_name="UTC",
        bars_path=store.bars_path(provider_id, canonical_symbol, timeframe),
        requested_start_utc=active_frame.index.min().to_pydatetime(),
        requested_end_utc=active_frame.index.max().to_pydatetime(),
        actual_start_utc=active_frame.index.min().to_pydatetime(),
        actual_end_utc=active_frame.index.max().to_pydatetime(),
        generated_at_utc=datetime(2026, 4, 11, tzinfo=timezone.utc),
        row_count=len(active_frame),
        source_fingerprint="0" * 64,
        instrument_metadata=instrument_metadata or {},
    )


def build_roll_manifest(
    store: FilesystemHistoricalDataStore,
    *,
    provider_id: str,
    canonical_symbol: str,
    timeframe: str,
    raw_contract_frames: dict[str, pd.DataFrame],
    events: tuple[RollAdjustmentEvent, ...],
) -> RollManifest:
    return RollManifest(
        provider_id=provider_id,
        canonical_symbol=canonical_symbol,
        timeframe=timeframe,
        roll_policy="additive_back_adjusted",
        contract_windows=tuple(
            RollContractWindow(
                contract_code=contract_code,
                raw_path=store.raw_contract_path(provider_id, canonical_symbol, timeframe, contract_code),
                start_utc=frame.index.min().to_pydatetime(),
                end_utc=frame.index.max().to_pydatetime(),
            )
            for contract_code, frame in raw_contract_frames.items()
        ),
        events=events,
        generated_at_utc=datetime(2026, 4, 11, tzinfo=timezone.utc),
    )


def save_roll_adjusted_slice(
    store: FilesystemHistoricalDataStore,
    *,
    canonical_symbol: str,
    timeframe: str,
    adjusted_frame: pd.DataFrame,
    raw_contract_frames: dict[str, pd.DataFrame],
    events: tuple[RollAdjustmentEvent, ...],
    instrument_metadata: dict[str, str | int | float | bool | None] | None = None,
) -> None:
    store.save_source_slice(
        manifest=build_manifest(
            store,
            provider_id="ib",
            source_system=DatasetSource.IB,
            canonical_symbol=canonical_symbol,
            timeframe=timeframe,
            frame=adjusted_frame,
            instrument_metadata=instrument_metadata,
        ).model_copy(update={"roll_policy": "additive_back_adjusted"}),
        frame=adjusted_frame,
        raw_contract_frames=raw_contract_frames,
        roll_manifest=build_roll_manifest(
            store,
            provider_id="ib",
            canonical_symbol=canonical_symbol,
            timeframe=timeframe,
            raw_contract_frames=raw_contract_frames,
            events=events,
        ),
    )
