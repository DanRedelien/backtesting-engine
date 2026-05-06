"""Typed error taxonomy for the market-data pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backtest_engine.core.errors import InfrastructureError
from backtest_engine.infrastructure.data.market_data_contracts import ValidationManifest


class ProviderUnavailableError(InfrastructureError):
    """Raised when a requested historical-data provider is unavailable."""


class SymbolMappingError(InfrastructureError):
    """Raised when a canonical symbol cannot be resolved for one provider."""


class UnsupportedTimeframeError(InfrastructureError):
    """Raised when a provider does not support one timeframe natively."""


class InsufficientHistoryError(InfrastructureError):
    """Raised when a provider cannot cover the requested time window."""


class InvalidSourceDataError(InfrastructureError):
    """Raised when a saved source slice is structurally invalid."""


class VerificationFailedError(InfrastructureError):
    """Raised when a verification step fails for one saved source slice."""

    def __init__(
        self,
        message: str,
        *,
        validation_manifest: ValidationManifest | None = None,
        validation_manifest_path: Path | None = None,
        **context: Any,
    ) -> None:
        self.validation_manifest = validation_manifest
        self.validation_manifest_path = validation_manifest_path
        super().__init__(message, **context)


class ValidationManifestPersistenceError(InfrastructureError):
    """Raised when a validation manifest cannot be persisted."""


class MaterializationBlockedError(InfrastructureError):
    """Raised when a source slice cannot be materialized into a dataset."""


__all__ = [
    "InsufficientHistoryError",
    "InvalidSourceDataError",
    "MaterializationBlockedError",
    "ProviderUnavailableError",
    "SymbolMappingError",
    "UnsupportedTimeframeError",
    "ValidationManifestPersistenceError",
    "VerificationFailedError",
]
