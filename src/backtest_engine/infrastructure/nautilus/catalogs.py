"""Prepare Nautilus data catalogs from materialized datasets."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC
from decimal import Decimal
from pathlib import Path

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from backtest_engine.core.errors import InfrastructureError
from backtest_engine.core.types import NonEmptyStr, Symbol, Timeframe
from backtest_engine.infrastructure.data.parquet_normalizer import MaterializedDataset
from backtest_engine.infrastructure.nautilus.symbol_map import SymbolMapping, load_symbol_map


_TIMEFRAME_TO_BAR_STEP = {
    "1m": "1-MINUTE",
    "5m": "5-MINUTE",
    "15m": "15-MINUTE",
    "30m": "30-MINUTE",
    "1h": "1-HOUR",
    "4h": "4-HOUR",
    "1d": "1-DAY",
}
_FUTURES_OPEN_ENDED_EXPIRATION_NS = 2**63 - 1


class CatalogItem(BaseModel):
    """One catalog-backed symbol slice for a compiled Nautilus run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: Symbol
    timeframe: Timeframe
    instrument_id: NonEmptyStr
    venue: NonEmptyStr
    quote_currency: NonEmptyStr
    bar_type: NonEmptyStr
    row_count: int


class CatalogReference(BaseModel):
    """A persisted Nautilus catalog built from one materialized dataset."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_id: NonEmptyStr
    catalog_root: Path
    items: tuple[CatalogItem, ...] = Field(default_factory=tuple)


@dataclass(frozen=True)
class FilesystemNautilusCatalogBuilder:
    """Write materialized datasets into a deterministic Nautilus catalog root."""

    catalog_cache_root: Path
    symbol_map_path: Path | None = None

    def build(self, dataset: MaterializedDataset) -> CatalogReference:
        """Return the persisted catalog reference for one materialized dataset."""

        catalog_root = self.catalog_cache_root / dataset.dataset.dataset_id
        symbol_map = load_symbol_map(self.symbol_map_path)
        if catalog_root.exists() and any(catalog_root.iterdir()):
            return CatalogReference(
                dataset_id=dataset.dataset.dataset_id,
                catalog_root=catalog_root,
                items=tuple(
                    self._build_catalog_item(artifact.manifest, symbol_map)
                    for artifact in dataset.artifacts
                ),
            )

        try:
            from nautilus_trader.model import BarType
            from nautilus_trader.persistence.catalog import ParquetDataCatalog
            from nautilus_trader.persistence.wranglers import BarDataWrangler
        except Exception as exc:
            raise InfrastructureError("failed to import Nautilus catalog dependencies") from exc

        catalog_root.mkdir(parents=True, exist_ok=True)
        catalog = ParquetDataCatalog(catalog_root)
        written_instrument_ids: set[str] = set()
        items: list[CatalogItem] = []

        for artifact in dataset.artifacts:
            mapping = symbol_map.resolve(artifact.manifest.raw_symbol)
            instrument = _build_instrument(mapping)
            bar_type = _bar_type_for(mapping, artifact.manifest.timeframe)
            bars = pd.read_parquet(artifact.data_path)
            wrangler_frame = bars.copy()
            wrangler_frame["ts_event_utc"] = pd.to_datetime(wrangler_frame["ts_event_utc"], utc=True)
            # BarDataWrangler receives the already-canonical open event time.
            # The catalog handoff must preserve it and must not add a close shift.
            wrangler_frame = wrangler_frame.set_index("ts_event_utc")
            bar_objects = BarDataWrangler(BarType.from_str(bar_type), instrument).process(
                wrangler_frame[["open", "high", "low", "close", "volume"]].copy(),
            )
            if instrument.id.value not in written_instrument_ids:
                catalog.write_data([instrument])
                written_instrument_ids.add(instrument.id.value)
            catalog.write_data(bar_objects)
            items.append(self._build_catalog_item(artifact.manifest, symbol_map))

        return CatalogReference(
            dataset_id=dataset.dataset.dataset_id,
            catalog_root=catalog_root,
            items=tuple(items),
        )

    def _build_catalog_item(self, manifest, symbol_map) -> CatalogItem:
        mapping = symbol_map.resolve(manifest.raw_symbol)
        return CatalogItem(
            symbol=manifest.raw_symbol,
            timeframe=manifest.timeframe,
            instrument_id=mapping.nautilus_instrument_id,
            venue=mapping.venue,
            quote_currency=mapping.quote_currency,
            bar_type=_bar_type_for(mapping, manifest.timeframe),
            row_count=manifest.row_count,
        )


def _build_instrument(mapping: SymbolMapping):
    from decimal import Decimal as PyDecimal

    from nautilus_trader.model.identifiers import InstrumentId
    from nautilus_trader.model.identifiers import Symbol
    from nautilus_trader.model.instruments import Cfd
    from nautilus_trader.model.instruments import CurrencyPair
    from nautilus_trader.model.instruments import FuturesContract
    from nautilus_trader.model.objects import Currency
    from nautilus_trader.model.objects import Price
    from nautilus_trader.model.objects import Quantity

    instrument_id = InstrumentId.from_str(mapping.nautilus_instrument_id)
    raw_symbol = Symbol(mapping.nautilus_symbol)
    price_increment = Price.from_str(_decimal_to_nautilus_str(mapping.tick_size))
    lot_size = Quantity.from_str(_decimal_to_nautilus_str(mapping.lot_size))
    margin_init = PyDecimal(str(mapping.margin_init)) if mapping.margin_init is not None else None
    margin_maint = PyDecimal(str(mapping.margin_maint)) if mapping.margin_maint is not None else None
    maker_fee = PyDecimal(str(mapping.maker_fee)) if mapping.maker_fee is not None else None
    taker_fee = PyDecimal(str(mapping.taker_fee)) if mapping.taker_fee is not None else None
    asset_class = _asset_class_from_mapping(mapping.asset_class)
    info = {"mapping_symbol": mapping.mt5_symbol, "aliases": list(mapping.aliases)}

    if mapping.instrument_type == "CURRENCY_PAIR":
        size_increment = Quantity.from_str(_decimal_to_nautilus_str(mapping.size_increment))
        multiplier = Quantity.from_str(_decimal_to_nautilus_str(mapping.multiplier or Decimal("1")))
        return CurrencyPair(
            instrument_id=instrument_id,
            raw_symbol=raw_symbol,
            base_currency=Currency.from_str(mapping.base_currency),
            quote_currency=Currency.from_str(mapping.quote_currency),
            price_precision=mapping.price_precision,
            size_precision=mapping.size_precision,
            price_increment=price_increment,
            size_increment=size_increment,
            ts_event=0,
            ts_init=0,
            multiplier=multiplier,
            lot_size=lot_size,
            margin_init=margin_init,
            margin_maint=margin_maint,
            maker_fee=maker_fee,
            taker_fee=taker_fee,
            info=info,
        )

    if mapping.instrument_type == "CFD":
        size_increment = Quantity.from_str(_decimal_to_nautilus_str(mapping.size_increment))
        return Cfd(
            instrument_id=instrument_id,
            raw_symbol=raw_symbol,
            asset_class=asset_class,
            quote_currency=Currency.from_str(mapping.quote_currency),
            price_precision=mapping.price_precision,
            size_precision=mapping.size_precision,
            price_increment=price_increment,
            size_increment=size_increment,
            ts_event=0,
            ts_init=0,
            base_currency=Currency.from_str(mapping.base_currency) if mapping.base_currency else None,
            lot_size=lot_size,
            margin_init=margin_init,
            margin_maint=margin_maint,
            maker_fee=maker_fee,
            taker_fee=taker_fee,
            info=info,
        )

    if mapping.instrument_type == "FUTURES":
        if mapping.multiplier is None:
            raise InfrastructureError(
                "futures instruments require multiplier metadata",
                symbol=mapping.mt5_symbol,
                instrument_id=mapping.nautilus_instrument_id,
            )
        multiplier = Quantity.from_str(_decimal_to_nautilus_str(mapping.multiplier))
        return FuturesContract(
            instrument_id=instrument_id,
            raw_symbol=raw_symbol,
            asset_class=asset_class,
            currency=Currency.from_str(mapping.quote_currency),
            price_precision=mapping.price_precision,
            price_increment=price_increment,
            multiplier=multiplier,
            lot_size=lot_size,
            underlying=mapping.underlying,
            activation_ns=_dt_to_unix_nanos_or_default(mapping.activation_time_utc, 0),
            expiration_ns=_dt_to_unix_nanos_or_default(
                mapping.expiration_time_utc,
                _FUTURES_OPEN_ENDED_EXPIRATION_NS,
            ),
            ts_event=0,
            ts_init=0,
            margin_init=margin_init,
            margin_maint=margin_maint,
            maker_fee=maker_fee,
            taker_fee=taker_fee,
            exchange=mapping.exchange,
            info=info,
        )

    raise InfrastructureError(
        "unsupported instrument mapping for Nautilus catalog build",
        instrument_type=mapping.instrument_type,
        symbol=mapping.mt5_symbol,
    )


def _asset_class_from_mapping(asset_class: str | None):
    from nautilus_trader.model.enums import AssetClass

    mapping = {
        "FX": AssetClass.FX,
        "INDEX": AssetClass.INDEX,
        "COMMODITY": AssetClass.COMMODITY,
        "EQUITY": AssetClass.EQUITY,
        "CRYPTOCURRENCY": AssetClass.CRYPTOCURRENCY,
    }
    if asset_class is None:
        return None
    return mapping[asset_class]


def _bar_type_for(mapping: SymbolMapping, timeframe: Timeframe) -> str:
    normalized_timeframe = timeframe.strip().lower()
    try:
        bar_step = _TIMEFRAME_TO_BAR_STEP[normalized_timeframe]
    except KeyError as exc:
        supported = ", ".join(sorted(_TIMEFRAME_TO_BAR_STEP))
        raise InfrastructureError(
            "unsupported timeframe for Nautilus bar type",
            timeframe=timeframe,
            supported_timeframes=supported,
        ) from exc
    return f"{mapping.nautilus_instrument_id}-{bar_step}-LAST-EXTERNAL"


def _decimal_to_nautilus_str(value: Decimal) -> str:
    normalized = value.normalize()
    if normalized == normalized.to_integral():
        return str(normalized.quantize(Decimal("1")))
    return format(normalized, "f")


def _dt_to_unix_nanos_or_default(value, default: int) -> int:
    if value is None:
        return default
    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return int(aware.timestamp() * 1_000_000_000)


__all__ = ["CatalogItem", "CatalogReference", "FilesystemNautilusCatalogBuilder"]
