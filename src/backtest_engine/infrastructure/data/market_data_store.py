"""Filesystem storage for provider-managed historical market-data slices."""

from __future__ import annotations

import hashlib
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from backtest_engine.core.enums import DatasetSource
from backtest_engine.core.time import ensure_utc
from backtest_engine.core.types import Symbol, Timeframe
from backtest_engine.domain.market.datasets import DatasetSpec
from backtest_engine.infrastructure.data.cache_store import CachedBarSource
from backtest_engine.infrastructure.data.coverage_policy import assess_requested_coverage
from backtest_engine.infrastructure.data.errors import (
    MaterializationBlockedError,
    ValidationManifestPersistenceError,
)
from backtest_engine.infrastructure.data.market_data_contracts import (
    RollManifest,
    SourceDownloadCheckpoint,
    SourceSliceManifest,
    ValidationManifest,
)


@dataclass(frozen=True)
class FilesystemHistoricalDataStore:
    """Persist provider-managed source slices, manifests, and audit files."""

    source_cache_root: Path

    @property
    def canonical_source_cache_root(self) -> Path:
        return self.source_cache_root.resolve(strict=False)

    def slice_root(self, provider_id: str, canonical_symbol: Symbol, timeframe: Timeframe) -> Path:
        return self.canonical_source_cache_root / provider_id / canonical_symbol / timeframe

    def bars_path(self, provider_id: str, canonical_symbol: Symbol, timeframe: Timeframe) -> Path:
        return self.slice_root(provider_id, canonical_symbol, timeframe) / "bars.parquet"

    def canonical_bars_path(
        self, provider_id: str, canonical_symbol: Symbol, timeframe: Timeframe
    ) -> Path:
        return self.bars_path(provider_id, canonical_symbol, timeframe)

    def source_manifest_path(
        self, provider_id: str, canonical_symbol: Symbol, timeframe: Timeframe
    ) -> Path:
        return self.slice_root(provider_id, canonical_symbol, timeframe) / "source_manifest.json"

    def validation_manifest_path(
        self,
        provider_id: str,
        canonical_symbol: Symbol,
        timeframe: Timeframe,
    ) -> Path:
        return (
            self.slice_root(provider_id, canonical_symbol, timeframe) / "validation_manifest.json"
        )

    def checkpoint_path(
        self, provider_id: str, canonical_symbol: Symbol, timeframe: Timeframe
    ) -> Path:
        return self.slice_root(provider_id, canonical_symbol, timeframe) / "checkpoint.json"

    def roll_manifest_path(
        self, provider_id: str, canonical_symbol: Symbol, timeframe: Timeframe
    ) -> Path:
        return self.slice_root(provider_id, canonical_symbol, timeframe) / "roll_manifest.json"

    def raw_contract_root(
        self, provider_id: str, canonical_symbol: Symbol, timeframe: Timeframe
    ) -> Path:
        return self.slice_root(provider_id, canonical_symbol, timeframe) / "raw_contracts"

    def raw_contract_path(
        self,
        provider_id: str,
        canonical_symbol: Symbol,
        timeframe: Timeframe,
        contract_code: str,
    ) -> Path:
        return (
            self.raw_contract_root(provider_id, canonical_symbol, timeframe)
            / f"{contract_code}.parquet"
        )

    def normalize_storage_path(self, path: Path) -> str:
        return os.path.normcase(os.path.normpath(str(path.resolve(strict=False))))

    def relative_storage_suffix(self, path: Path) -> tuple[str, ...]:
        normalized = Path(os.path.normpath(str(path)))
        return tuple(os.path.normcase(part) for part in normalized.parts)

    def source_path_matches_canonical(
        self,
        *,
        provider_id: str,
        canonical_symbol: Symbol,
        timeframe: Timeframe,
        bars_path: Path,
    ) -> bool:
        canonical_path = self.canonical_bars_path(provider_id, canonical_symbol, timeframe)
        if bars_path.is_absolute():
            return self.normalize_storage_path(bars_path) == self.normalize_storage_path(
                canonical_path
            )
        relative_suffix = self.relative_storage_suffix(bars_path)
        canonical_suffix = self.relative_storage_suffix(canonical_path)
        return (
            len(relative_suffix) <= len(canonical_suffix)
            and canonical_suffix[-len(relative_suffix) :] == relative_suffix
        )

    def save_source_slice(
        self,
        *,
        manifest: SourceSliceManifest,
        frame: pd.DataFrame,
        raw_contract_frames: dict[str, pd.DataFrame] | None = None,
        roll_manifest: RollManifest | None = None,
    ) -> SourceSliceManifest:
        normalized = _normalize_frame(frame)
        canonical_bars_path = self.canonical_bars_path(
            manifest.provider_id,
            manifest.canonical_symbol,
            manifest.timeframe,
        )
        actual_start_utc = manifest.actual_start_utc
        actual_end_utc = manifest.actual_end_utc
        row_count = 0
        if not normalized.empty:
            actual_start_utc = normalized.index.min().to_pydatetime()
            actual_end_utc = normalized.index.max().to_pydatetime()
            row_count = int(len(normalized))
        bars_path = canonical_bars_path
        bars_path.parent.mkdir(parents=True, exist_ok=True)
        normalized.to_parquet(bars_path)
        source_fingerprint = self.compute_bars_hash(bars_path)
        resolved_manifest = manifest.model_copy(
            update={
                "bars_path": canonical_bars_path,
                "actual_start_utc": actual_start_utc,
                "actual_end_utc": actual_end_utc,
                "row_count": row_count,
                "source_fingerprint": source_fingerprint,
            }
        )
        self.source_manifest_path(
            manifest.provider_id,
            manifest.canonical_symbol,
            manifest.timeframe,
        ).write_text(resolved_manifest.model_dump_json(indent=2), encoding="utf-8")

        if raw_contract_frames:
            raw_root = self.raw_contract_root(
                manifest.provider_id,
                manifest.canonical_symbol,
                manifest.timeframe,
            )
            raw_root.mkdir(parents=True, exist_ok=True)
            for contract_code, contract_frame in raw_contract_frames.items():
                _normalize_frame(contract_frame).to_parquet(
                    self.raw_contract_path(
                        manifest.provider_id,
                        manifest.canonical_symbol,
                        manifest.timeframe,
                        contract_code,
                    )
                )

        if roll_manifest is not None:
            self.roll_manifest_path(
                manifest.provider_id,
                manifest.canonical_symbol,
                manifest.timeframe,
            ).write_text(roll_manifest.model_dump_json(indent=2), encoding="utf-8")

        self.clear_validation(manifest.provider_id, manifest.canonical_symbol, manifest.timeframe)
        return resolved_manifest

    def load_source_manifest(
        self,
        provider_id: str,
        canonical_symbol: Symbol,
        timeframe: Timeframe,
    ) -> SourceSliceManifest:
        return SourceSliceManifest.model_validate_json(
            self.source_manifest_path(provider_id, canonical_symbol, timeframe).read_text(
                encoding="utf-8",
            )
        )

    def load_validation_manifest(
        self,
        provider_id: str,
        canonical_symbol: Symbol,
        timeframe: Timeframe,
    ) -> ValidationManifest | None:
        path = self.validation_manifest_path(provider_id, canonical_symbol, timeframe)
        if not path.is_file():
            return None
        return ValidationManifest.model_validate_json(path.read_text(encoding="utf-8"))

    def save_validation_manifest(self, manifest: ValidationManifest) -> None:
        path = self.validation_manifest_path(
            manifest.provider_id,
            manifest.canonical_symbol,
            manifest.timeframe,
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        except OSError as exc:
            raise ValidationManifestPersistenceError(
                "failed to persist validation manifest",
                provider_id=manifest.provider_id,
                symbol=manifest.canonical_symbol,
                timeframe=manifest.timeframe,
                path=str(path),
            ) from exc

    def clear_validation(
        self, provider_id: str, canonical_symbol: Symbol, timeframe: Timeframe
    ) -> None:
        path = self.validation_manifest_path(provider_id, canonical_symbol, timeframe)
        if path.is_file():
            path.unlink()

    def clear_source_slice(
        self, provider_id: str, canonical_symbol: Symbol, timeframe: Timeframe
    ) -> None:
        root = self.slice_root(provider_id, canonical_symbol, timeframe)
        if root.is_dir():
            shutil.rmtree(root)

    def load_roll_manifest(
        self,
        provider_id: str,
        canonical_symbol: Symbol,
        timeframe: Timeframe,
    ) -> RollManifest | None:
        path = self.roll_manifest_path(provider_id, canonical_symbol, timeframe)
        if not path.is_file():
            return None
        return RollManifest.model_validate_json(path.read_text(encoding="utf-8"))

    def load_source_frame(
        self,
        provider_id: str,
        canonical_symbol: Symbol,
        timeframe: Timeframe,
    ) -> pd.DataFrame:
        frame = pd.read_parquet(self.bars_path(provider_id, canonical_symbol, timeframe))
        return _normalize_frame(frame)

    def load_raw_contract_frame(
        self,
        provider_id: str,
        canonical_symbol: Symbol,
        timeframe: Timeframe,
        contract_code: str,
    ) -> pd.DataFrame:
        return _normalize_frame(
            pd.read_parquet(
                self.raw_contract_path(provider_id, canonical_symbol, timeframe, contract_code),
            )
        )

    def load_saved_raw_contract_frames(
        self,
        provider_id: str,
        canonical_symbol: Symbol,
        timeframe: Timeframe,
    ) -> dict[str, pd.DataFrame]:
        raw_root = self.raw_contract_root(provider_id, canonical_symbol, timeframe)
        if not raw_root.is_dir():
            return {}
        frames: dict[str, pd.DataFrame] = {}
        for path in raw_root.glob("*.parquet"):
            frames[path.stem] = _normalize_frame(pd.read_parquet(path))
        return frames

    def save_checkpoint(self, checkpoint: SourceDownloadCheckpoint) -> None:
        path = self.checkpoint_path(
            checkpoint.provider_id,
            checkpoint.canonical_symbol,
            checkpoint.timeframe,
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(checkpoint.model_dump_json(indent=2), encoding="utf-8")

    def load_checkpoint(
        self,
        provider_id: str,
        canonical_symbol: Symbol,
        timeframe: Timeframe,
    ) -> SourceDownloadCheckpoint | None:
        path = self.checkpoint_path(provider_id, canonical_symbol, timeframe)
        if not path.is_file():
            return None
        return SourceDownloadCheckpoint.model_validate_json(path.read_text(encoding="utf-8"))

    def clear_checkpoint(
        self, provider_id: str, canonical_symbol: Symbol, timeframe: Timeframe
    ) -> None:
        path = self.checkpoint_path(provider_id, canonical_symbol, timeframe)
        if path.is_file():
            path.unlink()

    def compute_bars_hash(self, bars_path: Path) -> str:
        digest = hashlib.sha256()
        with bars_path.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()

    def has_complete_verified_slice(
        self,
        *,
        provider_id: str,
        canonical_symbol: Symbol,
        timeframe: Timeframe,
        requested_start_utc: datetime,
        requested_end_utc: datetime,
        validator_ruleset_version: str,
    ) -> bool:
        try:
            source_manifest = self.load_source_manifest(provider_id, canonical_symbol, timeframe)
        except FileNotFoundError:
            return False
        validation_manifest = self.load_validation_manifest(
            provider_id, canonical_symbol, timeframe
        )
        if validation_manifest is None:
            return False
        if validation_manifest.verification_verdict != "PASS":
            return False
        if validation_manifest.validator_ruleset_version != validator_ruleset_version:
            return False
        if not self.source_path_matches_canonical(
            provider_id=provider_id,
            canonical_symbol=canonical_symbol,
            timeframe=timeframe,
            bars_path=source_manifest.bars_path,
        ):
            return False
        canonical_bars_path = self.canonical_bars_path(provider_id, canonical_symbol, timeframe)
        try:
            current_fingerprint = self.compute_bars_hash(canonical_bars_path)
        except OSError:
            return False
        if source_manifest.source_fingerprint != current_fingerprint:
            return False
        if validation_manifest.source_fingerprint != current_fingerprint:
            return False
        return assess_requested_coverage(
            actual_start_utc=source_manifest.actual_start_utc,
            actual_end_utc=source_manifest.actual_end_utc,
            requested_start_utc=ensure_utc(requested_start_utc),
            requested_end_utc=ensure_utc(requested_end_utc),
            timeframe=timeframe,
            calendar_id=source_manifest.calendar_id,
            timezone_name=source_manifest.timezone_name,
        ).accepted

    def resolve_verified_sources(
        self,
        dataset: DatasetSpec,
        *,
        validator_ruleset_version: str,
    ) -> tuple[CachedBarSource, ...]:
        if dataset.source_system not in {DatasetSource.IB, DatasetSource.MT5}:
            raise ValueError("resolve_verified_sources is only valid for managed provider datasets")
        provider_id = dataset.source_system.value
        sources: list[CachedBarSource] = []
        for symbol in dataset.symbol_universe:
            try:
                source_manifest = self.load_source_manifest(provider_id, symbol, dataset.timeframe)
            except FileNotFoundError as exc:
                raise MaterializationBlockedError(
                    "materialization requires a source manifest",
                    provider_id=provider_id,
                    symbol=symbol,
                    timeframe=dataset.timeframe,
                ) from exc
            validation_manifest = self.load_validation_manifest(
                provider_id, symbol, dataset.timeframe
            )
            if validation_manifest is None:
                raise MaterializationBlockedError(
                    "materialization requires a verification manifest",
                    provider_id=provider_id,
                    symbol=symbol,
                    timeframe=dataset.timeframe,
                )
            canonical_bars_path = self.canonical_bars_path(provider_id, symbol, dataset.timeframe)
            if not self.source_path_matches_canonical(
                provider_id=provider_id,
                canonical_symbol=symbol,
                timeframe=dataset.timeframe,
                bars_path=source_manifest.bars_path,
            ):
                raise MaterializationBlockedError(
                    "source manifest path drift blocks materialization",
                    provider_id=provider_id,
                    symbol=symbol,
                    timeframe=dataset.timeframe,
                    manifest_path=str(source_manifest.bars_path),
                    canonical_path=str(canonical_bars_path),
                )
            try:
                current_fingerprint = self.compute_bars_hash(canonical_bars_path)
            except OSError as exc:
                raise MaterializationBlockedError(
                    "materialization requires an accessible source parquet",
                    provider_id=provider_id,
                    symbol=symbol,
                    timeframe=dataset.timeframe,
                    source_path=str(canonical_bars_path),
                ) from exc
            if validation_manifest.verification_verdict != "PASS":
                raise MaterializationBlockedError(
                    "materialization requires PASS verification",
                    provider_id=provider_id,
                    symbol=symbol,
                    timeframe=dataset.timeframe,
                    verification_verdict=validation_manifest.verification_verdict,
                )
            if validation_manifest.validator_ruleset_version != validator_ruleset_version:
                raise MaterializationBlockedError(
                    "validation ruleset version mismatch blocks materialization",
                    provider_id=provider_id,
                    symbol=symbol,
                    timeframe=dataset.timeframe,
                )
            if (
                validation_manifest.source_fingerprint != current_fingerprint
                or source_manifest.source_fingerprint != current_fingerprint
            ):
                raise MaterializationBlockedError(
                    "source fingerprint mismatch blocks materialization",
                    provider_id=provider_id,
                    symbol=symbol,
                    timeframe=dataset.timeframe,
                )
            sources.append(
                CachedBarSource(
                    symbol=symbol,
                    timeframe=dataset.timeframe,
                    source_path=canonical_bars_path,
                )
            )
        return tuple(sources)


def _normalize_frame(frame: pd.DataFrame) -> pd.DataFrame:
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
    return working.sort_index()


__all__ = ["FilesystemHistoricalDataStore"]
