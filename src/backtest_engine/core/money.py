"""Money primitives with explicit currency metadata."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator

from backtest_engine.core.types import CurrencyCode


class Money(BaseModel):
    """An immutable money value used at stable boundaries."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    amount: Decimal
    currency: CurrencyCode

    @field_validator("amount", mode="before")
    @classmethod
    def _coerce_decimal(cls, value: Decimal | float | int | str) -> Decimal:
        return Decimal(str(value))


__all__ = ["Money"]
