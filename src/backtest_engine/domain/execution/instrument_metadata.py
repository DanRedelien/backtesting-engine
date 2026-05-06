"""Instrument metadata contracts used by execution-cost calculations."""

from __future__ import annotations

from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backtest_engine.core.types import CurrencyCode, Symbol


class ExecutionInstrumentType(str, Enum):
    """Instrument families understood by execution-cost contracts."""

    CURRENCY_PAIR = "CURRENCY_PAIR"
    CFD = "CFD"
    FUTURES = "FUTURES"
    EQUITY = "EQUITY"
    SYNTHETIC = "SYNTHETIC"


class ExecutionAssetClass(str, Enum):
    """Asset classes used to resolve future execution-cost assumptions."""

    FX = "FX"
    INDEX = "INDEX"
    COMMODITY = "COMMODITY"
    EQUITY = "EQUITY"
    CRYPTOCURRENCY = "CRYPTOCURRENCY"


class ExecutionInstrumentMetadata(BaseModel):
    """Framework-agnostic instrument metadata required by cost policies."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: Symbol
    instrument_type: ExecutionInstrumentType
    asset_class: ExecutionAssetClass
    quote_currency: CurrencyCode
    tick_size: Decimal
    point_size: Decimal
    lot_size: Decimal
    multiplier: Decimal
    price_precision: int = Field(ge=0)

    @field_validator("tick_size", "point_size", "lot_size", "multiplier", mode="before")
    @classmethod
    def _coerce_decimal(cls, value: Decimal | float | int | str) -> Decimal:
        return Decimal(str(value))

    @field_validator("tick_size", "point_size", "lot_size", "multiplier")
    @classmethod
    def _require_positive_decimal(cls, value: Decimal) -> Decimal:
        if value <= Decimal("0"):
            raise ValueError("instrument metadata decimal fields must be positive")
        return value


__all__ = [
    "ExecutionAssetClass",
    "ExecutionInstrumentMetadata",
    "ExecutionInstrumentType",
]
