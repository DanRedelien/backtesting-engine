"""Application contracts for offline spread calibration."""

from __future__ import annotations

import math
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from backtest_engine.config.calibration import (
    CalibrationLiquidityEligibilityPolicy,
    CalibrationPriceBasis,
    CalibrationVolumeSemantics,
    SpreadCalibrationPanelSettings,
    SpreadCalibrationPublicationSettings,
)
from backtest_engine.config.execution_costs import UtcSessionBucketRule
from backtest_engine.core.time import ensure_utc
from backtest_engine.core.timeframes import normalize_timeframe
from backtest_engine.core.types import NonEmptyStr, Timeframe
from backtest_engine.infrastructure.data.parquet_normalizer import MaterializedDataset


PriceBasis = CalibrationPriceBasis
_PANEL_DEFAULTS = SpreadCalibrationPanelSettings()
_PUBLICATION_DEFAULTS = SpreadCalibrationPublicationSettings()
_FLOAT_REL_TOLERANCE = 1e-12
_FLOAT_ABS_TOLERANCE = 1e-15


class SpreadCalibrationCommand(BaseModel):
    """Request to build an offline EDGE calibration panel from normalized bars.

    The command intentionally contains only market-data, estimator, and sample
    controls. Strategy returns, trades, portfolio weights, and alpha parameters
    do not belong at this boundary.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    materialized_dataset: MaterializedDataset
    estimator_timeframe: Timeframe = _PANEL_DEFAULTS.estimator_timeframe
    edge_window_bars: int = Field(default=_PANEL_DEFAULTS.edge_window_bars, ge=3)
    calibration_start_utc: datetime | None = None
    calibration_end_utc: datetime | None = None
    validator_ruleset_version: NonEmptyStr = _PANEL_DEFAULTS.validator_ruleset_version
    minimum_usable_rows_per_symbol: int = Field(
        default=_PANEL_DEFAULTS.minimum_usable_rows_per_symbol,
        ge=1,
    )
    positive_volume_coverage_threshold: float = Field(
        default=_PANEL_DEFAULTS.positive_volume_coverage_threshold,
        gt=0.0,
        le=1.0,
    )
    volatility_short_window_bars: int = Field(
        default=_PANEL_DEFAULTS.volatility_short_window_bars,
        gt=0,
    )
    volatility_baseline_window_bars: int = Field(
        default=_PANEL_DEFAULTS.volatility_baseline_window_bars,
        gt=0,
    )
    volatility_floor_price: Decimal = Field(default=_PANEL_DEFAULTS.volatility_floor_price, gt=0)
    volume_baseline_window_bars: int = Field(
        default=_PANEL_DEFAULTS.volume_baseline_window_bars,
        gt=0,
    )
    volume_floor: Decimal = Field(default=_PANEL_DEFAULTS.volume_floor, gt=0)
    session_buckets: tuple[UtcSessionBucketRule, ...] = Field(
        default=_PANEL_DEFAULTS.session_buckets,
        min_length=1,
    )
    price_basis: PriceBasis = _PANEL_DEFAULTS.price_basis
    requested_by: NonEmptyStr = "operator"
    correlation_id: NonEmptyStr | None = None

    @field_validator("calibration_start_utc", "calibration_end_utc")
    @classmethod
    def _ensure_optional_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return ensure_utc(value)

    @model_validator(mode="after")
    def _validate_window(self) -> SpreadCalibrationCommand:
        if (
            self.calibration_start_utc is not None
            and self.calibration_end_utc is not None
            and self.calibration_start_utc >= self.calibration_end_utc
        ):
            raise ValueError("calibration_start_utc must be before calibration_end_utc")
        return self

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

    @field_validator("estimator_timeframe")
    @classmethod
    def _normalize_estimator_timeframe(cls, value: str) -> str:
        return normalize_timeframe(value)


class SpreadCalibrationPanelRow(BaseModel):
    """One ex-ante calibration target row from a completed EDGE window."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: NonEmptyStr
    estimator_timeframe: Timeframe
    fill_timestamp_utc: datetime
    target_observed_at_utc: datetime
    feature_observed_at_utc: datetime
    edge_window_start_utc: datetime
    edge_window_end_utc: datetime
    edge_window_bars: int = Field(ge=3)
    session_bucket_id: NonEmptyStr
    volatility_stress_signal: float
    liquidity_stress_signal: float
    liquidity_observed_volume: float = Field(ge=0.0)
    edge_full_spread_frac_signed: float
    edge_full_spread_frac_nonnegative: float = Field(ge=0.0)
    reference_price: float = Field(gt=0.0)
    half_spread_price: float = Field(ge=0.0)
    price_basis: PriceBasis
    conversion_method: NonEmptyStr
    source_fingerprint: NonEmptyStr
    validator_ruleset_version: NonEmptyStr
    negative_edge_estimate: bool

    @field_validator(
        "edge_full_spread_frac_signed",
        "edge_full_spread_frac_nonnegative",
        "volatility_stress_signal",
        "liquidity_stress_signal",
        "liquidity_observed_volume",
        "reference_price",
        "half_spread_price",
    )
    @classmethod
    def _ensure_finite_float(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("calibration panel numeric values must be finite")
        return value

    @field_validator(
        "fill_timestamp_utc",
        "target_observed_at_utc",
        "feature_observed_at_utc",
        "edge_window_start_utc",
        "edge_window_end_utc",
    )
    @classmethod
    def _ensure_utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)

    @model_validator(mode="after")
    def _validate_panel_row_contract(self) -> SpreadCalibrationPanelRow:
        expected_nonnegative = max(0.0, self.edge_full_spread_frac_signed)
        if not math.isclose(
            self.edge_full_spread_frac_nonnegative,
            expected_nonnegative,
            rel_tol=_FLOAT_REL_TOLERANCE,
            abs_tol=_FLOAT_ABS_TOLERANCE,
        ):
            raise ValueError(
                "edge_full_spread_frac_nonnegative must equal max(0, edge_full_spread_frac_signed)"
            )
        if self.negative_edge_estimate != (self.edge_full_spread_frac_signed < 0.0):
            raise ValueError("negative_edge_estimate must match signed EDGE estimate")
        expected_half_spread = self.reference_price * expected_nonnegative / 2.0
        if not math.isclose(
            self.half_spread_price,
            expected_half_spread,
            rel_tol=_FLOAT_REL_TOLERANCE,
            abs_tol=_FLOAT_ABS_TOLERANCE,
        ):
            raise ValueError(
                "half_spread_price must equal "
                "reference_price * edge_full_spread_frac_nonnegative / 2"
            )
        if self.edge_window_start_utc >= self.edge_window_end_utc:
            raise ValueError("edge_window_start_utc must be before edge_window_end_utc")
        if self.edge_window_end_utc > self.target_observed_at_utc:
            raise ValueError("edge_window_end_utc must not be after target_observed_at_utc")
        if self.feature_observed_at_utc > self.target_observed_at_utc:
            raise ValueError("feature_observed_at_utc must not be after target_observed_at_utc")
        if self.target_observed_at_utc >= self.fill_timestamp_utc:
            raise ValueError("target_observed_at_utc must be before fill_timestamp_utc")
        if self.feature_observed_at_utc >= self.fill_timestamp_utc:
            raise ValueError("feature_observed_at_utc must be before fill_timestamp_utc")
        if self.edge_window_end_utc >= self.fill_timestamp_utc:
            raise ValueError("EDGE source window must end before fill_timestamp_utc")
        return self


class SpreadCalibrationSymbolSummary(BaseModel):
    """Per-symbol EDGE panel diagnostics."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: NonEmptyStr
    estimator_timeframe: Timeframe
    source_fingerprint: NonEmptyStr
    input_bar_count: int = Field(ge=0)
    eligible_window_count: int = Field(ge=0)
    usable_row_count: int = Field(ge=0)
    invalid_window_count: int = Field(ge=0)
    negative_estimate_count: int = Field(ge=0)
    invalid_reason_counts: dict[NonEmptyStr, int] = Field(default_factory=dict)
    positive_volume_row_count: int = Field(ge=0)
    zero_volume_row_count: int = Field(ge=0)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def invalid_rate(self) -> float:
        """Return invalid EDGE windows divided by eligible windows."""

        if self.eligible_window_count == 0:
            return 0.0
        return self.invalid_window_count / self.eligible_window_count

    @computed_field  # type: ignore[prop-decorator]
    @property
    def negative_rate(self) -> float:
        """Return signed negative EDGE estimates divided by usable rows."""

        if self.usable_row_count == 0:
            return 0.0
        return self.negative_estimate_count / self.usable_row_count

    @computed_field  # type: ignore[prop-decorator]
    @property
    def positive_volume_coverage(self) -> float:
        """Return source rows with positive volume divided by all input rows."""

        if self.input_bar_count == 0:
            return 0.0
        return self.positive_volume_row_count / self.input_bar_count

    @model_validator(mode="after")
    def _validate_count_consistency(self) -> SpreadCalibrationSymbolSummary:
        reason_total = sum(self.invalid_reason_counts.values())
        if any(count < 0 for count in self.invalid_reason_counts.values()):
            raise ValueError("invalid reason counts must be non-negative")
        if reason_total != self.invalid_window_count:
            raise ValueError("invalid_window_count must match invalid_reason_counts total")
        if self.negative_estimate_count > self.usable_row_count:
            raise ValueError("negative_estimate_count cannot exceed usable_row_count")
        if self.usable_row_count + self.invalid_window_count != self.eligible_window_count:
            raise ValueError("usable plus invalid window counts must equal eligible windows")
        if self.positive_volume_row_count + self.zero_volume_row_count != self.input_bar_count:
            raise ValueError("positive plus zero volume row counts must equal input rows")
        return self


class SpreadCalibrationResult(BaseModel):
    """Phase-1 offline spread calibration output."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    calibration_id: NonEmptyStr
    dataset_id: NonEmptyStr
    estimator_timeframe: Timeframe
    edge_window_bars: int = Field(ge=3)
    volatility_short_window_bars: int = Field(
        default=_PANEL_DEFAULTS.volatility_short_window_bars,
        gt=0,
    )
    volatility_baseline_window_bars: int = Field(
        default=_PANEL_DEFAULTS.volatility_baseline_window_bars,
        gt=0,
    )
    volatility_floor_price: Decimal = Field(default=_PANEL_DEFAULTS.volatility_floor_price, gt=0)
    volume_baseline_window_bars: int = Field(
        default=_PANEL_DEFAULTS.volume_baseline_window_bars,
        gt=0,
    )
    volume_floor: Decimal = Field(default=_PANEL_DEFAULTS.volume_floor, gt=0)
    session_buckets: tuple[UtcSessionBucketRule, ...] = Field(
        default=_PANEL_DEFAULTS.session_buckets,
        min_length=1,
    )
    price_basis: PriceBasis
    panel_rows: tuple[SpreadCalibrationPanelRow, ...] = Field(default_factory=tuple)
    symbol_summaries: tuple[SpreadCalibrationSymbolSummary, ...] = Field(default_factory=tuple)
    source_fingerprints: dict[NonEmptyStr, NonEmptyStr] = Field(default_factory=dict)
    requested_by: NonEmptyStr
    correlation_id: NonEmptyStr | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def row_count(self) -> int:
        """Return the total number of usable panel rows."""

        return len(self.panel_rows)

    @model_validator(mode="after")
    def _validate_result_has_rows(self) -> SpreadCalibrationResult:
        if not self.panel_rows:
            raise ValueError("spread calibration result requires at least one panel row")
        return self

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

    @field_validator("estimator_timeframe")
    @classmethod
    def _normalize_estimator_timeframe(cls, value: str) -> str:
        return normalize_timeframe(value)


class SpreadCalibrationPublicationCommand(BaseModel):
    """Request to fit Phase-2 spread parameters and publish generated YAML."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    calibration_result: SpreadCalibrationResult
    target_timeframe: Timeframe
    output_root: Path = _PUBLICATION_DEFAULTS.output_root
    base_execution_costs_path: Path | None = None
    symbol_map_path: Path | None = None
    train_fraction: float = Field(default=_PUBLICATION_DEFAULTS.train_fraction, gt=0.0, lt=1.0)
    minimum_train_rows_per_symbol: int = Field(
        default=_PUBLICATION_DEFAULTS.minimum_train_rows_per_symbol,
        ge=1,
    )
    minimum_holdout_rows_per_symbol: int = Field(
        default=_PUBLICATION_DEFAULTS.minimum_holdout_rows_per_symbol,
        ge=1,
    )
    max_half_spread_train_quantile: float = Field(
        default=_PUBLICATION_DEFAULTS.max_half_spread_train_quantile,
        gt=0.0,
        le=1.0,
    )
    min_half_spread_tick_fraction: Decimal = Field(
        default=_PUBLICATION_DEFAULTS.min_half_spread_tick_fraction,
        ge=Decimal("0.5"),
    )
    allow_liquidity_weight: bool = _PUBLICATION_DEFAULTS.allow_liquidity_weight
    allow_cross_timeframe_dynamic_weights: bool = (
        _PUBLICATION_DEFAULTS.allow_cross_timeframe_dynamic_weights
    )
    liquidity_coverage_threshold: float = Field(
        default=_PUBLICATION_DEFAULTS.liquidity_coverage_threshold,
        gt=0.0,
        le=1.0,
    )
    liquidity_eligibility_policy: CalibrationLiquidityEligibilityPolicy = Field(
        default_factory=CalibrationLiquidityEligibilityPolicy,
    )
    volume_semantics: CalibrationVolumeSemantics = _PUBLICATION_DEFAULTS.volume_semantics
    allow_mixed_asset_classes: bool = _PUBLICATION_DEFAULTS.allow_mixed_asset_classes
    fit_tolerance: float = Field(default=_PUBLICATION_DEFAULTS.fit_tolerance, gt=0.0)
    max_fit_iterations: int = Field(default=_PUBLICATION_DEFAULTS.max_fit_iterations, ge=1)
    owner: NonEmptyStr = "offline_spread_calibration"
    description: NonEmptyStr | None = None

    @field_validator(
        "train_fraction",
        "max_half_spread_train_quantile",
        "liquidity_coverage_threshold",
        "fit_tolerance",
    )
    @classmethod
    def _ensure_finite_ratio(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("publication ratios must be finite")
        return value

    @field_validator("min_half_spread_tick_fraction", mode="before")
    @classmethod
    def _coerce_decimal(cls, value: Decimal | float | int | str) -> Decimal:
        return Decimal(str(value))

    @field_validator("min_half_spread_tick_fraction")
    @classmethod
    def _ensure_finite_positive_decimal(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value < Decimal("0.5"):
            raise ValueError("min_half_spread_tick_fraction must be finite and at least 0.5")
        return value

    @field_validator("target_timeframe")
    @classmethod
    def _normalize_target_timeframe(cls, value: str) -> str:
        return normalize_timeframe(value)


class PublishedCalibrationSymbol(BaseModel):
    """Fitted and published parameters for one symbol."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: NonEmptyStr
    base_half_spread_price: Decimal
    min_half_spread_price: Decimal
    max_half_spread_price: Decimal
    volatility_weight: Decimal
    liquidity_weight: Decimal
    train_row_count: int = Field(ge=0)
    holdout_row_count: int = Field(ge=0)
    train_max_clip_rate: float = Field(ge=0.0, le=1.0)
    holdout_max_clip_rate: float = Field(ge=0.0, le=1.0)


class SpreadCalibrationPublicationResult(BaseModel):
    """Persisted artifact locations and canonical hash for a Phase-2 publication."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    calibration_id: NonEmptyStr
    profile_id: NonEmptyStr
    estimator_timeframe: Timeframe
    target_timeframe: Timeframe
    output_dir: Path
    execution_costs_path: Path
    calibration_report_path: Path
    calibration_panel_path: Path
    diagnostic_artifact_paths: tuple[Path, ...] = Field(default_factory=tuple)
    execution_costs_config_hash: NonEmptyStr
    published_symbols: tuple[PublishedCalibrationSymbol, ...]
    train_row_count: int = Field(ge=0)
    holdout_row_count: int = Field(ge=0)
    purged_row_count: int = Field(ge=0)


__all__ = [
    "PriceBasis",
    "PublishedCalibrationSymbol",
    "SpreadCalibrationCommand",
    "SpreadCalibrationPanelRow",
    "SpreadCalibrationPublicationCommand",
    "SpreadCalibrationPublicationResult",
    "SpreadCalibrationResult",
    "SpreadCalibrationSymbolSummary",
]
