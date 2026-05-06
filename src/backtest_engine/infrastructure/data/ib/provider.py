"""IB/TWS provider adapter for the unified market-data workflow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter
from typing import Callable

import pandas as pd

from backtest_engine.config.data import IbDataSettings
from backtest_engine.core.enums import DatasetSource
from backtest_engine.core.time import ensure_utc
from backtest_engine.infrastructure.data.errors import (
    InsufficientHistoryError,
    SymbolMappingError,
    UnsupportedTimeframeError,
)
from backtest_engine.infrastructure.data.ib.client import IbHistoricalClient
from backtest_engine.infrastructure.data.ib.contract_resolver import IbContractResolver
from backtest_engine.infrastructure.data.ib.contracts import IbResolvedContract
from backtest_engine.infrastructure.data.ib.timeframes import IbTimeframe
from backtest_engine.infrastructure.data.market_data_contracts import (
    DownloadedSourceSlice,
    DryRunMetadata,
    RollAdjustmentEvent,
    RollContractWindow,
    RollManifest,
    SourceDownloadCheckpoint,
    SourceSliceManifest,
)
from backtest_engine.infrastructure.data.market_data_store import FilesystemHistoricalDataStore
from backtest_engine.infrastructure.data.progress import (
    compute_requested_coverage_progress,
    describe_coverage_gap,
    estimate_eta_sec,
    is_coverage_sufficient,
)
from backtest_engine.infrastructure.nautilus.symbol_map import SymbolMapping, load_symbol_map
from backtest_engine.infrastructure.observability import (
    DiagnosticsSink,
    NullDiagnosticsSink,
    StageDiagnosticEvent,
)

# v1 scope: CME E-mini index futures only.  Expand this set when the
# IB adapter gains support for additional product families.
_SUPPORTED_CANONICAL_SYMBOLS: frozenset[str] = frozenset({"ES", "NQ", "YM", "RTY"})


@dataclass
class IbHistoricalDataProvider:
    """Download additive back-adjusted CME index futures from IB/TWS."""

    settings: IbDataSettings
    store: FilesystemHistoricalDataStore
    client: IbHistoricalClient | None = None
    contract_resolver: IbContractResolver | None = None
    symbol_map_path: Path | None = None
    diagnostics: DiagnosticsSink = NullDiagnosticsSink()

    @property
    def provider_id(self) -> str:
        return "ib"

    @property
    def source_system(self) -> DatasetSource:
        return DatasetSource.IB

    def supported_timeframes(self) -> tuple[str, ...]:
        return tuple(item.file_suffix for item in IbTimeframe)

    def canonical_symbol_for(self, requested_symbol: str) -> str:
        mapping = self._resolve_mapping(requested_symbol)
        if mapping.mt5_symbol not in _SUPPORTED_CANONICAL_SYMBOLS:
            raise SymbolMappingError(
                "IB v1 supports only CME index futures",
                requested_symbol=requested_symbol,
                supported_symbols=",".join(sorted(_SUPPORTED_CANONICAL_SYMBOLS)),
            )
        return mapping.mt5_symbol

    def download_slice(
        self,
        *,
        requested_symbol: str,
        timeframe: str,
        start_utc: datetime | None,
        end_utc: datetime | None,
        force: bool,
        dry_run: bool,
        requested_by: str,
    ) -> DownloadedSourceSlice:
        try:
            resolved_timeframe = IbTimeframe.from_timeframe(timeframe)
        except Exception as exc:
            raise UnsupportedTimeframeError(
                "unsupported IB timeframe",
                timeframe=timeframe,
                supported_timeframes=",".join(self.supported_timeframes()),
            ) from exc
        mapping = self._resolve_mapping(requested_symbol)
        canonical_symbol = self.canonical_symbol_for(requested_symbol)
        requested_start, requested_end, explicit_window = _resolve_download_window(
            start_utc=start_utc,
            end_utc=end_utc,
            settings=self.settings,
        )
        bars_path = self.store.bars_path(self.provider_id, canonical_symbol, timeframe)
        source_manifest_path = self.store.source_manifest_path(
            self.provider_id, canonical_symbol, timeframe
        )
        if dry_run:
            return DownloadedSourceSlice(
                provider_id=self.provider_id,
                source_system=self.source_system,
                canonical_symbol=canonical_symbol,
                timeframe=timeframe,
                bars_path=bars_path,
                source_manifest_path=source_manifest_path,
                dry_run=True,
                dry_run_metadata=DryRunMetadata(
                    provider_symbol=canonical_symbol,
                    supported_timeframes=self.supported_timeframes(),
                    window_mode="explicit" if explicit_window else "max_available",
                    requested_start_utc=requested_start,
                    requested_end_utc=requested_end,
                    calendar_id="CME_INDEX_FUTURES",
                ),
            )

        if force:
            self.store.clear_source_slice(self.provider_id, canonical_symbol, timeframe)

        started_at = perf_counter()
        client = self.client or IbHistoricalClient(settings=self.settings)
        resolver = self.contract_resolver or IbContractResolver(client=client)
        client.connect()
        try:
            contracts = resolver.resolve_contract_chain(canonical_symbol)
            raw_frames = self.store.load_saved_raw_contract_frames(
                self.provider_id, canonical_symbol, timeframe
            )
            checkpoint = self.store.load_checkpoint(self.provider_id, canonical_symbol, timeframe)
            adjusted = _load_existing_adjusted_frame(
                store=self.store,
                provider_id=self.provider_id,
                canonical_symbol=canonical_symbol,
                timeframe=timeframe,
            )
            self._emit_progress(
                requested_by=requested_by,
                canonical_symbol=canonical_symbol,
                timeframe=timeframe,
                requested_start_utc=requested_start,
                requested_end_utc=requested_end,
                frame=adjusted,
                elapsed_sec=perf_counter() - started_at,
            )
            if adjusted.empty and raw_frames:
                adjusted, _ = _build_adjusted_series_from_raw_frames(
                    store=self.store,
                    provider_id=self.provider_id,
                    canonical_symbol=canonical_symbol,
                    timeframe=timeframe,
                    merged_raw_frames=raw_frames,
                )
            pending_windows = _pending_ib_windows(
                frame=adjusted,
                checkpoint=checkpoint,
                requested_start_utc=requested_start,
                requested_end_utc=requested_end,
                timeframe=timeframe,
            )
            for window_start, window_end in pending_windows:
                raw_frames = _fetch_ib_window(
                    client=client,
                    resolver=resolver,
                    store=self.store,
                    provider_id=self.provider_id,
                    source_system=self.source_system,
                    canonical_symbol=canonical_symbol,
                    timeframe=timeframe,
                    resolved_timeframe=resolved_timeframe,
                    requested_start_utc=requested_start,
                    requested_end_utc=requested_end,
                    window_start_utc=window_start,
                    window_end_utc=window_end,
                    raw_frames=raw_frames,
                    contracts=contracts,
                    instrument_metadata=mapping.metadata_dict(),
                    progress_callback=lambda current_frame: self._emit_progress(
                        requested_by=requested_by,
                        canonical_symbol=canonical_symbol,
                        timeframe=timeframe,
                        requested_start_utc=requested_start,
                        requested_end_utc=requested_end,
                        frame=current_frame,
                        elapsed_sec=perf_counter() - started_at,
                    ),
                )

            if not raw_frames:
                raise InsufficientHistoryError(
                    f"IB returned no historical bars for {canonical_symbol} {timeframe} "
                    f"({requested_start.date()}..{requested_end.date()}). "
                    f"IB API limits: max {self.settings.max_historical_years}yr history, "
                    f"{self.settings.delayed_data_minutes}min delay, "
                    f"pacing {self.settings.pacing_delay_sec}s, "
                    f"chunk {self.settings.chunk_duration}.",
                    canonical_symbol=canonical_symbol,
                    timeframe=timeframe,
                    requested_start=requested_start.isoformat(),
                    requested_end=requested_end.isoformat(),
                )

            adjusted, roll_manifest = _build_adjusted_series_from_raw_frames(
                store=self.store,
                provider_id=self.provider_id,
                canonical_symbol=canonical_symbol,
                timeframe=timeframe,
                merged_raw_frames=raw_frames,
            )
            actual_start = adjusted.index.min().to_pydatetime()
            actual_end = adjusted.index.max().to_pydatetime()
            coverage_start = requested_start if explicit_window else actual_start
            if not is_coverage_sufficient(
                actual_start_utc=actual_start,
                actual_end_utc=actual_end,
                requested_start_utc=coverage_start,
                requested_end_utc=requested_end,
                timeframe=timeframe,
                calendar_id="CME_INDEX_FUTURES",
                timezone_name="America/Chicago",
            ):
                gap_desc = describe_coverage_gap(
                    actual_start_utc=actual_start,
                    actual_end_utc=actual_end,
                    requested_start_utc=coverage_start,
                    requested_end_utc=requested_end,
                    timeframe=timeframe,
                    calendar_id="CME_INDEX_FUTURES",
                    timezone_name="America/Chicago",
                )
                message = (
                    f"IB data covers {actual_start.date()}..{actual_end.date()} "
                    f"but {coverage_start.date()}..{requested_end.date()} was requested; {gap_desc}. "
                    f"IB API limits: max {self.settings.max_historical_years}yr, "
                    f"{self.settings.delayed_data_minutes}min delay, "
                    f"chunk {self.settings.chunk_duration}."
                    if explicit_window
                    else (
                        "IB max-available download could not reach the recent end boundary; "
                        f"{gap_desc}."
                    )
                )
                raise InsufficientHistoryError(
                    message,
                    canonical_symbol=canonical_symbol,
                    timeframe=timeframe,
                    requested_start=coverage_start.isoformat(),
                    requested_end=requested_end.isoformat(),
                    actual_start=actual_start.isoformat(),
                    actual_end=actual_end.isoformat(),
                    row_count=len(adjusted),
                    contracts_used=",".join(sorted(raw_frames.keys())),
                )
            manifest = self.store.save_source_slice(
                manifest=SourceSliceManifest(
                    provider_id=self.provider_id,
                    source_system=self.source_system,
                    canonical_symbol=canonical_symbol,
                    provider_symbol=canonical_symbol,
                    timeframe=timeframe,
                    calendar_id="CME_INDEX_FUTURES",
                    timezone_name="UTC",
                    bars_path=bars_path,
                    requested_start_utc=coverage_start,
                    requested_end_utc=requested_end,
                    actual_start_utc=adjusted.index.min().to_pydatetime(),
                    actual_end_utc=adjusted.index.max().to_pydatetime(),
                    generated_at_utc=datetime.now(timezone.utc),
                    row_count=int(len(adjusted)),
                    source_fingerprint="0" * 64,
                    provider_metadata={
                        "host": self.settings.host,
                        "port": self.settings.port,
                        "chunk_duration": self.settings.chunk_duration,
                    },
                    instrument_metadata=mapping.metadata_dict(),
                    roll_policy="additive_back_adjusted",
                ),
                frame=adjusted,
                raw_contract_frames=raw_frames,
                roll_manifest=roll_manifest,
            )
            self.store.clear_checkpoint(self.provider_id, canonical_symbol, timeframe)
        finally:
            client.disconnect()

        return DownloadedSourceSlice(
            provider_id=self.provider_id,
            source_system=self.source_system,
            canonical_symbol=manifest.canonical_symbol,
            timeframe=manifest.timeframe,
            bars_path=manifest.bars_path,
            source_manifest_path=source_manifest_path,
        )

    def _resolve_mapping(self, requested_symbol: str) -> SymbolMapping:
        try:
            return load_symbol_map(self.symbol_map_path).resolve(requested_symbol)
        except KeyError as exc:
            raise SymbolMappingError(
                "unknown IB symbol mapping",
                requested_symbol=requested_symbol,
            ) from exc

    def _emit_progress(
        self,
        *,
        requested_by: str,
        canonical_symbol: str,
        timeframe: str,
        requested_start_utc: datetime,
        requested_end_utc: datetime,
        frame: pd.DataFrame,
        elapsed_sec: float,
    ) -> None:
        self.diagnostics.emit(
            StageDiagnosticEvent(
                stage="market_data.slice.download.progress",
                status="started",
                message="historical market-data slice download progressed",
                requested_by=requested_by,
                details={
                    "provider_id": self.provider_id,
                    "provider_symbol": canonical_symbol,
                    "canonical_symbol": canonical_symbol,
                    "timeframe": timeframe,
                    **_frame_progress_details(
                        requested_start_utc=requested_start_utc,
                        requested_end_utc=requested_end_utc,
                        frame=frame,
                        elapsed_sec=elapsed_sec,
                    ),
                },
            )
        )


def _build_roll_contract_windows(
    *,
    store: FilesystemHistoricalDataStore,
    provider_id: str,
    canonical_symbol: str,
    timeframe: str,
    merged_raw_frames: dict[str, pd.DataFrame],
) -> tuple[RollContractWindow, ...]:
    ordered_frames = sorted(
        merged_raw_frames.items(),
        key=lambda item: (
            ensure_utc(item[1].index.min().to_pydatetime()),
            item[0],
        ),
    )
    return tuple(
        RollContractWindow(
            contract_code=contract_code,
            raw_path=store.raw_contract_path(
                provider_id,
                canonical_symbol,
                timeframe,
                contract_code,
            ),
            start_utc=frame.index.min().to_pydatetime(),
            end_utc=frame.index.max().to_pydatetime(),
        )
        for contract_code, frame in ordered_frames
    )


def _load_existing_adjusted_frame(
    *,
    store: FilesystemHistoricalDataStore,
    provider_id: str,
    canonical_symbol: str,
    timeframe: str,
) -> pd.DataFrame:
    try:
        return store.load_source_frame(provider_id, canonical_symbol, timeframe)
    except FileNotFoundError:
        return pd.DataFrame()


def _pending_ib_windows(
    *,
    frame: pd.DataFrame,
    checkpoint: SourceDownloadCheckpoint | None,
    requested_start_utc: datetime,
    requested_end_utc: datetime,
    timeframe: str,
) -> tuple[tuple[datetime, datetime], ...]:
    step = _timeframe_delta(timeframe)
    if frame.empty:
        return ((requested_start_utc, requested_end_utc),)
    windows: list[tuple[datetime, datetime]] = []
    actual_start = frame.index.min().to_pydatetime()
    actual_end = frame.index.max().to_pydatetime()
    resume_start = checkpoint.last_timestamp_utc if checkpoint is not None else actual_start
    if actual_end < requested_end_utc:
        head_start = max(requested_start_utc, actual_end + step)
        if head_start <= requested_end_utc:
            windows.append((head_start, requested_end_utc))
    if resume_start > requested_start_utc:
        tail_end = min(requested_end_utc, resume_start - step)
        if requested_start_utc <= tail_end:
            windows.append((requested_start_utc, tail_end))
    return tuple(windows)


def _fetch_ib_window(
    *,
    client: IbHistoricalClient,
    resolver: IbContractResolver,
    store: FilesystemHistoricalDataStore,
    provider_id: str,
    source_system: DatasetSource,
    canonical_symbol: str,
    timeframe: str,
    resolved_timeframe: IbTimeframe,
    requested_start_utc: datetime,
    requested_end_utc: datetime,
    window_start_utc: datetime,
    window_end_utc: datetime,
    raw_frames: dict[str, pd.DataFrame],
    contracts: tuple[IbResolvedContract, ...],
    instrument_metadata: dict[str, str | int | float | bool | None],
    progress_callback: Callable[[pd.DataFrame], None] | None = None,
) -> dict[str, pd.DataFrame]:
    current_date = ensure_utc(window_end_utc)
    while current_date >= ensure_utc(window_start_utc):
        contract = resolver.select_contract(contracts, target_utc=current_date)
        if contract is None:
            current_date -= timedelta(days=7)
            continue
        chunk = client.fetch_chunk(
            contract,
            end_utc=current_date,
            timeframe=resolved_timeframe,
            duration=client.settings.chunk_duration,
        )
        if chunk.empty:
            current_date -= timedelta(days=7)
            continue
        raw_frames[contract.local_symbol] = _merge_frames(
            raw_frames.get(contract.local_symbol), chunk
        )
        adjusted, roll_manifest = _build_adjusted_series_from_raw_frames(
            store=store,
            provider_id=provider_id,
            canonical_symbol=canonical_symbol,
            timeframe=timeframe,
            merged_raw_frames=raw_frames,
        )
        if progress_callback is not None:
            progress_callback(adjusted)
        store.save_source_slice(
            manifest=SourceSliceManifest(
                provider_id=provider_id,
                source_system=source_system,
                canonical_symbol=canonical_symbol,
                provider_symbol=canonical_symbol,
                timeframe=timeframe,
                calendar_id="CME_INDEX_FUTURES",
                timezone_name="UTC",
                bars_path=store.bars_path(provider_id, canonical_symbol, timeframe),
                requested_start_utc=requested_start_utc,
                requested_end_utc=requested_end_utc,
                actual_start_utc=adjusted.index.min().to_pydatetime(),
                actual_end_utc=adjusted.index.max().to_pydatetime(),
                generated_at_utc=datetime.now(timezone.utc),
                row_count=int(len(adjusted)),
                source_fingerprint="0" * 64,
                provider_metadata={
                    "host": client.settings.host,
                    "port": client.settings.port,
                    "chunk_duration": client.settings.chunk_duration,
                },
                instrument_metadata=instrument_metadata,
                roll_policy="additive_back_adjusted",
            ),
            frame=adjusted,
            raw_contract_frames=raw_frames,
            roll_manifest=roll_manifest,
        )
        store.save_checkpoint(
            SourceDownloadCheckpoint(
                provider_id=provider_id,
                canonical_symbol=canonical_symbol,
                timeframe=timeframe,
                last_timestamp_utc=adjusted.index.min().to_pydatetime(),
                total_bars=len(adjusted),
                updated_at_utc=datetime.now(timezone.utc),
            )
        )
        if (
            adjusted.index.min().to_pydatetime() <= requested_start_utc
            and adjusted.index.max().to_pydatetime() >= requested_end_utc
        ):
            return raw_frames
        new_date = ensure_utc(chunk.index.min().to_pydatetime()) - _timeframe_delta(timeframe)
        if new_date >= current_date:
            break
        current_date = new_date
    return raw_frames


def _frame_progress_details(
    *,
    requested_start_utc: datetime,
    requested_end_utc: datetime,
    frame: pd.DataFrame,
    elapsed_sec: float,
) -> dict[str, str | int | float | bool | None]:
    actual_start = None if frame.empty else frame.index.min().to_pydatetime()
    actual_end = None if frame.empty else frame.index.max().to_pydatetime()
    progress_frac = compute_requested_coverage_progress(
        requested_start_utc=requested_start_utc,
        requested_end_utc=requested_end_utc,
        actual_start_utc=actual_start,
        actual_end_utc=actual_end,
    )
    eta_sec = estimate_eta_sec(elapsed_sec=elapsed_sec, progress_frac=progress_frac)
    return {
        "requested_start_utc": requested_start_utc.isoformat(),
        "requested_end_utc": requested_end_utc.isoformat(),
        "actual_start_utc": None if actual_start is None else actual_start.isoformat(),
        "actual_end_utc": None if actual_end is None else actual_end.isoformat(),
        "row_count": int(len(frame)),
        "progress_frac": round(progress_frac, 6),
        "progress_pct": round(progress_frac * 100.0, 1),
        "elapsed_sec": round(elapsed_sec, 2),
        "eta_sec": None if eta_sec is None else round(eta_sec, 2),
    }


def _build_adjusted_series_from_raw_frames(
    *,
    store: FilesystemHistoricalDataStore,
    provider_id: str,
    canonical_symbol: str,
    timeframe: str,
    merged_raw_frames: dict[str, pd.DataFrame],
) -> tuple[pd.DataFrame, RollManifest]:
    contract_windows = _build_roll_contract_windows(
        store=store,
        provider_id=provider_id,
        canonical_symbol=canonical_symbol,
        timeframe=timeframe,
        merged_raw_frames=merged_raw_frames,
    )
    roll_events: list[RollAdjustmentEvent] = []
    adjustments_by_contract: dict[str, float] = {}
    cumulative_adjustment = 0.0
    newer_frame: pd.DataFrame | None = None
    newer_contract: str | None = None
    for window in reversed(contract_windows):
        frame = merged_raw_frames[window.contract_code]
        adjustments_by_contract[window.contract_code] = cumulative_adjustment
        if newer_frame is not None and newer_contract is not None:
            additive_adjustment = float(newer_frame["open"].iloc[0]) - float(
                frame["close"].iloc[-1]
            )
            cumulative_adjustment += additive_adjustment
            adjustments_by_contract[window.contract_code] = cumulative_adjustment
            roll_events.append(
                RollAdjustmentEvent(
                    roll_time_utc=newer_frame.index.min().to_pydatetime(),
                    outgoing_contract=window.contract_code,
                    incoming_contract=newer_contract,
                    outgoing_close_raw=float(frame["close"].iloc[-1]),
                    incoming_open_raw=float(newer_frame["open"].iloc[0]),
                    additive_adjustment=additive_adjustment,
                    cumulative_adjustment=cumulative_adjustment,
                )
            )
        newer_frame = frame
        newer_contract = window.contract_code
    adjusted_frames: list[pd.DataFrame] = []
    for window in contract_windows:
        frame = merged_raw_frames[window.contract_code].copy()
        adjustment = adjustments_by_contract.get(window.contract_code, 0.0)
        if adjustment:
            for column in ("open", "high", "low", "close", "average"):
                if column in frame.columns:
                    frame[column] = frame[column].astype(float) + adjustment
        frame["contract"] = window.contract_code
        adjusted_frames.append(frame)
    adjusted = pd.concat(adjusted_frames).sort_index()
    adjusted = adjusted[~adjusted.index.duplicated(keep="last")]
    roll_manifest = RollManifest(
        provider_id=provider_id,
        canonical_symbol=canonical_symbol,
        timeframe=timeframe,
        roll_policy="additive_back_adjusted",
        contract_windows=contract_windows,
        events=tuple(reversed(roll_events)),
        generated_at_utc=datetime.now(timezone.utc),
    )
    return adjusted, roll_manifest


def _merge_frames(existing: pd.DataFrame | None, incoming: pd.DataFrame) -> pd.DataFrame:
    if existing is None or existing.empty:
        return incoming.sort_index()
    merged = pd.concat([existing, incoming]).sort_index()
    return merged[~merged.index.duplicated(keep="last")]


def _timeframe_delta(timeframe: str) -> timedelta:
    timeframe_minutes = {
        "1m": 1,
        "5m": 5,
        "15m": 15,
        "30m": 30,
        "1h": 60,
        "4h": 240,
        "1d": 1_440,
    }
    return timedelta(minutes=timeframe_minutes[timeframe])


def _resolve_download_window(
    *,
    start_utc: datetime | None,
    end_utc: datetime | None,
    settings: IbDataSettings,
) -> tuple[datetime, datetime, bool]:
    if start_utc is not None and end_utc is not None:
        return ensure_utc(start_utc), ensure_utc(end_utc), True
    effective_end = datetime.now(timezone.utc)
    effective_start = effective_end - timedelta(days=366 * settings.max_historical_years)
    return effective_start, effective_end, False


__all__ = ["IbHistoricalDataProvider"]
