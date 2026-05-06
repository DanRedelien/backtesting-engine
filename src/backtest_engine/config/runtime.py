"""Runtime settings and canonical run-spec contracts."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from backtest_engine.config.execution_costs import DEFAULT_EXECUTION_COST_PROFILE_ID
from backtest_engine.core.annualization import resolve_annualization_factor
from backtest_engine.core.enums import RunKind, RuntimeBoundary, WarmupPolicy
from backtest_engine.core.ids import build_run_id, stable_hash
from backtest_engine.core.money import Money
from backtest_engine.core.time import ensure_utc
from backtest_engine.core.types import NonEmptyStr
from backtest_engine.domain.market.datasets import DatasetSpec
from backtest_engine.domain.strategy.specifications import PortfolioStrategySpec


class ExecutionWindow(BaseModel):
    """The UTC execution window for a deterministic run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    start_utc: datetime
    end_utc: datetime

    @field_validator("start_utc", "end_utc")
    @classmethod
    def _ensure_utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)

    @model_validator(mode="after")
    def _validate_window(self) -> "ExecutionWindow":
        if self.start_utc >= self.end_utc:
            raise ValueError("execution window start_utc must be earlier than end_utc")
        return self


class RuntimeSettings(BaseModel):
    """Repository-level runtime paths and semantic defaults."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    runtime_root: Path = Path("var/runtime")
    nautilus_root: Path = Path("var/runtime/nautilus")
    results_root: Path = Path("results")
    semantic_policy_version: NonEmptyStr = "v1"
    default_annualization_policy: NonEmptyStr = "252d"

    @field_validator("default_annualization_policy")
    @classmethod
    def _validate_default_annualization_policy(cls, value: str) -> str:
        resolve_annualization_factor(value)
        return value


class PortfolioExecutionPolicy(BaseModel):
    """Execution-defining portfolio policy owned by the run spec."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rebalance_cadence: NonEmptyStr = "run_open"
    target_portfolio_vol_frac: float = Field(gt=0.0, le=1.0, default=1.0)
    vol_lookback_bars: int = Field(ge=2, default=20)
    max_portfolio_leverage: float = Field(gt=0.0, default=1.0)
    estimator_version: NonEmptyStr = "rolling_sample_v1"
    annualization_policy: NonEmptyStr = "252d"
    warmup_policy: WarmupPolicy = WarmupPolicy.HOLD_FLAT_UNTIL_LOOKBACK

    @field_validator("annualization_policy")
    @classmethod
    def _validate_annualization_policy(cls, value: str) -> str:
        resolve_annualization_factor(value)
        return value


class ExecutionCostProfileRef(BaseModel):
    """Declarative reference to an execution-cost assumption profile."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    profile_id: NonEmptyStr
    config_content_hash: str | None = None

    @field_validator("profile_id")
    @classmethod
    def _validate_supported_profile_id(cls, value: str) -> str:
        if value != DEFAULT_EXECUTION_COST_PROFILE_ID:
            raise ValueError(
                "unsupported execution-cost profile_id "
                f"{value!r}; supported profile_id is {DEFAULT_EXECUTION_COST_PROFILE_ID!r}",
            )
        return value

    @field_validator("config_content_hash")
    @classmethod
    def _validate_config_content_hash(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if len(normalized) != 64 or any(
            character not in "0123456789abcdef" for character in normalized
        ):
            raise ValueError(
                "config_content_hash must be a 64-character lowercase SHA-256 hex digest"
            )
        return normalized


class ExecutionVenueOverrides(BaseModel):
    """Optional declarative venue defaults to apply in a later compiler phase."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    oms_type: Literal["NETTING", "HEDGING"] | None = None
    account_type: Literal["CASH", "MARGIN", "BETTING"] | None = None
    book_type: Literal["L1_MBP", "L2_MBP", "L3_MBO"] | None = None

    @model_validator(mode="after")
    def _require_at_least_one_override(self) -> "ExecutionVenueOverrides":
        if self.oms_type is None and self.account_type is None and self.book_type is None:
            raise ValueError("venue_overrides must set at least one override")
        return self


class BacktestExecutionPolicy(BaseModel):
    """Declarative execution-realism intent captured by the canonical run spec."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    execution_costs: ExecutionCostProfileRef
    venue_overrides: ExecutionVenueOverrides | None = None


class BacktestRunSpec(BaseModel):
    """The canonical execution contract for all rewrite workflows."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_kind: RunKind
    runtime_boundary: RuntimeBoundary = RuntimeBoundary.NAUTILUS
    execution_window: ExecutionWindow
    dataset: DatasetSpec
    strategies: tuple[PortfolioStrategySpec, ...] = Field(default_factory=tuple)
    capital_base: Money
    portfolio_policy: PortfolioExecutionPolicy | None = None
    execution_policy: BacktestExecutionPolicy | None = None
    semantic_policy_version: NonEmptyStr = "v1"
    tags: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _validate_shape(self) -> "BacktestRunSpec":
        if not self.strategies:
            raise ValueError("BacktestRunSpec requires at least one strategy")
        if self.run_kind is RunKind.SINGLE and len(self.strategies) != 1:
            raise ValueError("single runs require exactly one strategy")
        if self.run_kind is RunKind.PORTFOLIO and self.portfolio_policy is None:
            object.__setattr__(self, "portfolio_policy", PortfolioExecutionPolicy())
        if self.run_kind is not RunKind.PORTFOLIO and self.portfolio_policy is not None:
            raise ValueError("portfolio_policy is only valid for portfolio runs")
        dataset_symbols = set(self.dataset.symbol_universe)
        for strategy_spec in self.strategies:
            leg_symbols = tuple(leg.symbol for leg in strategy_spec.legs)
            missing_symbols = sorted(set(leg_symbols).difference(dataset_symbols))
            if missing_symbols:
                raise ValueError(
                    "strategy legs must exist in dataset symbol_universe: "
                    + ",".join(missing_symbols)
                )
        if self.run_kind is RunKind.PORTFOLIO:
            total_weight = float(sum(strategy.weight_frac for strategy in self.strategies))
            if abs(total_weight - 1.0) > 1e-6:
                raise ValueError("portfolio runs require target sleeve weights to sum to 1.0")
            if self.portfolio_policy is None:
                raise ValueError("portfolio_policy is required for portfolio runs")
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def content_hash(self) -> str:
        exclude_fields = {"content_hash", "run_id"}
        if self.execution_policy is None:
            exclude_fields.add("execution_policy")
        payload = self.model_dump(mode="json", exclude=exclude_fields)
        return stable_hash(payload)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def run_id(self) -> str:
        return build_run_id(self.content_hash)


__all__ = [
    "BacktestExecutionPolicy",
    "BacktestRunSpec",
    "ExecutionCostProfileRef",
    "ExecutionVenueOverrides",
    "ExecutionWindow",
    "PortfolioExecutionPolicy",
    "RuntimeSettings",
]
