"""Provider-agnostic source-slice and verification contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backtest_engine.core.enums import DatasetSource
from backtest_engine.core.time import ensure_utc
from backtest_engine.core.types import ContentHash, NonEmptyStr, Symbol, Timeframe


class TimeframeOrigin(StrEnum):
    """Source timeframe origin constants."""

    NATIVE = "native"


class ValidationSeverity(StrEnum):
    """Validation issue severities."""

    WARN = "WARN"
    FAIL = "FAIL"


class VerificationVerdict(StrEnum):
    """Top-level verification verdict."""

    PASS = "PASS"
    FAIL = "FAIL"


class ValidationCheckStatus(StrEnum):
    """Per-check operator-facing validation status."""

    OK = "OK"
    WARN = "WARN"
    BAD = "BAD"
    NA = "NA"


class MarketDataIssue(BaseModel):
    """One typed verification issue."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    severity: ValidationSeverity
    code: NonEmptyStr
    message: NonEmptyStr
    details: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class ValidationCheckResult(BaseModel):
    """Structured result for one stable validation check."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    check_code: NonEmptyStr
    check_label: NonEmptyStr | None = None
    check_status: ValidationCheckStatus
    score_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    affected_count: int | None = Field(default=None, ge=0)
    checked_count: int | None = Field(default=None, ge=0)
    issue_codes: tuple[NonEmptyStr, ...] = ()
    sample_details: tuple[dict[str, str | int | float | bool | None], ...] = ()


class ValidationScoreSummary(BaseModel):
    """Informational score summary for one validated slice."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    overall_score_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    applicable_check_count: int = Field(default=0, ge=0)
    total_check_count: int = Field(default=0, ge=0)
    warning_check_count: int = Field(default=0, ge=0)
    failed_check_count: int = Field(default=0, ge=0)


class ValidationWindowSummary(BaseModel):
    """Requested and observed source-window summary for one validation run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    requested_start_utc: datetime
    requested_end_utc: datetime
    actual_start_utc: datetime
    actual_end_utc: datetime
    start_status: Literal["covered", "expected_gap", "tolerated_gap", "missing"]
    end_status: Literal["covered", "expected_gap", "tolerated_gap", "missing"]

    @field_validator(
        "requested_start_utc",
        "requested_end_utc",
        "actual_start_utc",
        "actual_end_utc",
    )
    @classmethod
    def _ensure_utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)


class SourceDownloadCheckpoint(BaseModel):
    """Resumable download marker for one provider slice."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_id: NonEmptyStr
    canonical_symbol: Symbol
    timeframe: Timeframe
    last_timestamp_utc: datetime
    total_bars: int = Field(ge=0)
    updated_at_utc: datetime

    @field_validator("last_timestamp_utc", "updated_at_utc")
    @classmethod
    def _ensure_utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)


class SourceSliceManifest(BaseModel):
    """Manifest for one provider-managed source slice."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_id: NonEmptyStr
    source_system: DatasetSource
    canonical_symbol: Symbol
    provider_symbol: NonEmptyStr
    timeframe: Timeframe
    timeframe_origin: NonEmptyStr = TimeframeOrigin.NATIVE
    calendar_id: NonEmptyStr
    timezone_name: NonEmptyStr
    bars_path: Path
    requested_start_utc: datetime
    requested_end_utc: datetime
    actual_start_utc: datetime
    actual_end_utc: datetime
    generated_at_utc: datetime
    row_count: int = Field(ge=0)
    source_fingerprint: ContentHash
    provider_metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    instrument_metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    roll_policy: NonEmptyStr | None = None

    @field_validator(
        "requested_start_utc",
        "requested_end_utc",
        "actual_start_utc",
        "actual_end_utc",
        "generated_at_utc",
    )
    @classmethod
    def _ensure_utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)


class RollContractWindow(BaseModel):
    """One raw-contract window saved for a continuous futures slice."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_code: NonEmptyStr
    raw_path: Path
    start_utc: datetime
    end_utc: datetime

    @field_validator("start_utc", "end_utc")
    @classmethod
    def _ensure_utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)


class RollAdjustmentEvent(BaseModel):
    """One additive roll-adjustment event."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    roll_time_utc: datetime
    outgoing_contract: NonEmptyStr
    incoming_contract: NonEmptyStr
    outgoing_close_raw: float
    incoming_open_raw: float
    additive_adjustment: float
    cumulative_adjustment: float

    @field_validator("roll_time_utc")
    @classmethod
    def _ensure_utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)


class RollManifest(BaseModel):
    """Audit manifest for one additive back-adjusted futures series."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_id: NonEmptyStr
    canonical_symbol: Symbol
    timeframe: Timeframe
    roll_policy: NonEmptyStr
    contract_windows: tuple[RollContractWindow, ...] = ()
    events: tuple[RollAdjustmentEvent, ...] = ()
    generated_at_utc: datetime

    @field_validator("generated_at_utc")
    @classmethod
    def _ensure_utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)


class ValidationManifest(BaseModel):
    """Verification result stored beside one source slice."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_id: NonEmptyStr
    canonical_symbol: Symbol
    timeframe: Timeframe
    source_fingerprint: ContentHash
    validator_ruleset_version: NonEmptyStr
    verification_verdict: VerificationVerdict
    issues: tuple[MarketDataIssue, ...] = ()
    check_results: tuple[ValidationCheckResult, ...] = ()
    score_summary: ValidationScoreSummary | None = None
    window_summary: ValidationWindowSummary | None = None
    warning_count: int = Field(default=0, ge=0)
    failure_count: int = Field(default=0, ge=0)
    verified_at_utc: datetime

    @field_validator("verified_at_utc")
    @classmethod
    def _ensure_utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)


class DryRunMetadata(BaseModel):
    """Extra resolution info surfaced only in dry-run mode."""

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


class DownloadedSourceSlice(BaseModel):
    """Typed result returned by one provider adapter."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_id: NonEmptyStr
    source_system: DatasetSource
    canonical_symbol: Symbol
    timeframe: Timeframe
    bars_path: Path
    source_manifest_path: Path
    skipped: bool = False
    dry_run: bool = False
    dry_run_metadata: DryRunMetadata | None = None


__all__ = [
    "DownloadedSourceSlice",
    "DryRunMetadata",
    "ValidationCheckResult",
    "ValidationCheckStatus",
    "MarketDataIssue",
    "RollAdjustmentEvent",
    "RollContractWindow",
    "RollManifest",
    "SourceDownloadCheckpoint",
    "SourceSliceManifest",
    "ValidationScoreSummary",
    "TimeframeOrigin",
    "ValidationManifest",
    "ValidationWindowSummary",
    "ValidationSeverity",
    "VerificationVerdict",
]
