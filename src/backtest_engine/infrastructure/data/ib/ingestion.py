"""Historical IB source-cache ingestion without legacy fetcher mixins."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

import pandas as pd

from backtest_engine.core.errors import InfrastructureError
from backtest_engine.core.time import ensure_utc
from backtest_engine.core.types import Symbol
from backtest_engine.infrastructure.data.ib.client import IbHistoricalClient
from backtest_engine.infrastructure.data.ib.contract_resolver import IbContractResolver
from backtest_engine.infrastructure.data.ib.contracts import (
    IbCacheArtifact,
    IbHistoricalIngestRequest,
    IbHistoricalIngestionResult,
    IbResolvedContract,
)
from backtest_engine.infrastructure.data.ib.storage import FilesystemIbCacheStore
from backtest_engine.infrastructure.data.ib.timeframes import IbTimeframe


@dataclass
class IbHistoricalCacheIngestor:
    """Build or refresh raw IB parquet caches for one canonical timeframe."""

    client: IbHistoricalClient
    contract_resolver: IbContractResolver
    cache_store: FilesystemIbCacheStore
    now_provider: Callable[[], datetime] | None = None

    def ingest(self, request: IbHistoricalIngestRequest) -> IbHistoricalIngestionResult:
        """Execute one explicit IB historical-cache ingestion request."""

        timeframe = IbTimeframe.from_timeframe(request.timeframe)
        self.client.connect()
        try:
            artifacts = tuple(
                self._ingest_symbol(
                    symbol=symbol,
                    request=request,
                    timeframe=timeframe,
                )
                for symbol in request.symbol_universe
            )
        finally:
            self.client.disconnect()

        return IbHistoricalIngestionResult(request=request, artifacts=artifacts)

    def _ingest_symbol(
        self,
        *,
        symbol: Symbol,
        request: IbHistoricalIngestRequest,
        timeframe: IbTimeframe,
    ) -> IbCacheArtifact:
        end_utc = ensure_utc(
            request.end_utc
            or (self._now_utc() - timedelta(minutes=self.client.settings.delayed_data_minutes))
        )
        start_utc = ensure_utc(
            request.start_utc
            or (end_utc - timedelta(days=self.client.settings.max_historical_years * 365))
        )

        if request.force_restart:
            self.cache_store.clear_checkpoint(symbol, request.timeframe)
            existing = pd.DataFrame()
        else:
            existing = self.cache_store.load_cache(symbol, request.timeframe)

        contracts = self.contract_resolver.resolve_contract_chain(symbol)
        new_head = pd.DataFrame()
        new_tail = pd.DataFrame()

        if not existing.empty:
            cache_max = existing.index.max().to_pydatetime()
            cache_min = existing.index.min().to_pydatetime()

            if cache_max < (end_utc - timedelta(days=2)):
                new_head = self._backfill_loop(
                    symbol=symbol,
                    timeframe=timeframe,
                    start_date=end_utc,
                    stop_date=cache_max,
                    contracts=contracts,
                    checkpoint_enabled=False,
                )

            if cache_min > (start_utc + timedelta(days=7)):
                checkpoint = self.cache_store.load_checkpoint(symbol, request.timeframe)
                resume_start = cache_min
                if checkpoint is not None and checkpoint.last_date_utc < resume_start:
                    resume_start = checkpoint.last_date_utc

                new_tail = self._backfill_loop(
                    symbol=symbol,
                    timeframe=timeframe,
                    start_date=resume_start,
                    stop_date=start_utc,
                    contracts=contracts,
                    checkpoint_enabled=True,
                )
        else:
            checkpoint = self.cache_store.load_checkpoint(symbol, request.timeframe)
            initial_start = checkpoint.last_date_utc if checkpoint is not None else end_utc
            new_tail = self._backfill_loop(
                symbol=symbol,
                timeframe=timeframe,
                start_date=initial_start,
                stop_date=start_utc,
                contracts=contracts,
                checkpoint_enabled=True,
            )

        frames_to_merge = tuple(
            frame for frame in (new_head, existing, new_tail) if not frame.empty
        )
        if not frames_to_merge:
            raise InfrastructureError(
                "IB ingestion produced no source data",
                symbol=symbol,
                timeframe=request.timeframe,
            )

        merged = pd.concat(frames_to_merge)
        artifact = self.cache_store.save_cache(
            symbol=symbol,
            timeframe=request.timeframe,
            frame=merged,
            generated_at_utc=self._now_utc(),
        )

        if artifact.manifest.start_time_utc is not None and artifact.manifest.start_time_utc <= (
            start_utc + timedelta(days=30)
        ):
            self.cache_store.clear_checkpoint(symbol, request.timeframe)

        return artifact

    def _backfill_loop(
        self,
        *,
        symbol: Symbol,
        timeframe: IbTimeframe,
        start_date: datetime,
        stop_date: datetime,
        contracts: tuple[IbResolvedContract, ...],
        checkpoint_enabled: bool,
    ) -> pd.DataFrame:
        collected: list[pd.DataFrame] = []
        current_date = ensure_utc(start_date)
        stop_boundary = ensure_utc(stop_date)
        current_contract: IbResolvedContract | None = None
        next_chunk_first_open_raw: float | None = None
        cumulative_adjustment = 0.0
        total_fetched = 0

        while current_date > stop_boundary:
            contract = self.contract_resolver.select_contract(contracts, target_utc=current_date)
            if contract is None:
                current_date -= timedelta(days=7)
                continue

            previous_contract = current_contract
            if previous_contract is None or contract.local_symbol != previous_contract.local_symbol:
                current_contract = contract

            chunk = self.client.fetch_chunk(
                contract,
                end_utc=current_date,
                timeframe=timeframe,
                duration=self.client.settings.chunk_duration,
            )

            if not chunk.empty:
                if (
                    previous_contract is not None
                    and contract.local_symbol != previous_contract.local_symbol
                    and next_chunk_first_open_raw is not None
                ):
                    old_close_raw = float(chunk["close"].iloc[-1])
                    gap = next_chunk_first_open_raw - old_close_raw
                    cumulative_adjustment += gap

                if cumulative_adjustment != 0.0:
                    for column in ("open", "high", "low", "close", "average"):
                        if column in chunk.columns:
                            chunk[column] = chunk[column].astype(float) + cumulative_adjustment

                next_chunk_first_open_raw = float(chunk["open"].iloc[0] - cumulative_adjustment)
                chunk["contract"] = contract.local_symbol
                collected.append(chunk)
                total_fetched += len(chunk)

            if checkpoint_enabled and total_fetched > 0 and total_fetched % 50000 == 0:
                self.cache_store.save_checkpoint(
                    symbol=symbol,
                    timeframe=timeframe.file_suffix,
                    last_date_utc=current_date,
                    total_bars=total_fetched,
                    updated_at_utc=self._now_utc(),
                )

            current_date -= timedelta(days=7)

        if not collected:
            return pd.DataFrame()
        return pd.concat(collected)

    def _now_utc(self) -> datetime:
        if self.now_provider is not None:
            return ensure_utc(self.now_provider())
        return datetime.now(timezone.utc)


__all__ = ["IbHistoricalCacheIngestor"]
