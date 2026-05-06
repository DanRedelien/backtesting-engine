"""Validated parameters for the channel breakout cartridge."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backtest_engine.core.ids import StrategyId
from backtest_engine.core.types import Symbol


TradeDirection = Literal["both", "long", "short"]


class ChannelBreakoutLongParameters(BaseModel):
    """Immutable channel-breakout parameters derived from one strategy spec."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    strategy_id: StrategyId
    symbol: Symbol
    trade_size: float = Field(gt=0.0, default=1.0)
    length: int = Field(ge=1, default=50)
    ema_period: int = Field(ge=1, default=200)
    entry_buffer_ticks: int = Field(ge=1, default=1)
    trade_direction: TradeDirection = "long"
    use_shock_filter: bool = True
    shock_atr_window: int = Field(ge=1, default=14)
    shock_max_gap_atr: float = Field(gt=0.0, default=1.25)
    shock_max_range_atr: float = Field(gt=0.0, default=3.0)
    shock_max_close_change_atr: float = Field(gt=0.0, default=2.0)

    @field_validator(
        "trade_size",
        "length",
        "ema_period",
        "entry_buffer_ticks",
        "shock_atr_window",
        "shock_max_gap_atr",
        "shock_max_range_atr",
        "shock_max_close_change_atr",
        mode="before",
    )
    @classmethod
    def _reject_bool_numeric_parameters(cls, value: object) -> object:
        if isinstance(value, bool | str | Decimal) or _is_numpy_scalar(value):
            raise ValueError("numeric strategy parameters must be built-in numbers")
        return value


def _is_numpy_scalar(value: object) -> bool:
    return type(value).__module__.startswith("numpy")


__all__ = ["ChannelBreakoutLongParameters", "TradeDirection"]
