"""Order-intent contracts."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator

from backtest_engine.core.enums import OrderSide, OrderType
from backtest_engine.core.ids import StrategyId
from backtest_engine.core.types import Symbol


class OrderIntent(BaseModel):
    """A normalized order request emitted by runtime wrappers."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    strategy_id: StrategyId
    symbol: Symbol
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None

    @field_validator("quantity", "limit_price", "stop_price", mode="before")
    @classmethod
    def _coerce_decimal(cls, value: Decimal | float | int | str | None) -> Decimal | None:
        if value is None:
            return None
        return Decimal(str(value))


__all__ = ["OrderIntent"]
