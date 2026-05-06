"""Validated parameters for the SMA pullback cartridge."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backtest_engine.core.ids import StrategyId
from backtest_engine.core.types import Symbol


TradeDirection = Literal["both", "long", "short"]


class SmaPullbackParameters(BaseModel):
    """Immutable SMA pullback parameters derived from one strategy spec."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    strategy_id: StrategyId
    symbol: Symbol
    trade_size: float = Field(gt=0.0, default=1.0)
    fast_sma_window: int = Field(ge=1, default=50)
    slow_sma_window: int = Field(ge=2, default=200)
    atr_window: int = Field(ge=1, default=14)
    atr_sl_mult: float = Field(gt=0.0, default=2.0)
    rr_ratio: float = Field(gt=0.0, default=3.0)
    trade_direction: TradeDirection = "both"

    @field_validator(
        "trade_size",
        "fast_sma_window",
        "slow_sma_window",
        "atr_window",
        "atr_sl_mult",
        "rr_ratio",
        mode="before",
    )
    @classmethod
    def _reject_bool_numeric_parameters(cls, value: object) -> object:
        if isinstance(value, bool | str | Decimal) or _is_numpy_scalar(value):
            raise ValueError("numeric strategy parameters must be built-in numbers")
        return value

    @model_validator(mode="after")
    def _validate_windows(self) -> "SmaPullbackParameters":
        if self.fast_sma_window >= self.slow_sma_window:
            raise ValueError("fast_sma_window must be less than slow_sma_window")
        return self


def _is_numpy_scalar(value: object) -> bool:
    return type(value).__module__.startswith("numpy")


__all__ = ["SmaPullbackParameters", "TradeDirection"]
