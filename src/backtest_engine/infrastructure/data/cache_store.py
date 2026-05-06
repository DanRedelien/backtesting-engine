"""Filesystem-backed resolution of source parquet datasets."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from backtest_engine.core.errors import InfrastructureError
from backtest_engine.core.types import Symbol, Timeframe
from backtest_engine.domain.market.datasets import DatasetSpec


class CachedBarSource(BaseModel):
    """The resolved source parquet for one symbol/timeframe slice."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: Symbol
    timeframe: Timeframe
    source_path: Path


@dataclass(frozen=True)
class FilesystemParquetCacheStore:
    """Resolve source parquet files from one explicit cache root."""

    source_cache_root: Path

    def resolve_source(self, symbol: Symbol, timeframe: Timeframe) -> CachedBarSource:
        """Return the canonical source parquet location for one slice."""

        source_path = self.source_cache_root / f"{symbol}_{timeframe}.parquet"
        if not source_path.is_file():
            raise InfrastructureError(
                "source parquet dataset not found",
                symbol=symbol,
                timeframe=timeframe,
                source_path=str(source_path),
            )
        return CachedBarSource(symbol=symbol, timeframe=timeframe, source_path=source_path)

    def resolve_sources(self, dataset: DatasetSpec) -> tuple[CachedBarSource, ...]:
        """Return the source slices declared by one dataset spec."""

        return tuple(
            self.resolve_source(symbol=symbol, timeframe=dataset.timeframe)
            for symbol in dataset.symbol_universe
        )


__all__ = ["CachedBarSource", "FilesystemParquetCacheStore"]
