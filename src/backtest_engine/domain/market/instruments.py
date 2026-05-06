"""Instrument-domain contracts."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator

from backtest_engine.core.types import NonEmptyStr, Symbol


class InstrumentSpec(BaseModel):
    """A normalized instrument definition used by the rewrite."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: Symbol
    venue: NonEmptyStr
    instrument_type: NonEmptyStr
    tick_size: Decimal
    lot_size: Decimal

    @field_validator("tick_size", "lot_size", mode="before")
    @classmethod
    def _coerce_decimal(cls, value: Decimal | float | int | str) -> Decimal:
        return Decimal(str(value))


__all__ = ["InstrumentSpec"]
