"""Normalize source parquet caches into explicit dataset artifacts."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backtest_engine.core.enums import DatasetSource
from backtest_engine.core.errors import InfrastructureError
from backtest_engine.core.time import ensure_utc
from backtest_engine.core.types import NonEmptyStr, Symbol, Timeframe
from backtest_engine.domain.market.datasets import DatasetSpec
from backtest_engine.infrastructure.data.cache_store import (
    CachedBarSource,
    FilesystemParquetCacheStore,
)
from backtest_engine.infrastructure.data.market_data_store import FilesystemHistoricalDataStore
from backtest_engine.infrastructure.data.verification import MARKET_DATA_VALIDATOR_RULESET_VERSION

if TYPE_CHECKING:
    from backtest_engine.infrastructure.nautilus.symbol_map import SymbolMap


# Canonical bar time: source/provider bar open timestamp normalized to UTC.
# This normalizer owns any future semantic change, such as a completed-bar shift.
NORMALIZED_BAR_COLUMNS = (
    "ts_event_utc",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "vwap",
    "trade_count",
    "contract_code",
)


class NormalizedBarManifest(BaseModel):
    """Manifest for one normalized symbol/timeframe dataset slice."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_id: NonEmptyStr
    source_system: DatasetSource
    raw_symbol: Symbol
    timeframe: Timeframe
    normalization_policy: NonEmptyStr
    schema_version: NonEmptyStr
    source_path: Path
    source_fingerprint: NonEmptyStr
    row_count: int
    start_time_utc: datetime
    end_time_utc: datetime
    columns: tuple[str, ...] = NORMALIZED_BAR_COLUMNS
    nautilus_instrument_id: NonEmptyStr
    instrument_metadata: dict[str, object] = Field(default_factory=dict)

    @field_validator("start_time_utc", "end_time_utc")
    @classmethod
    def _ensure_utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)


class NormalizedBarArtifact(BaseModel):
    """The persisted artifact pair for one normalized slice."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: Symbol
    timeframe: Timeframe
    data_path: Path
    manifest_path: Path
    manifest: NormalizedBarManifest


class DatasetMaterializationManifest(BaseModel):
    """Top-level manifest for one materialized dataset root."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_id: NonEmptyStr
    normalization_policy: NonEmptyStr
    schema_version: NonEmptyStr
    dataset_version: NonEmptyStr
    timeframe: Timeframe
    symbol_universe: tuple[Symbol, ...]
    artifacts: tuple[Path, ...]


class MaterializedDataset(BaseModel):
    """A persisted normalized dataset ready for downstream adapters."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset: DatasetSpec
    dataset_root: Path
    manifest_path: Path
    artifacts: tuple[NormalizedBarArtifact, ...]


@dataclass(frozen=True)
class FilesystemParquetDatasetNormalizer:
    """Normalize parquet source caches into persisted dataset artifacts."""

    cache_store: FilesystemParquetCacheStore
    normalized_root: Path
    symbol_map_path: Path | None = None
    market_data_store: FilesystemHistoricalDataStore | None = None
    validator_ruleset_version: NonEmptyStr = MARKET_DATA_VALIDATOR_RULESET_VERSION

    def materialize(self, dataset: DatasetSpec) -> MaterializedDataset:
        """Return a persisted normalized dataset for one dataset spec."""

        if dataset.source_system not in {
            DatasetSource.PARQUET,
            DatasetSource.IB,
            DatasetSource.MT5,
        }:
            raise InfrastructureError(
                "parquet normalizer supports only DatasetSource.PARQUET, DatasetSource.IB, or DatasetSource.MT5",
                source_system=dataset.source_system,
                dataset_id=dataset.dataset_id,
            )

        sources = (
            self._resolve_managed_sources(dataset)
            if dataset.source_system in {DatasetSource.IB, DatasetSource.MT5}
            else self.cache_store.resolve_sources(dataset)
        )
        dataset_root = self.normalized_root / dataset.dataset_id
        manifest_path = dataset_root / "dataset_manifest.json"
        if manifest_path.is_file():
            cached = self._load_cached_materialization(
                dataset=dataset,
                manifest_path=manifest_path,
                sources=sources,
            )
            if cached is not None:
                return cached

        symbol_map = _load_symbol_map(self.symbol_map_path)
        dataset_root.mkdir(parents=True, exist_ok=True)
        artifacts = tuple(
            self._materialize_source(
                dataset=dataset,
                source=source,
                dataset_root=dataset_root,
                symbol_map=symbol_map,
            )
            for source in sources
        )
        manifest = DatasetMaterializationManifest(
            dataset_id=dataset.dataset_id,
            normalization_policy=dataset.normalization_policy,
            schema_version=dataset.schema_version,
            dataset_version=dataset.dataset_version,
            timeframe=dataset.timeframe,
            symbol_universe=dataset.symbol_universe,
            artifacts=tuple(artifact.manifest_path for artifact in artifacts),
        )
        manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        return MaterializedDataset(
            dataset=dataset,
            dataset_root=dataset_root,
            manifest_path=manifest_path,
            artifacts=artifacts,
        )

    def _load_cached_materialization(
        self,
        dataset: DatasetSpec,
        manifest_path: Path,
        *,
        sources: tuple[CachedBarSource, ...],
    ) -> MaterializedDataset | None:
        try:
            manifest = DatasetMaterializationManifest.model_validate_json(
                manifest_path.read_text(encoding="utf-8"),
            )
        except Exception:
            return None

        if len(manifest.artifacts) != len(sources):
            return None

        current_sources = {(source.symbol, source.timeframe): source for source in sources}
        artifacts: list[NormalizedBarArtifact] = []
        for artifact_manifest_path in manifest.artifacts:
            if not artifact_manifest_path.is_file():
                return None
            artifact = self._load_artifact(artifact_manifest_path)
            if artifact is None or not artifact.data_path.is_file():
                return None
            current_source = current_sources.get((artifact.symbol, artifact.timeframe))
            if current_source is None:
                return None
            if artifact.manifest.source_path != current_source.source_path:
                return None
            try:
                current_fingerprint = _compute_file_hash(current_source.source_path)
            except OSError:
                return None
            if artifact.manifest.source_fingerprint != current_fingerprint:
                return None
            artifacts.append(artifact)

        return MaterializedDataset(
            dataset=dataset,
            dataset_root=manifest_path.parent,
            manifest_path=manifest_path,
            artifacts=tuple(artifacts),
        )

    def _resolve_managed_sources(self, dataset: DatasetSpec) -> tuple[CachedBarSource, ...]:
        active_store = self.market_data_store or FilesystemHistoricalDataStore(
            source_cache_root=self.cache_store.source_cache_root,
        )
        return active_store.resolve_verified_sources(
            dataset,
            validator_ruleset_version=self.validator_ruleset_version,
        )

    def _load_artifact(self, manifest_path: Path) -> NormalizedBarArtifact | None:
        try:
            manifest = NormalizedBarManifest.model_validate_json(
                manifest_path.read_text(encoding="utf-8"),
            )
        except Exception:
            return None

        return NormalizedBarArtifact(
            symbol=manifest.raw_symbol,
            timeframe=manifest.timeframe,
            data_path=manifest_path.parent / "bars.parquet",
            manifest_path=manifest_path,
            manifest=manifest,
        )

    def _materialize_source(
        self,
        dataset: DatasetSpec,
        source: CachedBarSource,
        dataset_root: Path,
        symbol_map: SymbolMap,
    ) -> NormalizedBarArtifact:
        frame = self._read_source_frame(source.source_path)
        normalized = _normalize_frame(frame)
        mapping = symbol_map.resolve(source.symbol)
        source_fingerprint = _compute_file_hash(source.source_path)
        artifact_root = dataset_root / source.symbol / source.timeframe
        artifact_root.mkdir(parents=True, exist_ok=True)
        data_path = artifact_root / "bars.parquet"
        manifest_path = artifact_root / "manifest.json"
        normalized.to_parquet(data_path, index=False)
        manifest = NormalizedBarManifest(
            dataset_id=dataset.dataset_id,
            source_system=dataset.source_system,
            raw_symbol=source.symbol,
            timeframe=source.timeframe,
            normalization_policy=dataset.normalization_policy,
            schema_version=dataset.schema_version,
            source_path=source.source_path,
            source_fingerprint=source_fingerprint,
            row_count=int(len(normalized)),
            start_time_utc=normalized["ts_event_utc"].iloc[0].to_pydatetime(),
            end_time_utc=normalized["ts_event_utc"].iloc[-1].to_pydatetime(),
            nautilus_instrument_id=mapping.nautilus_instrument_id,
            instrument_metadata=mapping.metadata_dict(),
        )
        manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        return NormalizedBarArtifact(
            symbol=source.symbol,
            timeframe=source.timeframe,
            data_path=data_path,
            manifest_path=manifest_path,
            manifest=manifest,
        )

    def _read_source_frame(self, source_path: Path) -> pd.DataFrame:
        try:
            return pd.read_parquet(source_path)
        except Exception as exc:
            raise InfrastructureError(
                "failed to read source parquet dataset",
                source_path=str(source_path),
            ) from exc


def _normalize_frame(frame: pd.DataFrame) -> pd.DataFrame:
    _validate_required_columns(frame)
    normalized_index = _normalize_timestamp_index(frame)
    working = frame.copy()
    working.index = normalized_index
    working = working.sort_index()
    normalized = pd.DataFrame(
        {
            "ts_event_utc": normalized_index,
            "open": working["open"].astype(float),
            "high": working["high"].astype(float),
            "low": working["low"].astype(float),
            "close": working["close"].astype(float),
            "volume": working["volume"].astype(float),
            "vwap": (
                working["average"].astype(float)
                if "average" in working.columns
                else pd.Series([pd.NA] * len(working), index=working.index, dtype="Float64")
            ),
            "trade_count": (
                working["barCount"].astype("Int64")
                if "barCount" in working.columns
                else pd.Series([pd.NA] * len(working), index=working.index, dtype="Int64")
            ),
            "contract_code": (
                working["contract"].astype("string")
                if "contract" in working.columns
                else pd.Series([pd.NA] * len(working), index=working.index, dtype="string")
            ),
        }
    )
    return normalized[list(NORMALIZED_BAR_COLUMNS)]


def _normalize_timestamp_index(frame: pd.DataFrame) -> pd.DatetimeIndex:
    index = frame.index
    if not isinstance(index, pd.DatetimeIndex):
        if "date" in frame.columns:
            index = pd.DatetimeIndex(pd.to_datetime(frame["date"], utc=True))
        else:
            index = pd.DatetimeIndex(pd.to_datetime(index, utc=True))
    elif index.tz is None:
        index = index.tz_localize("UTC")
    else:
        index = index.tz_convert("UTC")

    normalized_index = pd.DatetimeIndex(sorted(pd.DatetimeIndex(index)))
    if normalized_index.has_duplicates:
        raise InfrastructureError(
            "source parquet contains duplicate timestamps after UTC normalization"
        )
    return normalized_index


def _validate_required_columns(frame: pd.DataFrame) -> None:
    required = {"open", "high", "low", "close", "volume"}
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise InfrastructureError(
            "source parquet is missing required OHLCV columns",
            missing_columns=",".join(missing),
        )


def _load_symbol_map(symbol_map_path: Path | None) -> "SymbolMap":
    from backtest_engine.infrastructure.nautilus.symbol_map import load_symbol_map

    return load_symbol_map(symbol_map_path)


def _compute_file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "DatasetMaterializationManifest",
    "FilesystemParquetDatasetNormalizer",
    "MaterializedDataset",
    "NORMALIZED_BAR_COLUMNS",
    "NormalizedBarArtifact",
    "NormalizedBarManifest",
]
