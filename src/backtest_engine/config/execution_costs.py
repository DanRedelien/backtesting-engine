"""Validated execution-cost profile configuration."""

from __future__ import annotations

from datetime import time
from decimal import Decimal
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backtest_engine.core.ids import stable_hash
from backtest_engine.core.types import NonEmptyStr
from backtest_engine.domain.execution.commissions import (
    ExecutionCostProfilePatch,
    ResolvedExecutionCostProfile,
    resolve_execution_cost_profile,
    resolve_execution_cost_profiles,
)
from backtest_engine.domain.execution.instrument_metadata import (
    ExecutionAssetClass,
    ExecutionInstrumentMetadata,
)


DEFAULT_EXECUTION_COSTS_PATH = Path(__file__).resolve().parent / "execution_costs.yaml"
DEFAULT_EXECUTION_COST_PROFILE_ID = "default_execution_costs"


class ExecutionCostsConfig(BaseModel):
    """Config-layer execution-cost assumptions loaded from YAML."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = Field(ge=1)
    profile_id: NonEmptyStr
    owner: NonEmptyStr
    description: NonEmptyStr
    asset_class_defaults: dict[ExecutionAssetClass, ExecutionCostProfilePatch]
    symbol_overrides: dict[str, ExecutionCostProfilePatch] = Field(default_factory=dict)
    dynamic_spread_runtime: "DynamicSpreadRuntimeConfig | None" = None

    def resolve_profile(
        self,
        metadata: ExecutionInstrumentMetadata,
    ) -> ResolvedExecutionCostProfile:
        """Resolve one instrument's final commission, spread, and slippage profile."""

        default = self.asset_class_defaults.get(metadata.asset_class)
        if default is None:
            raise ValueError(
                f"missing asset-class execution-cost default for {metadata.asset_class}"
            )
        override = self._symbol_overrides_by_normalized_symbol().get(
            metadata.symbol.strip().upper()
        )
        return resolve_execution_cost_profile(metadata, default, override)

    def resolve_profiles(
        self,
        metadata_by_leg: tuple[ExecutionInstrumentMetadata, ...],
    ) -> tuple[ResolvedExecutionCostProfile, ...]:
        """Resolve final commission, spread, and slippage profiles per symbol/per leg."""

        return resolve_execution_cost_profiles(
            metadata_by_leg,
            self.asset_class_defaults,
            self._symbol_overrides_by_normalized_symbol(),
        )

    def _symbol_overrides_by_normalized_symbol(self) -> dict[str, ExecutionCostProfilePatch]:
        return {symbol.strip().upper(): patch for symbol, patch in self.symbol_overrides.items()}

    def resolve_dynamic_spread_runtime(
        self,
        metadata: ExecutionInstrumentMetadata,
    ) -> "DynamicSpreadRuntimeProfile | None":
        """Resolve optional dynamic spread feature settings for one instrument."""

        if self.dynamic_spread_runtime is None:
            return None
        return self.dynamic_spread_runtime.resolve_profile(metadata)


class UtcSessionBucketRule(BaseModel):
    """Explicit UTC time bucket used by dynamic spread feature generation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    session_bucket_id: NonEmptyStr
    weekdays: tuple[int, ...] = Field(min_length=1)
    start_time_utc: time
    end_time_utc: time

    @field_validator("start_time_utc", "end_time_utc")
    @classmethod
    def _validate_naive_utc_time(cls, value: time) -> time:
        if value.utcoffset() is not None:
            raise ValueError("UTC session bucket times must be naive HH:MM:SS values")
        return value

    @field_validator("weekdays")
    @classmethod
    def _validate_weekdays(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        invalid = sorted(day for day in value if day < 0 or day > 6)
        if invalid:
            raise ValueError(
                "UTC session bucket weekdays must use integers 0=Monday through 6=Sunday"
            )
        if len(value) != len(set(value)):
            raise ValueError("UTC session bucket weekdays must be unique")
        return value


class DynamicSpreadRuntimeProfile(BaseModel):
    """Runtime feature-generation settings for log-linear dynamic spreads."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    volatility_short_window_bars: int = Field(gt=0)
    volatility_baseline_window_bars: int = Field(gt=0)
    volatility_floor_price: Decimal = Field(gt=0)
    volatility_signal_method: Literal["true_range_atr"]
    volume_baseline_window_bars: int = Field(gt=0)
    volume_floor: Decimal = Field(gt=0)
    dynamic_order_types: tuple[Literal["market"], ...] = Field(min_length=1)
    session_buckets: tuple[UtcSessionBucketRule, ...] = Field(min_length=1)

    @field_validator("volatility_floor_price", "volume_floor", mode="before")
    @classmethod
    def _coerce_decimal(cls, value: Decimal | float | int | str) -> Decimal:
        return Decimal(str(value))

    @field_validator("dynamic_order_types")
    @classmethod
    def _validate_dynamic_order_types(
        cls,
        value: tuple[Literal["market"], ...],
    ) -> tuple[Literal["market"], ...]:
        if value != ("market",):
            raise ValueError(
                "dynamic spread runtime dynamic_order_types must be exactly ('market',)"
            )
        return value

    @field_validator("session_buckets")
    @classmethod
    def _validate_unique_bucket_ids(
        cls,
        value: tuple[UtcSessionBucketRule, ...],
    ) -> tuple[UtcSessionBucketRule, ...]:
        bucket_ids = [bucket.session_bucket_id for bucket in value]
        if len(bucket_ids) != len(set(bucket_ids)):
            raise ValueError("dynamic spread runtime session_bucket_id values must be unique")
        return value

    @property
    def required_history_bars(self) -> int:
        """Return the minimum number of prior bars required before a feature row."""

        volatility_history_bars = (
            max(
                self.volatility_short_window_bars,
                self.volatility_baseline_window_bars,
            )
            + 1
        )
        return max(
            volatility_history_bars,
            self.volume_baseline_window_bars,
            1,
        )


class DynamicSpreadRuntimeConfig(BaseModel):
    """Config-layer dynamic spread feature-generation settings."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    asset_class_defaults: dict[ExecutionAssetClass, DynamicSpreadRuntimeProfile]
    symbol_overrides: dict[str, DynamicSpreadRuntimeProfile] = Field(default_factory=dict)

    def resolve_profile(
        self,
        metadata: ExecutionInstrumentMetadata,
    ) -> DynamicSpreadRuntimeProfile | None:
        """Resolve runtime settings by symbol override, then asset-class default."""

        normalized_symbol = metadata.symbol.strip().upper()
        symbol_overrides = {
            symbol.strip().upper(): profile for symbol, profile in self.symbol_overrides.items()
        }
        override = symbol_overrides.get(normalized_symbol)
        if override is not None:
            return override
        return self.asset_class_defaults.get(metadata.asset_class)


def default_execution_costs_path() -> Path:
    """Return the bundled execution-cost profile path."""

    return DEFAULT_EXECUTION_COSTS_PATH


def load_execution_costs(path: Path | str | None = None) -> ExecutionCostsConfig:
    """Load and validate execution-cost assumptions from YAML."""

    resolved_path = Path(path) if path is not None else default_execution_costs_path()
    raw = yaml.safe_load(resolved_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"expected a mapping YAML object in {resolved_path}")
    return ExecutionCostsConfig.model_validate(raw)


def execution_costs_config_hash(config: ExecutionCostsConfig) -> str:
    """Return the canonical hash of a validated execution-cost config."""

    return stable_hash(config.model_dump(mode="json"))


__all__ = [
    "DEFAULT_EXECUTION_COST_PROFILE_ID",
    "DynamicSpreadRuntimeConfig",
    "DynamicSpreadRuntimeProfile",
    "ExecutionCostsConfig",
    "UtcSessionBucketRule",
    "default_execution_costs_path",
    "execution_costs_config_hash",
    "load_execution_costs",
]
