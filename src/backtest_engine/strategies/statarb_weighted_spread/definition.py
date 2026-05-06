"""Strategy package definition for ``statarb_weighted_spread``."""

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
from backtest_engine.strategies.statarb_weighted_spread.parameters import (
    StatarbWeightedSpreadParameters,
)


_RESERVED_PARAMETER_KEYS = frozenset({"strategy_id", "leg_symbols"})


def _build_parameters(strategy_spec: PortfolioStrategySpec) -> StatarbWeightedSpreadParameters:
    _reject_reserved_parameters(strategy_spec)
    return StatarbWeightedSpreadParameters.model_validate(
        {
            **strategy_spec.strategy.parameters,
            "strategy_id": strategy_spec.strategy.strategy_id,
            "leg_symbols": tuple(leg.symbol for leg in strategy_spec.legs),
        }
    )


def _build_config(
    strategy_spec: PortfolioStrategySpec,
    parameters: BaseModel,
    strategy_items: tuple[ResolvedCatalogItem, ...],
    slot_sizing: CompiledSlotSizingView | None,
) -> dict[str, JsonValue]:
    del strategy_spec
    statarb_parameters = cast(StatarbWeightedSpreadParameters, parameters)
    return {
        "instrument_ids": [item.instrument_id for item in strategy_items],
        "bar_types": [item.bar_type for item in strategy_items],
        "leg_symbols": list(statarb_parameters.leg_symbols),
        "strategy_id": statarb_parameters.strategy_id,
        "unit_trade_sizes": list(statarb_parameters.trade_sizes),
        "slot_multiplier": _slot_multiplier(slot_sizing),
        "spread_weights": list(statarb_parameters.spread_weights),
        "zscore_window": statarb_parameters.zscore_window,
        "entry_zscore": statarb_parameters.entry_zscore,
        "exit_zscore": statarb_parameters.exit_zscore,
        "trade_direction": statarb_parameters.trade_direction,
    }


def _slot_multiplier(slot_sizing: CompiledSlotSizingView | None) -> float:
    if slot_sizing is None:
        return 1.0
    return float(slot_sizing.slot_multiplier)


def _reject_reserved_parameters(strategy_spec: PortfolioStrategySpec) -> None:
    reserved_keys = sorted(set(strategy_spec.strategy.parameters).intersection(_RESERVED_PARAMETER_KEYS))
    if not reserved_keys:
        return
    raise InfrastructureError(
        "strategy parameters include reserved derived keys",
        strategy_id=strategy_spec.strategy.strategy_id,
        implementation_id=strategy_spec.strategy.implementation_id,
        reserved_parameters=",".join(reserved_keys),
    )


STRATEGY_DEFINITION = StrategyPackageDefinition(
    implementation_id="statarb_weighted_spread",
    strategy_path=(
        "backtest_engine.strategies.statarb_weighted_spread.nautilus_strategy:"
        "StatarbWeightedSpreadStrategy"
    ),
    config_path=(
        "backtest_engine.strategies.statarb_weighted_spread.nautilus_strategy:"
        "StatarbWeightedSpreadStrategyConfig"
    ),
    build_parameters=_build_parameters,
    build_config=_build_config,
    min_legs=2,
    max_legs=None,
)


__all__ = ["STRATEGY_DEFINITION"]
