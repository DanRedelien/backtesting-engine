"""Strategy package definition for ``passive_bar``."""

from __future__ import annotations

from typing import cast

from pydantic import BaseModel

from backtest_engine.core.errors import InfrastructureError
from backtest_engine.core.types import JsonValue
from backtest_engine.domain.strategy.specifications import PortfolioStrategySpec
from backtest_engine.strategies.package_contracts import (
    CompiledSlotSizingView,
    ResolvedCatalogItem,
    StrategyPackageDefinition,
)
from backtest_engine.strategies.passive_bar.parameters import PassiveBarParameters


def _build_parameters(strategy_spec: PortfolioStrategySpec) -> PassiveBarParameters:
    unsupported_keys = sorted(strategy_spec.strategy.parameters)
    if unsupported_keys:
        raise InfrastructureError(
            "strategy parameters are not supported by passive_bar",
            strategy_id=strategy_spec.strategy.strategy_id,
            implementation_id=strategy_spec.strategy.implementation_id,
            unsupported_parameters=",".join(unsupported_keys),
        )
    return PassiveBarParameters(
        strategy_id=strategy_spec.strategy.strategy_id,
        symbol=strategy_spec.legs[0].symbol,
    )


def _build_config(
    strategy_spec: PortfolioStrategySpec,
    parameters: BaseModel,
    strategy_items: tuple[ResolvedCatalogItem, ...],
    slot_sizing: CompiledSlotSizingView | None,
) -> dict[str, JsonValue]:
    del strategy_spec, slot_sizing
    passive_parameters = cast(PassiveBarParameters, parameters)
    item = strategy_items[0]
    return {
        "instrument_id": item.instrument_id,
        "bar_type": item.bar_type,
        "strategy_id": passive_parameters.strategy_id,
    }


STRATEGY_DEFINITION = StrategyPackageDefinition(
    implementation_id="passive_bar",
    strategy_path="backtest_engine.strategies.passive_bar.nautilus_strategy:PassiveBarStrategy",
    config_path="backtest_engine.strategies.passive_bar.nautilus_strategy:PassiveBarStrategyConfig",
    build_parameters=_build_parameters,
    build_config=_build_config,
    min_legs=1,
    max_legs=1,
)


__all__ = ["STRATEGY_DEFINITION"]
