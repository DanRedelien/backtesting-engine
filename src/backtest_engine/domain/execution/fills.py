"""Fill-event truth contracts."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator

from backtest_engine.core.enums import OrderSide
from backtest_engine.core.ids import StrategyId
from backtest_engine.core.time import ensure_utc
from backtest_engine.core.types import Symbol


class FillEvent(BaseModel):
    """A normalized fill event projected from runtime truth."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    strategy_id: StrategyId
    symbol: Symbol
    side: OrderSide
    quantity: Decimal
    price: Decimal
    filled_at_utc: datetime

    @field_validator("quantity", "price", mode="before")
    @classmethod
    def _coerce_decimal(cls, value: Decimal | float | int | str) -> Decimal:
        return Decimal(str(value))

    @field_validator("filled_at_utc")
    @classmethod
    def _ensure_utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)


__all__ = ["FillEvent"]
