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
from backtest_engine.strategies.statarb_weighted_spread.definition import STRATEGY_DEFINITION


def _spec(parameters: Mapping[str, object]) -> PortfolioStrategySpec:
    return PortfolioStrategySpec(
        slot_id="slot-statarb",
        weight_frac=1.0,
        strategy=StrategySpec(
            strategy_id="statarb-es-nq",
            implementation_id="statarb_weighted_spread",
            policy_version="v1",
            parameters=cast(dict[str, JsonValue], dict(parameters)),
        ),
        legs=(StrategyLegSpec(symbol="ES"), StrategyLegSpec(symbol="NQ")),
    )


def _valid_parameters() -> dict[str, object]:
    return {
        "trade_sizes": [1.0, 1.0],
        "spread_weights": [1.0, -1.0],
        "zscore_window": 20,
        "entry_zscore": 1.0,
        "exit_zscore": 0.2,
    }


def test_statarb_rejects_reserved_derived_parameter_keys() -> None:
    parameters = {**_valid_parameters(), "leg_symbols": ["ES", "NQ"]}

    with pytest.raises(InfrastructureError, match="reserved derived keys"):
        STRATEGY_DEFINITION.build_parameters(_spec(parameters))


def test_statarb_rejects_bool_numeric_sequence_parameters() -> None:
    parameters = {**_valid_parameters(), "trade_sizes": [True, 1.0]}

    with pytest.raises(ValidationError, match="must contain built-in numbers"):
        STRATEGY_DEFINITION.build_parameters(_spec(parameters))


def test_statarb_rejects_string_numeric_sequence_parameters() -> None:
    parameters = {**_valid_parameters(), "trade_sizes": ["1.0", 1.0]}

    with pytest.raises(ValidationError, match="must contain built-in numbers"):
        STRATEGY_DEFINITION.build_parameters(_spec(parameters))


def test_statarb_rejects_bool_numeric_scalar_parameters() -> None:
    parameters = {**_valid_parameters(), "zscore_window": True}

    with pytest.raises(ValidationError, match="must be built-in numbers"):
        STRATEGY_DEFINITION.build_parameters(_spec(parameters))


def test_statarb_rejects_string_numeric_scalar_parameters() -> None:
    parameters = {**_valid_parameters(), "zscore_window": "20"}

    with pytest.raises(ValidationError, match="must be built-in numbers"):
        STRATEGY_DEFINITION.build_parameters(_spec(parameters))


def test_statarb_resolver_builds_full_config() -> None:
    compiled = build_default_nautilus_strategy_resolver().resolve(
        strategy_spec=_spec(
            {
                "trade_sizes": [1.0, 2.0],
                "spread_weights": [1.0, -0.5],
                "zscore_window": 20,
                "entry_zscore": 1.0,
                "exit_zscore": 0.2,
                "trade_direction": "short_spread_only",
            }
        ),
        catalog=CatalogReference(
            dataset_id="dataset-statarb",
            catalog_root=Path("catalogs/statarb"),
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
                CatalogItem(
                    symbol="NQ",
                    timeframe="30m",
                    instrument_id="NQ.CME",
                    venue="CME",
                    quote_currency="USD",
                    bar_type="NQ.CME-30-MINUTE-LAST-EXTERNAL",
                    row_count=100,
                ),
            ),
        ),
        slot_sizing=CompiledSlotSizing(
            slot_id="slot-statarb",
            target_weight_frac=1.0,
            effective_weight_frac=0.75,
            slot_multiplier=0.75,
        ),
    )

    assert compiled.config == {
        "instrument_ids": ["ES.CME", "NQ.CME"],
        "bar_types": ["ES.CME-30-MINUTE-LAST-EXTERNAL", "NQ.CME-30-MINUTE-LAST-EXTERNAL"],
        "leg_symbols": ["ES", "NQ"],
        "strategy_id": "statarb-es-nq",
        "unit_trade_sizes": [1.0, 2.0],
        "slot_multiplier": 0.75,
        "spread_weights": [1.0, -0.5],
        "zscore_window": 20,
        "entry_zscore": 1.0,
        "exit_zscore": 0.2,
        "trade_direction": "short_spread_only",
    }
