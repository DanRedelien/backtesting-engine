from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from typing import Any

import pytest

from backtest_engine.config.execution_costs import (
    DEFAULT_EXECUTION_COST_PROFILE_ID,
    ExecutionCostsConfig,
    load_execution_costs,
)
from backtest_engine.domain.execution.commissions import (
    FixedPerContractCommission,
    RateOfNotionalCommission,
)
from backtest_engine.domain.execution.instrument_metadata import (
    ExecutionAssetClass,
    ExecutionInstrumentMetadata,
    ExecutionInstrumentType,
)
from backtest_engine.domain.execution.spreads import (
    BufferedStaticSpread,
    LogLinearDynamicHalfSpread,
    StaticHalfSpreadPrice,
    StaticHalfSpreadTicks,
    calculate_half_spread_price,
)
from backtest_engine.domain.execution.slippage import (
    BpsOfPriceSlippage,
    FixedTicksSlippage,
    calculate_slippage_price,
)
from backtest_engine.infrastructure.nautilus.symbol_map import SymbolMapping, load_symbol_map


def test_bundled_execution_costs_resolve_current_symbol_universe() -> None:
    execution_costs = load_execution_costs()
    symbol_map = load_symbol_map()
    metadata_by_leg = tuple(_metadata_from_mapping(mapping) for mapping in symbol_map.mappings)
    metadata_by_symbol = {metadata.symbol: metadata for metadata in metadata_by_leg}

    profiles = execution_costs.resolve_profiles(metadata_by_leg)
    profiles_by_symbol = {profile.symbol: profile for profile in profiles}

    assert len(profiles) == len(symbol_map.mappings)
    assert isinstance(profiles_by_symbol["XAUUSD"].commission_model, RateOfNotionalCommission)
    assert isinstance(profiles_by_symbol["US500"].commission_model, RateOfNotionalCommission)
    assert isinstance(profiles_by_symbol["BTCUSD"].commission_model, RateOfNotionalCommission)
    assert isinstance(profiles_by_symbol["ES"].commission_model, FixedPerContractCommission)
    assert profiles_by_symbol["ES"].commission_model.amount_per_contract == Decimal("2.25")
    assert isinstance(profiles_by_symbol["EURUSD"].spread_model, StaticHalfSpreadTicks)
    assert isinstance(profiles_by_symbol["XAUUSD"].spread_model, StaticHalfSpreadPrice)
    assert isinstance(profiles_by_symbol["US500"].spread_model, BufferedStaticSpread)
    assert isinstance(profiles_by_symbol["BTCUSD"].spread_model, BufferedStaticSpread)
    assert isinstance(profiles_by_symbol["ES"].spread_model, StaticHalfSpreadTicks)
    assert all(
        not isinstance(profile.spread_model, LogLinearDynamicHalfSpread) for profile in profiles
    )
    assert isinstance(profiles_by_symbol["EURUSD"].slippage_model, FixedTicksSlippage)
    assert isinstance(profiles_by_symbol["XAUUSD"].slippage_model, FixedTicksSlippage)
    assert isinstance(profiles_by_symbol["US500"].slippage_model, BpsOfPriceSlippage)
    assert isinstance(profiles_by_symbol["BTCUSD"].slippage_model, BpsOfPriceSlippage)
    assert isinstance(profiles_by_symbol["ES"].slippage_model, FixedTicksSlippage)
    assert calculate_half_spread_price(
        metadata_by_symbol["ES"],
        profiles_by_symbol["ES"].spread_model,
    ) == Decimal("0.125")
    assert calculate_half_spread_price(
        metadata_by_symbol["RTY"],
        profiles_by_symbol["RTY"].spread_model,
    ) == Decimal("0.05")
    assert calculate_slippage_price(
        metadata_by_symbol["ES"],
        profiles_by_symbol["ES"].slippage_model,
        "5000",
    ) == Decimal("0.25")
    assert calculate_slippage_price(
        metadata_by_symbol["BTCUSD"],
        profiles_by_symbol["BTCUSD"].slippage_model,
        "50000",
    ) == Decimal("10.00")


def test_bundled_execution_costs_exposes_default_profile_id() -> None:
    execution_costs = load_execution_costs()

    assert execution_costs.profile_id == DEFAULT_EXECUTION_COST_PROFILE_ID


def test_execution_costs_config_accepts_in_memory_dynamic_spread_profile() -> None:
    execution_costs = ExecutionCostsConfig.model_validate(
        {
            "schema_version": 1,
            "profile_id": "test_dynamic_spread_profile",
            "owner": "unit-tests",
            "description": "In-memory dynamic spread fixture; not bundled runtime defaults.",
            "asset_class_defaults": {
                "INDEX": {
                    "commission_model": {
                        "model": "rate_of_notional",
                        "commission_rate_bps": "0.40",
                    },
                    "spread_model": {
                        "model": "log_linear_dynamic_half_spread",
                        "base_half_spread_price": "0.25",
                        "min_half_spread_price": "0.10",
                        "max_half_spread_price": "2.00",
                        "volatility_weight": "0.50",
                        "liquidity_weight": "0.25",
                        "session_buckets": [
                            {
                                "session_bucket_id": "regular",
                                "session_adjustment_log": "0",
                            },
                            {
                                "session_bucket_id": "rollover",
                                "session_adjustment_log": "0.20",
                            },
                        ],
                        "provenance": {
                            "symbol": "ES",
                            "venue": "CME",
                            "timeframe": "15m",
                            "provider_or_broker": "manual-test-fixture",
                            "sample_start_utc": "2024-01-01T00:00:00Z",
                            "sample_end_utc": "2024-02-01T00:00:00Z",
                            "row_count": 1000,
                            "data_quality_notes": "fixture only",
                            "sample_role": "in_sample_fixture",
                            "estimator_method": "manual",
                            "conversion_method": "already_price_units",
                        },
                    },
                    "slippage_model": {
                        "model": "fixed_ticks",
                        "slippage_ticks": "1",
                    },
                },
            },
        },
    )
    profile = execution_costs.resolve_profile(
        ExecutionInstrumentMetadata(
            symbol="ES",
            instrument_type=ExecutionInstrumentType.FUTURES,
            asset_class=ExecutionAssetClass.INDEX,
            quote_currency="USD",
            tick_size=Decimal("0.25"),
            point_size=Decimal("0.25"),
            lot_size=Decimal("1"),
            multiplier=Decimal("50"),
            price_precision=2,
        ),
    )

    assert isinstance(profile.spread_model, LogLinearDynamicHalfSpread)
    assert profile.spread_model.provenance.symbol == "ES"
    assert profile.spread_model.session_buckets[1].session_bucket_id == "rollover"


def test_execution_costs_config_resolves_dynamic_spread_runtime_settings() -> None:
    execution_costs = ExecutionCostsConfig.model_validate(
        {
            "schema_version": 1,
            "profile_id": "test_dynamic_runtime",
            "owner": "unit-tests",
            "description": "Dynamic runtime fixture.",
            "asset_class_defaults": {
                "INDEX": {
                    "commission_model": {
                        "model": "rate_of_notional",
                        "commission_rate_bps": "0.40",
                    },
                    "spread_model": {
                        "model": "static_half_spread_price",
                        "half_spread_price": "0.25",
                    },
                    "slippage_model": {
                        "model": "fixed_ticks",
                        "slippage_ticks": "1",
                    },
                },
            },
            "dynamic_spread_runtime": {
                "asset_class_defaults": {
                    "INDEX": {
                        "volatility_short_window_bars": 2,
                        "volatility_baseline_window_bars": 3,
                        "volatility_floor_price": "0.01",
                        "volatility_signal_method": "true_range_atr",
                        "volume_baseline_window_bars": 4,
                        "volume_floor": "1",
                        "dynamic_order_types": ["market"],
                        "session_buckets": [
                            {
                                "session_bucket_id": "regular",
                                "weekdays": [0, 1, 2, 3, 4],
                                "start_time_utc": "13:30:00",
                                "end_time_utc": "20:00:00",
                            },
                        ],
                    },
                },
            },
        },
    )

    runtime_profile = execution_costs.resolve_dynamic_spread_runtime(
        ExecutionInstrumentMetadata(
            symbol="ES",
            instrument_type=ExecutionInstrumentType.FUTURES,
            asset_class=ExecutionAssetClass.INDEX,
            quote_currency="USD",
            tick_size=Decimal("0.25"),
            point_size=Decimal("0.25"),
            lot_size=Decimal("1"),
            multiplier=Decimal("50"),
            price_precision=2,
        ),
    )

    assert runtime_profile is not None
    assert runtime_profile.required_history_bars == 4
    assert runtime_profile.volatility_floor_price == Decimal("0.01")
    assert runtime_profile.volatility_signal_method == "true_range_atr"
    assert runtime_profile.dynamic_order_types == ("market",)
    assert runtime_profile.session_buckets[0].session_bucket_id == "regular"


def test_execution_costs_config_rejects_timezone_aware_session_bucket_times() -> None:
    with pytest.raises(ValueError, match="session bucket times must be naive"):
        ExecutionCostsConfig.model_validate(
            {
                "schema_version": 1,
                "profile_id": "test_dynamic_runtime",
                "owner": "unit-tests",
                "description": "Dynamic runtime fixture.",
                "asset_class_defaults": {
                    "INDEX": {
                        "commission_model": {
                            "model": "rate_of_notional",
                            "commission_rate_bps": "0.40",
                        },
                        "spread_model": {
                            "model": "static_half_spread_price",
                            "half_spread_price": "0.25",
                        },
                        "slippage_model": {
                            "model": "fixed_ticks",
                            "slippage_ticks": "1",
                        },
                    },
                },
                "dynamic_spread_runtime": {
                    "asset_class_defaults": {
                        "INDEX": {
                            "volatility_short_window_bars": 2,
                            "volatility_baseline_window_bars": 3,
                            "volatility_floor_price": "0.01",
                            "volatility_signal_method": "true_range_atr",
                            "volume_baseline_window_bars": 4,
                            "volume_floor": "1",
                            "dynamic_order_types": ["market"],
                            "session_buckets": [
                                {
                                    "session_bucket_id": "regular",
                                    "weekdays": [0, 1, 2, 3, 4],
                                    "start_time_utc": "13:30:00Z",
                                    "end_time_utc": "20:00:00Z",
                                },
                            ],
                        },
                    },
                },
            },
        )


def test_dynamic_spread_runtime_rejects_hidden_or_unsupported_assumptions() -> None:
    base_payload: dict[str, Any] = {
        "schema_version": 1,
        "profile_id": "test_dynamic_runtime",
        "owner": "unit-tests",
        "description": "Dynamic runtime fixture.",
        "asset_class_defaults": {
            "INDEX": {
                "commission_model": {
                    "model": "rate_of_notional",
                    "commission_rate_bps": "0.40",
                },
                "spread_model": {
                    "model": "static_half_spread_price",
                    "half_spread_price": "0.25",
                },
                "slippage_model": {
                    "model": "fixed_ticks",
                    "slippage_ticks": "1",
                },
            },
        },
        "dynamic_spread_runtime": {
            "asset_class_defaults": {
                "INDEX": {
                    "volatility_short_window_bars": 2,
                    "volatility_baseline_window_bars": 3,
                    "volatility_floor_price": "0.01",
                    "volatility_signal_method": "true_range_atr",
                    "volume_baseline_window_bars": 4,
                    "volume_floor": "1",
                    "dynamic_order_types": ["market"],
                    "session_buckets": [
                        {
                            "session_bucket_id": "regular",
                            "weekdays": [0, 1, 2, 3, 4],
                            "start_time_utc": "13:30:00",
                            "end_time_utc": "20:00:00",
                        },
                    ],
                },
            },
        },
    }

    missing_floor = deepcopy(base_payload)
    missing_floor["dynamic_spread_runtime"] = {
        "asset_class_defaults": {
            "INDEX": {
                key: value
                for key, value in base_payload["dynamic_spread_runtime"]["asset_class_defaults"][
                    "INDEX"
                ].items()
                if key != "volatility_floor_price"
            },
        },
    }
    non_positive_floor = deepcopy(base_payload)
    non_positive_floor["dynamic_spread_runtime"] = {
        "asset_class_defaults": {
            "INDEX": {
                **base_payload["dynamic_spread_runtime"]["asset_class_defaults"]["INDEX"],
                "volatility_floor_price": "0",
            },
        },
    }
    unsupported_method = deepcopy(base_payload)
    unsupported_method["dynamic_spread_runtime"] = {
        "asset_class_defaults": {
            "INDEX": {
                **base_payload["dynamic_spread_runtime"]["asset_class_defaults"]["INDEX"],
                "volatility_signal_method": "high_low_range",
            },
        },
    }
    unsupported_order_type = deepcopy(base_payload)
    unsupported_order_type["dynamic_spread_runtime"] = {
        "asset_class_defaults": {
            "INDEX": {
                **base_payload["dynamic_spread_runtime"]["asset_class_defaults"]["INDEX"],
                "dynamic_order_types": ["market", "stop"],
            },
        },
    }

    for payload in (
        missing_floor,
        non_positive_floor,
        unsupported_method,
        unsupported_order_type,
    ):
        with pytest.raises(ValueError):
            ExecutionCostsConfig.model_validate(payload)


def test_execution_costs_do_not_mutate_nautilus_symbol_map_fee_fields() -> None:
    _ = load_execution_costs()
    symbol_map = load_symbol_map()

    assert symbol_map.resolve("EURUSD").maker_fee == Decimal("0.00002")
    assert symbol_map.resolve("XAUUSD").maker_fee is None
    assert symbol_map.resolve("ES").taker_fee is None


def _metadata_from_mapping(mapping: SymbolMapping) -> ExecutionInstrumentMetadata:
    if mapping.asset_class is None:
        raise AssertionError(f"mapping {mapping.mt5_symbol} must define asset_class")
    return ExecutionInstrumentMetadata(
        symbol=mapping.mt5_symbol,
        instrument_type=ExecutionInstrumentType(mapping.instrument_type),
        asset_class=ExecutionAssetClass(mapping.asset_class),
        quote_currency=mapping.quote_currency,
        tick_size=mapping.tick_size,
        point_size=mapping.point_size,
        lot_size=mapping.lot_size,
        multiplier=mapping.multiplier or Decimal("1"),
        price_precision=mapping.price_precision,
    )
