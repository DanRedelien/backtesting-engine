"""Internal data structures for spread calibration publication."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from backtest_engine.application.calibration.contracts import SpreadCalibrationPanelRow
from backtest_engine.domain.execution.instrument_metadata import ExecutionAssetClass
from backtest_engine.infrastructure.nautilus.symbol_map import SymbolMapping


@dataclass(frozen=True)
class SplitRows:
    train: tuple[SpreadCalibrationPanelRow, ...]
    holdout: tuple[SpreadCalibrationPanelRow, ...]
    purged: tuple[SpreadCalibrationPanelRow, ...]
    split_timestamp_utc: datetime
    holdout_start_utc: datetime
    purged_gap: timedelta


@dataclass(frozen=True)
class SymbolBounds:
    base_half_spread_price: float
    min_half_spread_price: float
    max_half_spread_price: float


@dataclass(frozen=True)
class PreparedPublication:
    mappings_by_symbol: dict[str, SymbolMapping]
    tick_size_by_symbol: dict[str, Decimal]
    min_half_spread_by_symbol: dict[str, float]
    canonical_symbol_by_input_symbol: dict[str, str]
    asset_classes: set[ExecutionAssetClass]


__all__ = ["PreparedPublication", "SplitRows", "SymbolBounds"]
