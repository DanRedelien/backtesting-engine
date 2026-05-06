# mypy: disable-error-code=no-untyped-def
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import cast

import pytest
from pydantic import ValidationError

from backtest_engine.core.errors import InfrastructureError
from backtest_engine.core.types import JsonValue
from backtest_engine.domain.strategy.specifications import (
    PortfolioStrategySpec,
    StrategyLegSpec,
    StrategySpec,
)
from backtest_engine.infrastructure.nautilus.catalogs import CatalogItem, CatalogReference
from backtest_engine.infrastructure.nautilus.portfolio_sizing import CompiledSlotSizing
from backtest_engine.infrastructure.nautilus.strategy_package_resolver import (
    build_default_nautilus_strategy_resolver,
)
from backtest_engine.strategies.channel_breakout_long.definition import STRATEGY_DEFINITION


def _spec(parameters: Mapping[str, object]) -> PortfolioStrategySpec:
    return PortfolioStrategySpec(
        slot_id="slot-channel",
        weight_frac=1.0,
        strategy=StrategySpec(
            strategy_id="channel-es",
            implementation_id="channel_breakout_long",
            policy_version="v1",
            parameters=cast(dict[str, JsonValue], dict(parameters)),
        ),
        legs=(StrategyLegSpec(symbol="ES"),),
    )


def test_channel_breakout_rejects_reserved_derived_parameter_keys() -> None:
    with pytest.raises(InfrastructureError, match="reserved derived keys"):
        STRATEGY_DEFINITION.build_parameters(_spec({"strategy_id": "override"}))


def test_channel_breakout_rejects_bool_numeric_parameters() -> None:
    with pytest.raises(ValidationError, match="must be built-in numbers"):
        STRATEGY_DEFINITION.build_parameters(_spec({"entry_buffer_ticks": True}))


def test_channel_breakout_rejects_string_numeric_parameters() -> None:
    with pytest.raises(ValidationError, match="must be built-in numbers"):
        STRATEGY_DEFINITION.build_parameters(_spec({"entry_buffer_ticks": "1"}))


def test_channel_breakout_resolver_builds_full_config() -> None:
    compiled = build_default_nautilus_strategy_resolver().resolve(
        strategy_spec=_spec(
            {
                "trade_size": 3.0,
                "length": 20,
                "ema_period": 50,
                "entry_buffer_ticks": 2,
                "trade_direction": "long",
                "use_shock_filter": False,
                "shock_atr_window": 7,
                "shock_max_gap_atr": 1.1,
                "shock_max_range_atr": 2.2,
                "shock_max_close_change_atr": 1.8,
            }
        ),
        catalog=CatalogReference(
            dataset_id="dataset-channel",
            catalog_root=Path("catalogs/channel"),
            items=(
                CatalogItem(
                    symbol="ES",
                    timeframe="30m",
                    instrument_id="ES.CME",
                    venue="CME",
                    quote_currency="USD",
                    bar_type="ES.CME-30-MINUTE-LAST-EXTERNAL",
                    row_count=100,
                ),
            ),
        ),
        slot_sizing=CompiledSlotSizing(
            slot_id="slot-channel",
            target_weight_frac=1.0,
            effective_weight_frac=0.5,
            slot_multiplier=0.5,
        ),
    )

    assert compiled.config == {
        "instrument_id": "ES.CME",
        "bar_type": "ES.CME-30-MINUTE-LAST-EXTERNAL",
        "strategy_id": "channel-es",
        "symbol": "ES",
        "unit_trade_size": 3.0,
        "slot_multiplier": 0.5,
        "length": 20,
        "ema_period": 50,
        "entry_buffer_ticks": 2,
        "trade_direction": "long",
        "use_shock_filter": False,
        "shock_atr_window": 7,
        "shock_max_gap_atr": 1.1,
        "shock_max_range_atr": 2.2,
        "shock_max_close_change_atr": 1.8,
    }
