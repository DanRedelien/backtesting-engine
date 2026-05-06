"""Validated parameters for the weighted spread statarb cartridge."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backtest_engine.core.ids import StrategyId
from backtest_engine.core.types import Symbol


TradeDirection = Literal["both", "long_spread_only", "short_spread_only"]


class StatarbWeightedSpreadParameters(BaseModel):
    """Immutable weighted-spread statarb parameters derived from one strategy spec."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    strategy_id: StrategyId
    leg_symbols: tuple[Symbol, ...] = Field(default_factory=tuple)
    trade_sizes: tuple[float, ...] = Field(default_factory=tuple)
    spread_weights: tuple[float, ...] = Field(default_factory=tuple)
    zscore_window: int = Field(ge=2)
    entry_zscore: float = Field(gt=0.0)
    exit_zscore: float = Field(ge=0.0)
    trade_direction: TradeDirection = "both"

    @field_validator("zscore_window", "entry_zscore", "exit_zscore", mode="before")
    @classmethod
    def _reject_bool_numeric_parameters(cls, value: object) -> object:
        if isinstance(value, bool | str | Decimal) or _is_numpy_scalar(value):
            raise ValueError("numeric strategy parameters must be built-in numbers")
        return value

    @field_validator("trade_sizes", "spread_weights", mode="before")
    @classmethod
    def _reject_bool_numeric_sequences(cls, value: object) -> object:
        if isinstance(value, bool | str | Decimal) or _is_numpy_scalar(value):
            raise ValueError("numeric strategy parameter sequences must contain built-in numbers")
        if isinstance(value, list | tuple) and any(_is_forbidden_numeric_item(item) for item in value):
            raise ValueError("numeric strategy parameter sequences must contain built-in numbers")
        return value

    @model_validator(mode="after")
    def _validate_shape(self) -> "StatarbWeightedSpreadParameters":
        leg_count = len(self.leg_symbols)
        if leg_count < 2:
            raise ValueError("weighted spread statarb requires at least two legs")
        if len(self.trade_sizes) != leg_count:
            raise ValueError("trade_sizes length must match leg_symbols length")
        if len(self.spread_weights) != leg_count:
            raise ValueError("spread_weights length must match leg_symbols length")
        if any(size <= 0.0 for size in self.trade_sizes):
            raise ValueError("trade_sizes must be positive")
        if self.exit_zscore >= self.entry_zscore:
            raise ValueError("exit_zscore must be less than entry_zscore")
        if all(weight == 0.0 for weight in self.spread_weights):
            raise ValueError("spread_weights must not all be zero")
        return self


def _is_forbidden_numeric_item(value: object) -> bool:
    return isinstance(value, bool | str | Decimal) or _is_numpy_scalar(value)


def _is_numpy_scalar(value: object) -> bool:
    return type(value).__module__.startswith("numpy")


__all__ = ["StatarbWeightedSpreadParameters", "TradeDirection"]
