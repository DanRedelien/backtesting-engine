# mypy: disable-error-code=no-untyped-def
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import cast

import pytest

from backtest_engine.core.errors import InfrastructureError
from backtest_engine.core.types import JsonValue
from backtest_engine.domain.strategy.specifications import (
    PortfolioStrategySpec,
    StrategyLegSpec,
    StrategySpec,
)
from backtest_engine.infrastructure.nautilus.catalogs import CatalogItem, CatalogReference
from backtest_engine.infrastructure.nautilus.strategy_package_resolver import (
    build_default_nautilus_strategy_resolver,
)
from backtest_engine.strategies.passive_bar.definition import STRATEGY_DEFINITION


def _spec(parameters: Mapping[str, object]) -> PortfolioStrategySpec:
    return PortfolioStrategySpec(
        slot_id="slot-passive",
        weight_frac=1.0,
        strategy=StrategySpec(
            strategy_id="passive-es",
            implementation_id="passive_bar",
            policy_version="v1",
            parameters=cast(dict[str, JsonValue], dict(parameters)),
        ),
        legs=(StrategyLegSpec(symbol="ES"),),
    )


def test_passive_bar_rejects_user_supplied_parameters() -> None:
    with pytest.raises(InfrastructureError, match="parameters are not supported"):
        STRATEGY_DEFINITION.build_parameters(_spec({"trade_size": 1.0}))


def test_passive_bar_resolver_builds_full_config() -> None:
    compiled = build_default_nautilus_strategy_resolver().resolve(
        strategy_spec=_spec({}),
        catalog=CatalogReference(
            dataset_id="dataset-passive",
            catalog_root=Path("catalogs/passive"),
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
    )

    assert compiled.config == {
        "instrument_id": "ES.CME",
        "bar_type": "ES.CME-30-MINUTE-LAST-EXTERNAL",
        "strategy_id": "passive-es",
    }
