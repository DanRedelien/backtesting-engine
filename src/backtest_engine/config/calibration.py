"""Validated settings for offline spread calibration workflows."""

from __future__ import annotations

import math
from datetime import time
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backtest_engine.config.execution_costs import UtcSessionBucketRule
from backtest_engine.core.market_data_validation import MARKET_DATA_VALIDATOR_RULESET_VERSION
from backtest_engine.core.timeframes import normalize_timeframe
from backtest_engine.core.types import NonEmptyStr, Timeframe


CalibrationPriceBasis = Literal["last_window_close"]
DEFAULT_CALIBRATION_VALIDATOR_RULESET_VERSION = MARKET_DATA_VALIDATOR_RULESET_VERSION
DEFAULT_CALIBRATION_SESSION_BUCKETS = (
    UtcSessionBucketRule(
        session_bucket_id="regular",
        weekdays=(0, 1, 2, 3, 4, 5, 6),
        start_time_utc=time(0, 0),
        end_time_utc=time(0, 0),
    ),
)
DEFAULT_CALIBRATION_DIAGNOSTICS_PATH = Path(__file__).resolve().parent / (
    "calibration_diagnostics.yaml"
)


class CalibrationVolumeSemantics(str, Enum):
    """Volume semantics accepted or rejected by calibration liquidity fitting."""

    TRADED_VOLUME = "traded_volume"
    CONTRACT_VOLUME = "contract_volume"
    SHARE_VOLUME = "share_volume"
    TICK_VOLUME = "tick_volume"
    UNKNOWN = "unknown"


class CalibrationLiquidityEligibilityPolicy(BaseModel):
    """Explicit policy for when calibration may fit liquidity coefficients."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    allowed_volume_semantics: tuple[CalibrationVolumeSemantics, ...] = (
        CalibrationVolumeSemantics.TRADED_VOLUME,
        CalibrationVolumeSemantics.CONTRACT_VOLUME,
        CalibrationVolumeSemantics.SHARE_VOLUME,
    )

    def allows(self, volume_semantics: CalibrationVolumeSemantics) -> bool:
        """Return whether the declared source volume semantics are trustworthy."""

        return volume_semantics in self.allowed_volume_semantics


class SpreadCalibrationPanelSettings(BaseModel):
    """Default policy knobs for Phase 1 EDGE panel construction."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    estimator_timeframe: Timeframe = "1m"
    edge_window_bars: int = Field(default=60, ge=3)
    validator_ruleset_version: NonEmptyStr = DEFAULT_CALIBRATION_VALIDATOR_RULESET_VERSION
    minimum_usable_rows_per_symbol: int = Field(default=1, ge=1)
    positive_volume_coverage_threshold: float = Field(default=1.0, gt=0.0, le=1.0)
    volatility_short_window_bars: int = Field(default=2, gt=0)
    volatility_baseline_window_bars: int = Field(default=2, gt=0)
    volatility_floor_price: Decimal = Field(default=Decimal("0.000000000001"), gt=0)
    volume_baseline_window_bars: int = Field(default=2, gt=0)
    volume_floor: Decimal = Field(default=Decimal("1"), gt=0)
    session_buckets: tuple[UtcSessionBucketRule, ...] = Field(
        default=DEFAULT_CALIBRATION_SESSION_BUCKETS,
        min_length=1,
    )
    price_basis: CalibrationPriceBasis = "last_window_close"

    @field_validator("estimator_timeframe")
    @classmethod
    def _normalize_estimator_timeframe(cls, value: str) -> str:
        return normalize_timeframe(value)

    @field_validator("positive_volume_coverage_threshold")
    @classmethod
    def _ensure_finite_coverage_threshold(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("positive_volume_coverage_threshold must be finite")
        return value

    @field_validator("volatility_floor_price", "volume_floor", mode="before")
    @classmethod
    def _coerce_decimal(cls, value: Decimal | float | int | str) -> Decimal:
        return Decimal(str(value))

    @field_validator("volatility_floor_price", "volume_floor")
    @classmethod
    def _ensure_finite_positive_decimal(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value <= Decimal("0"):
            raise ValueError("calibration feature floors must be finite and positive")
        return value


class SpreadCalibrationPublicationSettings(BaseModel):
    """Default policy knobs for Phase 2 fitting and generated YAML publication."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    output_root: Path = Path("var/runtime/calibration")
    train_fraction: float = Field(default=0.8, gt=0.0, lt=1.0)
    minimum_train_rows_per_symbol: int = Field(default=1, ge=1)
    minimum_holdout_rows_per_symbol: int = Field(default=1, ge=1)
    max_half_spread_train_quantile: float = Field(default=0.99, gt=0.0, le=1.0)
    min_half_spread_tick_fraction: Decimal = Field(default=Decimal("0.5"), ge=Decimal("0.5"))
    allow_liquidity_weight: bool = False
    allow_cross_timeframe_dynamic_weights: bool = False
    liquidity_coverage_threshold: float = Field(default=1.0, gt=0.0, le=1.0)
    liquidity_eligibility_policy: CalibrationLiquidityEligibilityPolicy = Field(
        default_factory=CalibrationLiquidityEligibilityPolicy,
    )
    volume_semantics: CalibrationVolumeSemantics = CalibrationVolumeSemantics.UNKNOWN
    allow_mixed_asset_classes: bool = False
    fit_tolerance: float = Field(default=1e-12, gt=0.0)
    max_fit_iterations: int = Field(default=1000, ge=1)

    @field_validator(
        "train_fraction",
        "max_half_spread_train_quantile",
        "liquidity_coverage_threshold",
        "fit_tolerance",
    )
    @classmethod
    def _ensure_finite_float(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("calibration publication floats must be finite")
        return value

    @field_validator("min_half_spread_tick_fraction", mode="before")
    @classmethod
    def _coerce_decimal(cls, value: Decimal | float | int | str) -> Decimal:
        return Decimal(str(value))

    @field_validator("min_half_spread_tick_fraction")
    @classmethod
    def _ensure_half_tick_floor(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value < Decimal("0.5"):
            raise ValueError("min_half_spread_tick_fraction must be at least 0.5")
        return value


class SpreadCalibrationDiagnosticsThresholds(BaseModel):
    """Internal heuristic thresholds for report-only diagnostics flags."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    absolute_mean_log_error_warning: float = Field(gt=0.0)
    absolute_mean_log_error_review: float = Field(gt=0.0)
    mae_log_warning: float = Field(gt=0.0)
    mae_log_review: float = Field(gt=0.0)
    rmse_log_warning: float = Field(gt=0.0)
    rmse_log_review: float = Field(gt=0.0)
    severe_underpricing_rate_1_5x_warning: float = Field(ge=0.0, le=1.0)
    severe_underpricing_rate_1_5x_review: float = Field(ge=0.0, le=1.0)
    severe_underpricing_rate_2_0x_warning: float = Field(ge=0.0, le=1.0)
    severe_underpricing_rate_2_0x_review: float = Field(ge=0.0, le=1.0)
    min_clip_rate_warning: float = Field(ge=0.0, le=1.0)
    min_clip_rate_review: float = Field(ge=0.0, le=1.0)
    max_clip_rate_warning: float = Field(ge=0.0, le=1.0)
    max_clip_rate_review: float = Field(ge=0.0, le=1.0)
    target_floor_rate_warning: float = Field(ge=0.0, le=1.0)
    target_floor_rate_review: float = Field(ge=0.0, le=1.0)
    baseline_mae_degradation_warning: float = Field(gt=0.0)
    baseline_mae_degradation_review: float = Field(gt=0.0)

    @field_validator(
        "absolute_mean_log_error_warning",
        "absolute_mean_log_error_review",
        "mae_log_warning",
        "mae_log_review",
        "rmse_log_warning",
        "rmse_log_review",
        "severe_underpricing_rate_1_5x_warning",
        "severe_underpricing_rate_1_5x_review",
        "severe_underpricing_rate_2_0x_warning",
        "severe_underpricing_rate_2_0x_review",
        "min_clip_rate_warning",
        "min_clip_rate_review",
        "max_clip_rate_warning",
        "max_clip_rate_review",
        "target_floor_rate_warning",
        "target_floor_rate_review",
        "baseline_mae_degradation_warning",
        "baseline_mae_degradation_review",
    )
    @classmethod
    def _ensure_finite_threshold(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("calibration diagnostic thresholds must be finite")
        return value

    @model_validator(mode="after")
    def _validate_warning_not_above_review(self) -> "SpreadCalibrationDiagnosticsThresholds":
        threshold_pairs = (
            ("absolute_mean_log_error", self.absolute_mean_log_error_warning, self.absolute_mean_log_error_review),
            ("mae_log", self.mae_log_warning, self.mae_log_review),
            ("rmse_log", self.rmse_log_warning, self.rmse_log_review),
            (
                "severe_underpricing_rate_1_5x",
                self.severe_underpricing_rate_1_5x_warning,
                self.severe_underpricing_rate_1_5x_review,
            ),
            (
                "severe_underpricing_rate_2_0x",
                self.severe_underpricing_rate_2_0x_warning,
                self.severe_underpricing_rate_2_0x_review,
            ),
            ("min_clip_rate", self.min_clip_rate_warning, self.min_clip_rate_review),
            ("max_clip_rate", self.max_clip_rate_warning, self.max_clip_rate_review),
            ("target_floor_rate", self.target_floor_rate_warning, self.target_floor_rate_review),
            (
                "baseline_mae_degradation",
                self.baseline_mae_degradation_warning,
                self.baseline_mae_degradation_review,
            ),
        )
        inverted_pairs = [
            metric_name
            for metric_name, warning_threshold, review_threshold in threshold_pairs
            if warning_threshold > review_threshold
        ]
        if inverted_pairs:
            raise ValueError(
                "calibration diagnostic warning thresholds must not exceed review thresholds: "
                + ",".join(inverted_pairs)
            )
        return self


class SpreadCalibrationDiagnosticsPalette(BaseModel):
    """Matplotlib palette for calibration diagnostics artifacts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    paper: NonEmptyStr
    panel: NonEmptyStr
    ink: NonEmptyStr
    muted: NonEmptyStr
    line: NonEmptyStr
    accent: NonEmptyStr
    negative: NonEmptyStr
    amber: NonEmptyStr


class SpreadCalibrationDiagnosticsPlotSettings(BaseModel):
    """Plot rendering settings for deterministic diagnostics PNG artifacts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    backend: NonEmptyStr = "Agg"
    dpi: int = Field(default=140, ge=72)
    summary_width_inches: float = Field(default=11.0, gt=0.0)
    summary_height_inches: float = Field(default=6.5, gt=0.0)
    symbol_width_inches: float = Field(default=12.0, gt=0.0)
    symbol_height_inches: float = Field(default=9.0, gt=0.0)

    @field_validator(
        "summary_width_inches",
        "summary_height_inches",
        "symbol_width_inches",
        "symbol_height_inches",
    )
    @classmethod
    def _ensure_finite_size(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("calibration diagnostic plot sizes must be finite")
        return value


class SpreadCalibrationDiagnosticsSettings(BaseModel):
    """Validated settings for report-only spread calibration diagnostics."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = Field(ge=1)
    policy_name: NonEmptyStr
    policy_description: NonEmptyStr
    threshold_interpretation: NonEmptyStr
    threshold_status_levels: tuple[Literal["warning", "review_flag"], ...]
    thresholds: SpreadCalibrationDiagnosticsThresholds
    palette: SpreadCalibrationDiagnosticsPalette
    plot: SpreadCalibrationDiagnosticsPlotSettings
    decile_count: int = Field(default=10, ge=2)
    regime_bucket_labels: tuple[NonEmptyStr, ...] = Field(default=("low", "mid", "high"))
    minimum_regression_rows: int = Field(default=2, ge=2)

    @field_validator("threshold_status_levels")
    @classmethod
    def _validate_status_levels(
        cls,
        value: tuple[Literal["warning", "review_flag"], ...],
    ) -> tuple[Literal["warning", "review_flag"], ...]:
        if value != ("warning", "review_flag"):
            raise ValueError(
                "calibration diagnostic status levels must be warning and review_flag"
            )
        return value

    @field_validator("regime_bucket_labels")
    @classmethod
    def _validate_regime_bucket_labels(
        cls,
        value: tuple[NonEmptyStr, ...],
    ) -> tuple[NonEmptyStr, ...]:
        if value != ("low", "mid", "high"):
            raise ValueError("calibration diagnostic regime buckets must be low/mid/high")
        return value


def default_calibration_diagnostics_path() -> Path:
    """Return the bundled diagnostics settings path."""

    return DEFAULT_CALIBRATION_DIAGNOSTICS_PATH


def load_calibration_diagnostics_settings(
    path: Path | str | None = None,
) -> SpreadCalibrationDiagnosticsSettings:
    """Load and validate report-only spread calibration diagnostics settings."""

    resolved_path = Path(path) if path is not None else default_calibration_diagnostics_path()
    raw = yaml.safe_load(resolved_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"expected a mapping YAML object in {resolved_path}")
    return SpreadCalibrationDiagnosticsSettings.model_validate(raw)


__all__ = [
    "CalibrationLiquidityEligibilityPolicy",
    "CalibrationPriceBasis",
    "CalibrationVolumeSemantics",
    "DEFAULT_CALIBRATION_SESSION_BUCKETS",
    "DEFAULT_CALIBRATION_DIAGNOSTICS_PATH",
    "DEFAULT_CALIBRATION_VALIDATOR_RULESET_VERSION",
    "SpreadCalibrationDiagnosticsPalette",
    "SpreadCalibrationDiagnosticsPlotSettings",
    "SpreadCalibrationDiagnosticsSettings",
    "SpreadCalibrationDiagnosticsThresholds",
    "SpreadCalibrationPanelSettings",
    "SpreadCalibrationPublicationSettings",
    "default_calibration_diagnostics_path",
    "load_calibration_diagnostics_settings",
]
