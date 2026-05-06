"""Filesystem storage for IB source parquet caches and checkpoints."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from backtest_engine.core.errors import InfrastructureError
from backtest_engine.core.types import Symbol, Timeframe
from backtest_engine.infrastructure.data.ib.contracts import (
    IbCacheArtifact,
    IbCacheManifest,
    IbDownloadCheckpoint,
)


@dataclass(frozen=True)
class FilesystemIbCacheStore:
    """Persist and reload IB source caches without leaking legacy helpers."""

    source_cache_root: Path

    def load_cache(self, symbol: Symbol, timeframe: Timeframe) -> pd.DataFrame:
        """Return one cached source DataFrame or an empty frame when absent."""

        cache_path = self.cache_path(symbol, timeframe)
        if not cache_path.is_file():
            return pd.DataFrame()

        try:
            frame = pd.read_parquet(cache_path)
        except Exception as exc:
            raise InfrastructureError(
                "failed to read IB source cache",
                symbol=symbol,
                timeframe=timeframe,
                cache_path=str(cache_path),
            ) from exc

        if frame.empty:
            return frame
        return _normalize_cache_frame(frame)

    def save_cache(
        self,
        *,
        symbol: Symbol,
        timeframe: Timeframe,
        frame: pd.DataFrame,
        generated_at_utc: datetime,
    ) -> IbCacheArtifact:
        """Write one source cache plus a manifest describing the saved artifact."""

        normalized = _normalize_cache_frame(frame)
        cache_path = self.cache_path(symbol, timeframe)
        manifest_path = self.manifest_path(symbol, timeframe)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        normalized.to_parquet(cache_path)

        contract_codes = _extract_contract_codes(normalized)
        start_time = normalized.index.min().to_pydatetime() if not normalized.empty else None
        end_time = normalized.index.max().to_pydatetime() if not normalized.empty else None
        manifest = IbCacheManifest(
            symbol=symbol,
            timeframe=timeframe,
            cache_path=cache_path,
            row_count=int(len(normalized)),
            start_time_utc=start_time,
            end_time_utc=end_time,
            contract_codes=contract_codes,
            generated_at_utc=generated_at_utc,
        )
        manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        return IbCacheArtifact(
            symbol=symbol,
            timeframe=timeframe,
            cache_path=cache_path,
            manifest_path=manifest_path,
            manifest=manifest,
        )

    def load_checkpoint(
        self,
        symbol: Symbol,
        timeframe: Timeframe,
    ) -> IbDownloadCheckpoint | None:
        """Load one resumable checkpoint if it exists and is still parseable."""

        checkpoint_path = self.checkpoint_path(symbol, timeframe)
        if not checkpoint_path.is_file():
            return None

        try:
            return IbDownloadCheckpoint.model_validate_json(
                checkpoint_path.read_text(encoding="utf-8")
            )
        except Exception:
            return None

    def save_checkpoint(
        self,
        *,
        symbol: Symbol,
        timeframe: Timeframe,
        last_date_utc: datetime,
        total_bars: int,
        updated_at_utc: datetime,
    ) -> None:
        """Persist resumable download state for one symbol/timeframe pair."""

        checkpoint = IbDownloadCheckpoint(
            symbol=symbol,
            timeframe=timeframe,
            last_date_utc=last_date_utc,
            total_bars=total_bars,
            updated_at_utc=updated_at_utc,
        )
        checkpoint_path = self.checkpoint_path(symbol, timeframe)
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        checkpoint_path.write_text(checkpoint.model_dump_json(indent=2), encoding="utf-8")

    def clear_checkpoint(self, symbol: Symbol, timeframe: Timeframe) -> None:
        """Delete one checkpoint once the full backfill completes."""

        checkpoint_path = self.checkpoint_path(symbol, timeframe)
        if checkpoint_path.is_file():
            checkpoint_path.unlink()

    def cache_path(self, symbol: Symbol, timeframe: Timeframe) -> Path:
        return self.source_cache_root / f"{symbol}_{timeframe}.parquet"

    def manifest_path(self, symbol: Symbol, timeframe: Timeframe) -> Path:
        return self.source_cache_root / f"{symbol}_{timeframe}.manifest.json"

    def checkpoint_path(self, symbol: Symbol, timeframe: Timeframe) -> Path:
        return self.source_cache_root / f"{symbol}_{timeframe}_checkpoint.json"


def _normalize_cache_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame

    working = frame.copy()
    if not isinstance(working.index, pd.DatetimeIndex):
        if "date" in working.columns:
            working = working.set_index("date")
        working.index = pd.to_datetime(working.index, utc=True)
    elif working.index.tz is None:
        working.index = working.index.tz_localize("UTC")
    else:
        working.index = working.index.tz_convert("UTC")

    working = working[~working.index.duplicated(keep="last")].sort_index()
    return working


def _extract_contract_codes(frame: pd.DataFrame) -> tuple[str, ...]:
    if "contract" not in frame.columns:
        return ()

    contract_codes: list[str] = []
    for value in frame["contract"].dropna().astype(str):
        normalized = value.strip()
        if normalized and normalized not in contract_codes:
            contract_codes.append(normalized)
    return tuple(contract_codes)


__all__ = ["FilesystemIbCacheStore"]
