"""Application-layer contracts for historical market data."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from backtest_engine.core.enums import DatasetSource
from backtest_engine.core.time import ensure_utc
from backtest_engine.core.types import NonEmptyStr, Symbol, Timeframe


CheckStatus = Literal["OK", "WARN", "BAD", "NA"]
VerificationVerdict = Literal["PASS", "FAIL"]
CoverageStatus = Literal["covered", "expected_gap", "tolerated_gap", "missing"]
DetailValue = str | int | float | bool | None


class MarketDataErrorDetail(BaseModel):
    """Structured error for one requested market-data slice."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: NonEmptyStr
    message: NonEmptyStr
    details: dict[str, DetailValue] = Field(default_factory=dict)


class MarketDataDryRunMetadata(BaseModel):
    """Application-owned dry-run detail surfaced to delivery adapters."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_symbol: NonEmptyStr
    supported_timeframes: tuple[Timeframe, ...]
    window_mode: Literal["explicit", "max_available"]
    requested_start_utc: datetime
    requested_end_utc: datetime
    calendar_id: NonEmptyStr | None = None

    @field_validator("requested_start_utc", "requested_end_utc")
    @classmethod
    def _ensure_utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)


class MarketDataValidationCheckDetail(BaseModel):
    """Operator-facing verification detail for one stable check."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    check_code: NonEmptyStr
    check_label: NonEmptyStr | None = None
    check_status: CheckStatus
    score_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    affected_count: int | None = Field(default=None, ge=0)
    checked_count: int | None = Field(default=None, ge=0)
    issue_codes: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)
    sample_details: tuple[dict[str, DetailValue], ...] = Field(default_factory=tuple)


class MarketDataValidationScoreSummary(BaseModel):
    """Application-owned verification score summary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    overall_score_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    applicable_check_count: int = Field(default=0, ge=0)
    total_check_count: int = Field(default=0, ge=0)
    warning_check_count: int = Field(default=0, ge=0)
    failed_check_count: int = Field(default=0, ge=0)


class MarketDataValidationWindowSummary(BaseModel):
    """Requested and observed source-window summary for one verification run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    requested_start_utc: datetime
    requested_end_utc: datetime
    actual_start_utc: datetime
    actual_end_utc: datetime
    start_status: CoverageStatus
    end_status: CoverageStatus

    @field_validator(
        "requested_start_utc",
        "requested_end_utc",
        "actual_start_utc",
        "actual_end_utc",
    )
    @classmethod
    def _ensure_utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)


class MarketDataValidationReport(BaseModel):
    """Application-owned verification report used by CLI and UI adapters."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_fingerprint: NonEmptyStr
    validator_ruleset_version: NonEmptyStr
    verification_verdict: VerificationVerdict
    check_results: tuple[MarketDataValidationCheckDetail, ...] = Field(default_factory=tuple)
    score_summary: MarketDataValidationScoreSummary | None = None
    window_summary: MarketDataValidationWindowSummary | None = None
    warning_count: int = Field(default=0, ge=0)
    failure_count: int = Field(default=0, ge=0)
    verified_at_utc: datetime

    @field_validator("verified_at_utc")
    @classmethod
    def _ensure_utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)


class HistoricalMarketDataRequest(BaseModel):
    """Request to download historical market data from one provider."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_id: NonEmptyStr
    symbol_universe: tuple[Symbol, ...]
    timeframes: tuple[Timeframe, ...]
    start_utc: datetime | None = None
    end_utc: datetime | None = None
    requested_by: NonEmptyStr = "cli"
    dry_run: bool = False
    force: bool = False

    @field_validator("start_utc", "end_utc")
    @classmethod
    def _ensure_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return ensure_utc(value)

    @model_validator(mode="after")
    def _validate_window_edges(self) -> HistoricalMarketDataRequest:
        if (self.start_utc is None) != (self.end_utc is None):
            raise ValueError("start_utc and end_utc must either both be set or both be omitted")
        return self


class HistoricalMarketDataSliceResult(BaseModel):
    """Outcome of one provider slice download."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_id: NonEmptyStr
    source_system: DatasetSource
    canonical_symbol: Symbol
    timeframe: Timeframe
    status: NonEmptyStr
    bars_path: Path | None = None
    source_manifest_path: Path | None = None
    error: MarketDataErrorDetail | None = None
    dry_run_metadata: MarketDataDryRunMetadata | None = None


class HistoricalMarketDataBatchResult(BaseModel):
    """Batch result for one download request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request: HistoricalMarketDataRequest
    slice_results: tuple[HistoricalMarketDataSliceResult, ...]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def succeeded(self) -> bool:
        return all(result.error is None for result in self.slice_results)


class MarketDataVerificationRequest(BaseModel):
    """Request to verify existing downloaded market-data slices."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_id: NonEmptyStr
    symbol_universe: tuple[Symbol, ...]
    timeframes: tuple[Timeframe, ...]
    requested_by: NonEmptyStr = "cli"


class MarketDataVerificationSliceResult(BaseModel):
    """Outcome of one verification run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_id: NonEmptyStr
    canonical_symbol: Symbol
    timeframe: Timeframe
    status: NonEmptyStr
    validation_manifest_path: Path | None = None
    validation_manifest: MarketDataValidationReport | None = None
    error: MarketDataErrorDetail | None = None


class MarketDataVerificationBatchResult(BaseModel):
    """Batch verification result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request: MarketDataVerificationRequest
    slice_results: tuple[MarketDataVerificationSliceResult, ...]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def succeeded(self) -> bool:
        return all(result.error is None for result in self.slice_results)


__all__ = [
    "HistoricalMarketDataBatchResult",
    "HistoricalMarketDataRequest",
    "HistoricalMarketDataSliceResult",
    "MarketDataDryRunMetadata",
    "MarketDataErrorDetail",
    "MarketDataValidationCheckDetail",
    "MarketDataValidationReport",
    "MarketDataValidationScoreSummary",
    "MarketDataValidationWindowSummary",
    "MarketDataVerificationBatchResult",
    "MarketDataVerificationRequest",
    "MarketDataVerificationSliceResult",
]
