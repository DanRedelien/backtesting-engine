"""Position truth contracts."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator

from backtest_engine.core.types import Symbol


class PositionSnapshot(BaseModel):
    """A normalized position snapshot owned by execution truth."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: Symbol
    quantity: Decimal
    average_price: Decimal
    realized_pnl: Decimal = Decimal("0")
    unrealized_pnl: Decimal = Decimal("0")

    @field_validator(
        "quantity",
        "average_price",
        "realized_pnl",
        "unrealized_pnl",
        mode="before",
    )
    @classmethod
    def _coerce_decimal(cls, value: Decimal | float | int | str) -> Decimal:
        return Decimal(str(value))


__all__ = ["PositionSnapshot"]
