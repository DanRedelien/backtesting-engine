"""MT5 provider adapter for the unified market-data workflow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter
from typing import Callable, Protocol

import pandas as pd

from backtest_engine.config.data import Mt5DataSettings
from backtest_engine.core.enums import DatasetSource
from backtest_engine.core.time import ensure_utc
from backtest_engine.core.errors import InfrastructureError
from backtest_engine.infrastructure.data.errors import (
    InsufficientHistoryError,
    SymbolMappingError,
    UnsupportedTimeframeError,
)
from backtest_engine.infrastructure.data.market_data_contracts import (
    DownloadedSourceSlice,
    DryRunMetadata,
    SourceDownloadCheckpoint,
    SourceSliceManifest,
)
from backtest_engine.infrastructure.data.progress import (
    compute_requested_coverage_progress,
    describe_coverage_gap,
    estimate_eta_sec,
    is_coverage_sufficient,
)
from backtest_engine.infrastructure.data.market_data_store import FilesystemHistoricalDataStore
from backtest_engine.infrastructure.data.mt5.client import Mt5HistoricalClient
from backtest_engine.infrastructure.data.mt5.timeframes import supported_mt5_timeframes
from backtest_engine.infrastructure.nautilus.symbol_map import SymbolMapping, load_symbol_map
from backtest_engine.infrastructure.observability import (
    DiagnosticsSink,
    NullDiagnosticsSink,
    StageDiagnosticEvent,
)


class Mt5HistoricalClientPort(Protocol):
    """Minimal MT5 client contract required by the provider."""

    settings: Mt5DataSettings

    def connect(self) -> None:
        """Open the MT5 session."""
        ...

    def disconnect(self) -> None:
        """Close the MT5 session."""
        ...

    def fetch_with_poll(
        self,
        *,
        provider_symbol: str,
        timeframe: str,
        start_utc: datetime,
        end_utc: datetime,
    ) -> pd.DataFrame:
        """Fetch one source window from MT5."""
        ...

    def session_metadata(self) -> dict[str, str | int | float | bool | None]:
        """Return provider session metadata."""
        ...


@dataclass
class Mt5HistoricalDataProvider:
    """Download MT5 bars into the provider-managed source cache layout."""

    settings: Mt5DataSettings
    store: FilesystemHistoricalDataStore
    client: Mt5HistoricalClientPort | None = None
    symbol_map_path: Path | None = None
    diagnostics: DiagnosticsSink = NullDiagnosticsSink()

    @property
    def provider_id(self) -> str:
        return "mt5"

    @property
    def source_system(self) -> DatasetSource:
        return DatasetSource.MT5

    def supported_timeframes(self) -> tuple[str, ...]:
        return supported_mt5_timeframes()

    def canonical_symbol_for(self, requested_symbol: str) -> str:
        return self._resolve_mapping(requested_symbol).mt5_symbol

    def _require_broker_timezone(self) -> str:
        """Return the configured broker timezone or raise a typed error."""
        if self.settings.broker_timezone_name is None:
            raise InfrastructureError(
                "MT5 broker timezone is required but not configured; "
                "set BTE_DATA__MT5__BROKER_TIMEZONE_NAME explicitly",
            )
        return self.settings.broker_timezone_name

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
        if timeframe not in self.supported_timeframes():
            raise UnsupportedTimeframeError(
                "unsupported MT5 timeframe",
                timeframe=timeframe,
                supported_timeframes=",".join(self.supported_timeframes()),
            )
        mapping = self._resolve_mapping(requested_symbol)
        canonical_symbol = mapping.mt5_symbol
        provider_symbol = mapping.resolved_provider_symbol
        requested_start, requested_end, explicit_window = _resolve_download_window(
            start_utc=start_utc,
            end_utc=end_utc,
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
                    provider_symbol=provider_symbol,
                    supported_timeframes=self.supported_timeframes(),
                    window_mode="explicit" if explicit_window else "max_available",
                    requested_start_utc=requested_start,
                    requested_end_utc=requested_end,
                    calendar_id=_calendar_id_for(mapping),
                ),
            )

        broker_tz = self._require_broker_timezone()

        if force:
            self.store.clear_source_slice(self.provider_id, canonical_symbol, timeframe)

        started_at = perf_counter()
        client = self.client or Mt5HistoricalClient(settings=self.settings)
        client.connect()
        try:
            frame = _load_existing_source_frame(
                store=self.store,
                provider_id=self.provider_id,
                canonical_symbol=canonical_symbol,
                timeframe=timeframe,
            )
            self._emit_progress(
                requested_by=requested_by,
                provider_symbol=provider_symbol,
                canonical_symbol=canonical_symbol,
                timeframe=timeframe,
                requested_start_utc=requested_start,
                requested_end_utc=requested_end,
                frame=frame,
                elapsed_sec=perf_counter() - started_at,
            )
            checkpoint = self.store.load_checkpoint(self.provider_id, canonical_symbol, timeframe)
            frame = _resume_mt5_history(
                client=client,
                store=self.store,
                provider_id=self.provider_id,
                source_system=self.source_system,
                canonical_symbol=canonical_symbol,
                provider_symbol=provider_symbol,
                timeframe=timeframe,
                requested_start_utc=requested_start,
                requested_end_utc=requested_end,
                timezone_name=broker_tz,
                calendar_id=_calendar_id_for(mapping),
                provider_metadata=client.session_metadata(),
                instrument_metadata=mapping.metadata_dict(),
                existing_frame=frame,
                checkpoint=checkpoint,
                progress_callback=lambda current_frame: self._emit_progress(
                    requested_by=requested_by,
                    provider_symbol=provider_symbol,
                    canonical_symbol=canonical_symbol,
                    timeframe=timeframe,
                    requested_start_utc=requested_start,
                    requested_end_utc=requested_end,
                    frame=current_frame,
                    elapsed_sec=perf_counter() - started_at,
                ),
            )
            if frame.empty:
                raise InsufficientHistoryError(
                    "MT5 returned no historical bars for the requested window",
                    provider_symbol=provider_symbol,
                    canonical_symbol=canonical_symbol,
                    timeframe=timeframe,
                    requested_start=requested_start.isoformat(),
                    requested_end=requested_end.isoformat(),
                )
            actual_start = frame.index.min().to_pydatetime()
            actual_end = frame.index.max().to_pydatetime()
            coverage_start = requested_start if explicit_window else actual_start
            if not is_coverage_sufficient(
                actual_start_utc=actual_start,
                actual_end_utc=actual_end,
                requested_start_utc=coverage_start,
                requested_end_utc=requested_end,
                timeframe=timeframe,
                calendar_id=_calendar_id_for(mapping),
                timezone_name=broker_tz,
            ):
                gap_desc = describe_coverage_gap(
                    actual_start_utc=actual_start,
                    actual_end_utc=actual_end,
                    requested_start_utc=coverage_start,
                    requested_end_utc=requested_end,
                    timeframe=timeframe,
                    calendar_id=_calendar_id_for(mapping),
                    timezone_name=broker_tz,
                )
                message = (
                    f"MT5 data covers {actual_start.date()}..{actual_end.date()} "
                    f"but {coverage_start.date()}..{requested_end.date()} was requested; {gap_desc}. "
                    f"MT5 may not have enough historical {timeframe} data; consider adjusting --start."
                    if explicit_window
                    else (
                        "MT5 max-available download could not reach the recent end boundary; "
                        f"{gap_desc}."
                    )
                )
                raise InsufficientHistoryError(
                    message,
                    provider_symbol=provider_symbol,
                    canonical_symbol=canonical_symbol,
                    timeframe=timeframe,
                    requested_start=coverage_start.isoformat(),
                    requested_end=requested_end.isoformat(),
                    actual_start=actual_start.isoformat(),
                    actual_end=actual_end.isoformat(),
                    row_count=len(frame),
                )
            manifest = _persist_mt5_source_slice(
                store=self.store,
                provider_id=self.provider_id,
                source_system=self.source_system,
                canonical_symbol=canonical_symbol,
                provider_symbol=provider_symbol,
                timeframe=timeframe,
                calendar_id=_calendar_id_for(mapping),
                timezone_name=broker_tz,
                requested_start_utc=coverage_start,
                requested_end_utc=requested_end,
                frame=frame,
                provider_metadata=client.session_metadata(),
                instrument_metadata=mapping.metadata_dict(),
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
                "unknown MT5 symbol mapping",
                requested_symbol=requested_symbol,
            ) from exc

    def _emit_progress(
        self,
        *,
        requested_by: str,
        provider_symbol: str,
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
                    "provider_symbol": provider_symbol,
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


def _calendar_id_for(mapping: SymbolMapping) -> str:
    if mapping.asset_class == "CRYPTOCURRENCY":
        return "CRYPTO_24_7"
    if mapping.asset_class == "FX":
        return "FX_24_5"
    return "CFD_BROKER_SESSION"


def _resolve_download_window(
    *,
    start_utc: datetime | None,
    end_utc: datetime | None,
) -> tuple[datetime, datetime, bool]:
    if start_utc is not None and end_utc is not None:
        return ensure_utc(start_utc), ensure_utc(end_utc), True
    return datetime(1970, 1, 1, tzinfo=timezone.utc), datetime.now(timezone.utc), False


def _resume_mt5_history(
    *,
    client: Mt5HistoricalClientPort,
    store: FilesystemHistoricalDataStore,
    provider_id: str,
    source_system: DatasetSource,
    canonical_symbol: str,
    provider_symbol: str,
    timeframe: str,
    requested_start_utc: datetime,
    requested_end_utc: datetime,
    timezone_name: str,
    calendar_id: str,
    provider_metadata: dict[str, str | int | float | bool | None],
    instrument_metadata: dict[str, str | int | float | bool | None],
    existing_frame: pd.DataFrame,
    checkpoint: SourceDownloadCheckpoint | None,
    progress_callback: Callable[[pd.DataFrame], None] | None = None,
) -> pd.DataFrame:
    frame = _normalize_saved_frame(existing_frame)
    timeframe_step = _timeframe_delta(timeframe)
    pending_windows = _pending_windows(
        frame=frame,
        checkpoint=checkpoint,
        requested_start_utc=requested_start_utc,
        requested_end_utc=requested_end_utc,
        timeframe_step=timeframe_step,
    )
    if not pending_windows:
        return frame
    for window_start, window_end in pending_windows:
        current_end = window_end
        while current_end >= window_start:
            chunk_start = max(
                window_start,
                current_end - timedelta(days=client.settings.chunk_days) + timeframe_step,
            )
            chunk = client.fetch_with_poll(
                provider_symbol=provider_symbol,
                timeframe=timeframe,
                start_utc=chunk_start,
                end_utc=current_end,
            )
            if chunk.empty:
                break
            prev_len = len(frame)
            frame = _merge_frames(frame, chunk)
            if progress_callback is not None:
                progress_callback(frame)
            _persist_mt5_source_slice(
                store=store,
                provider_id=provider_id,
                source_system=source_system,
                canonical_symbol=canonical_symbol,
                provider_symbol=provider_symbol,
                timeframe=timeframe,
                calendar_id=calendar_id,
                timezone_name=timezone_name,
                requested_start_utc=requested_start_utc,
                requested_end_utc=requested_end_utc,
                frame=frame,
                provider_metadata=provider_metadata,
                instrument_metadata=instrument_metadata,
            )
            store.save_checkpoint(
                SourceDownloadCheckpoint(
                    provider_id=provider_id,
                    canonical_symbol=canonical_symbol,
                    timeframe=timeframe,
                    last_timestamp_utc=frame.index.min().to_pydatetime(),
                    total_bars=len(frame),
                    updated_at_utc=datetime.now(timezone.utc),
                )
            )
            if (
                frame.index.min().to_pydatetime() <= requested_start_utc
                and frame.index.max().to_pydatetime() >= requested_end_utc
            ):
                return frame
            new_end = chunk.index.min().to_pydatetime() - timeframe_step
            if new_end >= current_end or len(frame) == prev_len:
                break
            current_end = new_end
    return frame


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


def _persist_mt5_source_slice(
    *,
    store: FilesystemHistoricalDataStore,
    provider_id: str,
    source_system: DatasetSource,
    canonical_symbol: str,
    provider_symbol: str,
    timeframe: str,
    calendar_id: str,
    timezone_name: str,
    requested_start_utc: datetime,
    requested_end_utc: datetime,
    frame: pd.DataFrame,
    provider_metadata: dict[str, str | int | float | bool | None],
    instrument_metadata: dict[str, str | int | float | bool | None],
) -> SourceSliceManifest:
    normalized = _normalize_saved_frame(frame)
    return store.save_source_slice(
        manifest=SourceSliceManifest(
            provider_id=provider_id,
            source_system=source_system,
            canonical_symbol=canonical_symbol,
            provider_symbol=provider_symbol,
            timeframe=timeframe,
            calendar_id=calendar_id,
            timezone_name=timezone_name,
            bars_path=store.bars_path(provider_id, canonical_symbol, timeframe),
            requested_start_utc=requested_start_utc,
            requested_end_utc=requested_end_utc,
            actual_start_utc=normalized.index.min().to_pydatetime(),
            actual_end_utc=normalized.index.max().to_pydatetime(),
            generated_at_utc=datetime.now(timezone.utc),
            row_count=int(len(normalized)),
            source_fingerprint="0" * 64,
            provider_metadata=provider_metadata,
            instrument_metadata=instrument_metadata,
        ),
        frame=normalized,
    )


def _load_existing_source_frame(
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


def _pending_windows(
    *,
    frame: pd.DataFrame,
    checkpoint: SourceDownloadCheckpoint | None,
    requested_start_utc: datetime,
    requested_end_utc: datetime,
    timeframe_step: timedelta,
) -> tuple[tuple[datetime, datetime], ...]:
    if frame.empty:
        return ((requested_start_utc, requested_end_utc),)
    windows: list[tuple[datetime, datetime]] = []
    actual_start = frame.index.min().to_pydatetime()
    actual_end = frame.index.max().to_pydatetime()
    resume_start = checkpoint.last_timestamp_utc if checkpoint is not None else actual_start
    if actual_end < requested_end_utc:
        head_start = max(requested_start_utc, actual_end + timeframe_step)
        if head_start <= requested_end_utc:
            windows.append((head_start, requested_end_utc))
    if resume_start > requested_start_utc:
        tail_end = min(requested_end_utc, resume_start - timeframe_step)
        if requested_start_utc <= tail_end:
            windows.append((requested_start_utc, tail_end))
    return tuple(windows)


def _merge_frames(existing: pd.DataFrame, incoming: pd.DataFrame) -> pd.DataFrame:
    if existing.empty:
        return _normalize_saved_frame(incoming)
    combined = pd.concat([existing, incoming]).sort_index()
    return combined[~combined.index.duplicated(keep="last")]


def _normalize_saved_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    normalized = frame.copy()
    normalized.index = pd.DatetimeIndex(pd.to_datetime(normalized.index, utc=True))
    return normalized.sort_index()


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


__all__ = ["Mt5HistoricalDataProvider"]
