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
from backtest_engine.strategies.sma_pullback.definition import STRATEGY_DEFINITION


def _spec(parameters: Mapping[str, object]) -> PortfolioStrategySpec:
    return PortfolioStrategySpec(
        slot_id="slot-sma",
        weight_frac=1.0,
        strategy=StrategySpec(
            strategy_id="sma-es",
            implementation_id="sma_pullback",
            policy_version="v1",
            parameters=cast(dict[str, JsonValue], dict(parameters)),
        ),
        legs=(StrategyLegSpec(symbol="ES"),),
    )


def test_sma_pullback_rejects_reserved_derived_parameter_keys() -> None:
    with pytest.raises(InfrastructureError, match="reserved derived keys"):
        STRATEGY_DEFINITION.build_parameters(_spec({"symbol": "NQ"}))


def test_sma_pullback_rejects_bool_numeric_parameters() -> None:
    with pytest.raises(ValidationError, match="must be built-in numbers"):
        STRATEGY_DEFINITION.build_parameters(_spec({"trade_size": True}))


def test_sma_pullback_rejects_string_numeric_parameters() -> None:
    with pytest.raises(ValidationError, match="must be built-in numbers"):
        STRATEGY_DEFINITION.build_parameters(_spec({"trade_size": "1.0"}))


def test_sma_pullback_resolver_builds_full_config() -> None:
    compiled = build_default_nautilus_strategy_resolver().resolve(
        strategy_spec=_spec(
            {
                "trade_size": 2.0,
                "fast_sma_window": 10,
                "slow_sma_window": 30,
                "atr_window": 5,
                "atr_sl_mult": 1.5,
                "rr_ratio": 2.0,
                "trade_direction": "long",
            }
        ),
        catalog=CatalogReference(
            dataset_id="dataset-sma",
            catalog_root=Path("catalogs/sma"),
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
            slot_id="slot-sma",
            target_weight_frac=1.0,
            effective_weight_frac=0.25,
            slot_multiplier=0.25,
        ),
    )

    assert compiled.config == {
        "instrument_id": "ES.CME",
        "bar_type": "ES.CME-30-MINUTE-LAST-EXTERNAL",
        "strategy_id": "sma-es",
        "symbol": "ES",
        "unit_trade_size": 2.0,
        "slot_multiplier": 0.25,
        "fast_sma_window": 10,
        "slow_sma_window": 30,
        "atr_window": 5,
        "atr_sl_mult": 1.5,
        "rr_ratio": 2.0,
        "trade_direction": "long",
    }
