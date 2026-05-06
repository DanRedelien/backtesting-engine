"""Application-owned port abstractions for the market-data boundary."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Protocol


class HistoricalDataStore(Protocol):
    """Application-visible surface of the historical-data store.

    Declares only the query and path-resolution methods that the
    application service needs.  Infrastructure adapters satisfy this
    protocol structurally.
    """

    def has_complete_verified_slice(
        self,
        *,
        provider_id: str,
        canonical_symbol: str,
        timeframe: str,
        requested_start_utc: datetime,
        requested_end_utc: datetime,
        validator_ruleset_version: str,
    ) -> bool: ...

    def bars_path(
        self,
        provider_id: str,
        canonical_symbol: str,
        timeframe: str,
    ) -> Path: ...

    def source_manifest_path(
        self,
        provider_id: str,
        canonical_symbol: str,
        timeframe: str,
    ) -> Path: ...

    def validation_manifest_path(
        self,
        provider_id: str,
        canonical_symbol: str,
        timeframe: str,
    ) -> Path: ...


__all__ = ["HistoricalDataStore"]
