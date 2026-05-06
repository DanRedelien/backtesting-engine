"""Typed contracts for the V2 IB source-cache boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backtest_engine.core.enums import DatasetSource
from backtest_engine.core.errors import InfrastructureError
from backtest_engine.core.time import ensure_utc
from backtest_engine.core.types import NonEmptyStr, Symbol, Timeframe
from backtest_engine.domain.market.datasets import DatasetSpec


@dataclass(frozen=True)
class IbResolvedContract:
    """One resolved IB futures contract kept inside infrastructure only."""

    symbol: Symbol
    exchange: NonEmptyStr
    local_symbol: NonEmptyStr
    expiry_utc: datetime
    contract_handle: object = field(repr=False, compare=False)


class IbHistoricalIngestRequest(BaseModel):
    """Explicit request to build or refresh IB-backed source parquet caches."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol_universe: tuple[Symbol, ...]
    timeframe: Timeframe
    force_restart: bool = False
    start_utc: datetime | None = None
    end_utc: datetime | None = None

    @field_validator("start_utc", "end_utc")
    @classmethod
    def _ensure_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return ensure_utc(value)

    @model_validator(mode="after")
    def _validate_window(self) -> "IbHistoricalIngestRequest":
        if (
            self.start_utc is not None
            and self.end_utc is not None
            and self.start_utc >= self.end_utc
        ):
            raise ValueError("IB ingest request start_utc must be earlier than end_utc")
        return self

    @classmethod
    def from_dataset(
        cls,
        dataset: DatasetSpec,
        *,
        force_restart: bool = False,
    ) -> "IbHistoricalIngestRequest":
        """Build an ingestion request from one canonical IB dataset spec."""

        if dataset.source_system is not DatasetSource.IB:
            raise InfrastructureError(
                "IB ingestion requests require DatasetSource.IB",
                source_system=dataset.source_system,
                dataset_id=dataset.dataset_id,
            )
        return cls(
            symbol_universe=dataset.symbol_universe,
            timeframe=dataset.timeframe,
            force_restart=force_restart,
        )


class IbDownloadCheckpoint(BaseModel):
    """Resumable progress marker for one symbol/timeframe historical backfill."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: Symbol
    timeframe: Timeframe
    last_date_utc: datetime
    total_bars: int = Field(ge=0)
    updated_at_utc: datetime

    @field_validator("last_date_utc", "updated_at_utc")
    @classmethod
    def _ensure_utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)


class IbCacheManifest(BaseModel):
    """Manifest for one persisted IB source parquet cache artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_system: DatasetSource = DatasetSource.IB
    symbol: Symbol
    timeframe: Timeframe
    cache_path: Path
    row_count: int = Field(ge=0)
    start_time_utc: datetime | None = None
    end_time_utc: datetime | None = None
    contract_codes: tuple[NonEmptyStr, ...] = ()
    generated_at_utc: datetime

    @field_validator("start_time_utc", "end_time_utc", "generated_at_utc")
    @classmethod
    def _ensure_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return ensure_utc(value)


class IbCacheArtifact(BaseModel):
    """Filesystem pair for one saved IB source cache plus manifest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: Symbol
    timeframe: Timeframe
    cache_path: Path
    manifest_path: Path
    manifest: IbCacheManifest


class IbHistoricalIngestionResult(BaseModel):
    """Typed result for one IB historical-cache ingestion request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request: IbHistoricalIngestRequest
    artifacts: tuple[IbCacheArtifact, ...]


def parse_ib_expiry(raw_value: str) -> datetime:
    """Normalize IB expiry strings into UTC-aware datetimes."""

    if len(raw_value) == 8:
        expiry = datetime.strptime(raw_value, "%Y%m%d")
    else:
        expiry = datetime.strptime(f"{raw_value}15", "%Y%m%d")
    return expiry.replace(tzinfo=timezone.utc)


__all__ = [
    "IbCacheArtifact",
    "IbCacheManifest",
    "IbDownloadCheckpoint",
    "IbHistoricalIngestRequest",
    "IbHistoricalIngestionResult",
    "IbResolvedContract",
    "parse_ib_expiry",
]
