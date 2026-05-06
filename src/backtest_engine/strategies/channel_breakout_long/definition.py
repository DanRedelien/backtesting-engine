"""Strategy package definition for ``channel_breakout_long``."""

from __future__ import annotations

from typing import cast

from pydantic import BaseModel

from backtest_engine.core.errors import InfrastructureError
from backtest_engine.core.types import JsonValue
from backtest_engine.domain.strategy.specifications import PortfolioStrategySpec
from backtest_engine.strategies.channel_breakout_long.parameters import ChannelBreakoutLongParameters
from backtest_engine.strategies.package_contracts import (
    CompiledSlotSizingView,
    ResolvedCatalogItem,
    StrategyPackageDefinition,
)


_RESERVED_PARAMETER_KEYS = frozenset({"strategy_id", "symbol"})


def _build_parameters(strategy_spec: PortfolioStrategySpec) -> ChannelBreakoutLongParameters:
    _reject_reserved_parameters(strategy_spec)
    return ChannelBreakoutLongParameters.model_validate(
        {
            **strategy_spec.strategy.parameters,
            "strategy_id": strategy_spec.strategy.strategy_id,
            "symbol": strategy_spec.legs[0].symbol,
        }
    )


def _build_config(
    strategy_spec: PortfolioStrategySpec,
    parameters: BaseModel,
    strategy_items: tuple[ResolvedCatalogItem, ...],
    slot_sizing: CompiledSlotSizingView | None,
) -> dict[str, JsonValue]:
    del strategy_spec
    channel_parameters = cast(ChannelBreakoutLongParameters, parameters)
    item = strategy_items[0]
    return {
        "instrument_id": item.instrument_id,
        "bar_type": item.bar_type,
        "strategy_id": channel_parameters.strategy_id,
        "symbol": channel_parameters.symbol,
        "unit_trade_size": channel_parameters.trade_size,
        "slot_multiplier": _slot_multiplier(slot_sizing),
        "length": channel_parameters.length,
        "ema_period": channel_parameters.ema_period,
        "entry_buffer_ticks": channel_parameters.entry_buffer_ticks,
        "trade_direction": channel_parameters.trade_direction,
        "use_shock_filter": channel_parameters.use_shock_filter,
        "shock_atr_window": channel_parameters.shock_atr_window,
        "shock_max_gap_atr": channel_parameters.shock_max_gap_atr,
        "shock_max_range_atr": channel_parameters.shock_max_range_atr,
        "shock_max_close_change_atr": channel_parameters.shock_max_close_change_atr,
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
    implementation_id="channel_breakout_long",
    strategy_path=(
        "backtest_engine.strategies.channel_breakout_long.nautilus_strategy:"
        "ChannelBreakoutLongStrategy"
    ),
    config_path=(
        "backtest_engine.strategies.channel_breakout_long.nautilus_strategy:"
        "ChannelBreakoutLongStrategyConfig"
    ),
    build_parameters=_build_parameters,
    build_config=_build_config,
    min_legs=1,
    max_legs=1,
)


__all__ = ["STRATEGY_DEFINITION"]
