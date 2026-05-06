"""Typed loader for canonical Nautilus symbol metadata."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


DEFAULT_NAUTILUS_SYMBOL_MAP_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "nautilus_symbol_map.yaml"
)


class SymbolMapping(BaseModel):
    """One canonical mapping from a repository symbol family to Nautilus."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mt5_symbol: str
    provider_symbol: str | None = None
    aliases: tuple[str, ...] = ()
    nautilus_symbol: str
    nautilus_instrument_id: str
    instrument_type: Literal["CURRENCY_PAIR", "CFD", "FUTURES", "EQUITY", "SYNTHETIC"]
    venue: str
    asset_class: Literal["FX", "INDEX", "COMMODITY", "EQUITY", "CRYPTOCURRENCY"] | None = None
    base_currency: str | None = None
    quote_currency: str
    price_precision: int
    size_precision: int
    tick_size: Decimal
    point_size: Decimal
    size_increment: Decimal
    lot_size: Decimal
    multiplier: Decimal | None = None
    underlying: str | None = None
    exchange: str | None = None
    activation_time_utc: datetime | None = None
    expiration_time_utc: datetime | None = None
    margin_init: Decimal | None = None
    margin_maint: Decimal | None = None
    maker_fee: Decimal | None = None
    taker_fee: Decimal | None = None

    @model_validator(mode="after")
    def _validate_contract(self) -> "SymbolMapping":
        if self.instrument_type == "CURRENCY_PAIR" and self.base_currency is None:
            raise ValueError("currency pairs require base_currency")
        if self.instrument_type in {"CFD", "FUTURES"} and self.asset_class is None:
            raise ValueError(f"{self.instrument_type} mappings require asset_class")
        if self.instrument_type == "FUTURES" and self.multiplier is None:
            raise ValueError("futures mappings require multiplier")
        return self

    def all_symbols(self) -> set[str]:
        values = {self.mt5_symbol, self.provider_symbol, *self.aliases}
        return {value.strip().upper() for value in values if value and value.strip()}

    def matches(self, raw_symbol: str) -> bool:
        return raw_symbol.strip().upper() in self.all_symbols()

    def metadata_dict(self) -> dict[str, Any]:
        """Return JSON-safe instrument metadata for manifests."""

        return {
            "canonical_symbol": self.mt5_symbol,
            "provider_symbol": self.resolved_provider_symbol,
            "instrument_type": self.instrument_type,
            "asset_class": self.asset_class,
            "base_currency": self.base_currency,
            "quote_currency": self.quote_currency,
            "price_precision": self.price_precision,
            "size_precision": self.size_precision,
            "tick_size": float(self.tick_size),
            "point_size": float(self.point_size),
            "size_increment": float(self.size_increment),
            "lot_size": float(self.lot_size),
            "multiplier": float(self.multiplier) if self.multiplier is not None else None,
            "venue": self.venue,
            "underlying": self.underlying,
            "exchange": self.exchange,
            "activation_time_utc": (
                self.activation_time_utc.isoformat().replace("+00:00", "Z")
                if self.activation_time_utc is not None
                else None
            ),
            "expiration_time_utc": (
                self.expiration_time_utc.isoformat().replace("+00:00", "Z")
                if self.expiration_time_utc is not None
                else None
            ),
            "margin_init": float(self.margin_init) if self.margin_init is not None else None,
            "margin_maint": float(self.margin_maint) if self.margin_maint is not None else None,
            "maker_fee": float(self.maker_fee) if self.maker_fee is not None else None,
            "taker_fee": float(self.taker_fee) if self.taker_fee is not None else None,
        }

    @property
    def resolved_provider_symbol(self) -> str:
        return self.provider_symbol or self.mt5_symbol


class SymbolMap(BaseModel):
    """Typed representation of the canonical symbol-map YAML."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int
    owner: str
    description: str
    defaults: dict[str, Any] = Field(default_factory=dict)
    mappings: tuple[SymbolMapping, ...] = ()

    @model_validator(mode="after")
    def _validate_unique_aliases(self) -> "SymbolMap":
        seen: dict[str, str] = {}
        for mapping in self.mappings:
            for symbol in mapping.all_symbols():
                existing = seen.get(symbol)
                if existing is not None:
                    raise ValueError(
                        f"duplicate symbol alias '{symbol}' in '{existing}' and '{mapping.mt5_symbol}'",
                    )
                seen[symbol] = mapping.mt5_symbol
        return self

    def resolve(self, raw_symbol: str) -> SymbolMapping:
        normalized = raw_symbol.strip().upper()
        for mapping in self.mappings:
            if normalized in mapping.all_symbols():
                return mapping
        raise KeyError(f"unknown symbol mapping '{raw_symbol}'")


def default_symbol_map_path() -> Path:
    """Return the bundled symbol-map path shipped with V2."""

    return DEFAULT_NAUTILUS_SYMBOL_MAP_PATH


def load_symbol_map(path: Path | str | None = None) -> SymbolMap:
    """Load and validate the bundled Nautilus symbol-map YAML."""

    resolved_path = Path(path) if path is not None else default_symbol_map_path()
    raw = yaml.safe_load(resolved_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"expected a mapping YAML object in {resolved_path}")
    return SymbolMap.model_validate(raw)


__all__ = ["SymbolMap", "SymbolMapping", "default_symbol_map_path", "load_symbol_map"]
