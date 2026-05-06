"""Shared contracts for concrete strategy cartridges."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from pydantic import BaseModel

from backtest_engine.core.types import JsonValue, NonEmptyStr
from backtest_engine.domain.strategy.specifications import PortfolioStrategySpec


class ResolvedCatalogItem(Protocol):
    """Structural view of one catalog item passed into strategy config builders."""

    symbol: str
    timeframe: str
    instrument_id: str
    venue: str
    quote_currency: str
    bar_type: str
    row_count: int


class CompiledSlotSizingView(Protocol):
    """Structural view of slot sizing made available to strategy config builders."""

    slot_multiplier: float


StrategyParameterBuilder = Callable[[PortfolioStrategySpec], BaseModel]
StrategyConfigBuilder = Callable[
    [
        PortfolioStrategySpec,
        BaseModel,
        tuple[ResolvedCatalogItem, ...],
        CompiledSlotSizingView | None,
    ],
    dict[str, JsonValue],
]
StrategySpecValidator = Callable[[PortfolioStrategySpec], None]


@dataclass(frozen=True)
class StrategyPackageDefinition:
    """Runtime metadata and pure builders for one concrete strategy cartridge."""

    implementation_id: NonEmptyStr
    strategy_path: NonEmptyStr
    config_path: NonEmptyStr
    build_parameters: StrategyParameterBuilder
    build_config: StrategyConfigBuilder
    min_legs: int
    max_legs: int | None
    validate_strategy_spec: StrategySpecValidator | None = None

    def __post_init__(self) -> None:
        if self.min_legs < 1:
            raise ValueError("min_legs must be at least one")
        if self.max_legs is not None and self.max_legs < self.min_legs:
            raise ValueError("max_legs must be greater than or equal to min_legs")


__all__ = [
    "CompiledSlotSizingView",
    "ResolvedCatalogItem",
    "StrategyConfigBuilder",
    "StrategyPackageDefinition",
    "StrategyParameterBuilder",
    "StrategySpecValidator",
]
