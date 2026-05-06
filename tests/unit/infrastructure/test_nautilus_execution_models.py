from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from nautilus_trader.model.enums import OrderSide as NautilusOrderSide
from nautilus_trader.model.enums import OrderType as NautilusOrderType
from nautilus_trader.model.objects import Price, Quantity

from backtest_engine.core.errors import InfrastructureError
from backtest_engine.core.types import JsonValue
from backtest_engine.domain.execution.commissions import (
    CommissionModel,
    FixedPerContractCommission,
    RateOfNotionalCommission,
    ResolvedExecutionCostProfile,
)
from backtest_engine.domain.execution.instrument_metadata import (
    ExecutionAssetClass,
    ExecutionInstrumentMetadata,
    ExecutionInstrumentType,
)
from backtest_engine.domain.execution.slippage import FixedTicksSlippage, NoneExplicitSlippage
from backtest_engine.domain.execution.spreads import (
    DynamicSpreadCalibrationProvenance,
    DynamicSpreadSessionBucket,
    LogLinearDynamicHalfSpread,
    SpreadModel,
    StaticHalfSpreadPrice,
)
from backtest_engine.infrastructure.nautilus.catalogs import _build_instrument
from backtest_engine.infrastructure.nautilus.dynamic_spread_features import (
    DynamicSpreadFeatureArtifactManifest,
    DynamicSpreadFeatureArtifactRef,
    compute_file_sha256,
)
from backtest_engine.infrastructure.nautilus.execution_models import (
    ExecutionPolicyFeeModel,
    ExecutionPolicyFillModel,
    ExecutionPolicyInstrumentProfile,
    ExecutionPolicyModelConfig,
)
from backtest_engine.infrastructure.nautilus.symbol_map import SymbolMapping, load_symbol_map


@dataclass(frozen=True)
class _FakeOrder:
    side: NautilusOrderSide
    order_type: NautilusOrderType
    quantity: Quantity
    ts_init: int = 0
    ts_last: int = 0


def test_execution_policy_fee_model_charges_rate_of_notional() -> None:
    instrument = _build_instrument(load_symbol_map().resolve("US500"))
    model = ExecutionPolicyFeeModel(
        config=_model_config(
            "US500",
            commission_model=RateOfNotionalCommission(commission_rate_bps=Decimal("100")),
        ),
    )

    commission = model.get_commission(
        order=None,
        fill_qty=Quantity.from_str("2"),
        fill_px=Price.from_str("100.00"),
        instrument=instrument,
    )

    assert commission.as_decimal() == Decimal("2.00")
    assert str(commission.currency) == "USD"


def test_execution_policy_fee_model_charges_fixed_per_contract() -> None:
    instrument = _build_instrument(load_symbol_map().resolve("ES"))
    model = ExecutionPolicyFeeModel(
        config=_model_config(
            "ES",
            commission_model=FixedPerContractCommission(
                amount_per_contract=Decimal("2.25"),
                currency="USD",
            ),
        ),
    )

    commission = model.get_commission(
        order=None,
        fill_qty=Quantity.from_str("3"),
        fill_px=Price.from_str("5000.00"),
        instrument=instrument,
    )

    assert commission.as_decimal() == Decimal("6.75")
    assert str(commission.currency) == "USD"


def test_execution_policy_fill_model_worsens_market_and_stop_prices() -> None:
    instrument = _build_instrument(load_symbol_map().resolve("US500"))
    model = ExecutionPolicyFillModel(
        config=_model_config(
            "US500",
            commission_model=RateOfNotionalCommission(commission_rate_bps=Decimal("100")),
            spread_model=StaticHalfSpreadPrice(half_spread_price=Decimal("0.50")),
            slippage_model=FixedTicksSlippage(slippage_ticks=Decimal("5")),
        ),
    )

    buy_book = model.get_orderbook_for_fill_simulation(
        instrument=instrument,
        order=_FakeOrder(
            side=NautilusOrderSide.BUY,
            order_type=NautilusOrderType.MARKET,
            quantity=Quantity.from_str("1"),
        ),
        best_bid=Price.from_str("100.00"),
        best_ask=Price.from_str("100.00"),
    )
    sell_book = model.get_orderbook_for_fill_simulation(
        instrument=instrument,
        order=_FakeOrder(
            side=NautilusOrderSide.SELL,
            order_type=NautilusOrderType.STOP_MARKET,
            quantity=Quantity.from_str("1"),
        ),
        best_bid=Price.from_str("100.00"),
        best_ask=Price.from_str("100.00"),
    )

    assert buy_book is not None
    assert sell_book is not None
    assert buy_book.best_ask_price().as_decimal() == Decimal("100.55")
    assert sell_book.best_bid_price().as_decimal() == Decimal("99.45")


def test_execution_policy_fill_model_sizes_synthetic_book_to_cover_large_orders() -> None:
    instrument = _build_instrument(load_symbol_map().resolve("US500"))
    model = ExecutionPolicyFillModel(
        config=_model_config(
            "US500",
            commission_model=RateOfNotionalCommission(commission_rate_bps=Decimal("100")),
            spread_model=StaticHalfSpreadPrice(half_spread_price=Decimal("0.50")),
            slippage_model=FixedTicksSlippage(slippage_ticks=Decimal("5")),
        ),
    )
    large_quantity = Quantity.from_str("1000001")

    book = model.get_orderbook_for_fill_simulation(
        instrument=instrument,
        order=_FakeOrder(
            side=NautilusOrderSide.BUY,
            order_type=NautilusOrderType.MARKET,
            quantity=large_quantity,
        ),
        best_bid=Price.from_str("100.00"),
        best_ask=Price.from_str("100.00"),
    )

    assert book is not None
    assert book.best_ask_size().as_decimal() == large_quantity.as_decimal()


def test_execution_policy_fill_model_leaves_limit_orders_on_default_path() -> None:
    instrument = _build_instrument(load_symbol_map().resolve("US500"))
    model = ExecutionPolicyFillModel(
        config=_model_config(
            "US500",
            commission_model=RateOfNotionalCommission(commission_rate_bps=Decimal("100")),
        ),
    )

    book = model.get_orderbook_for_fill_simulation(
        instrument=instrument,
        order=_FakeOrder(
            side=NautilusOrderSide.BUY,
            order_type=NautilusOrderType.LIMIT,
            quantity=Quantity.from_str("1"),
        ),
        best_bid=Price.from_str("100.00"),
        best_ask=Price.from_str("100.00"),
    )

    assert book is None


def test_execution_policy_fill_model_uses_dynamic_spread_features(tmp_path: Path) -> None:
    instrument = _build_instrument(load_symbol_map().resolve("US500"))
    feature_ref = _write_dynamic_feature_artifact(tmp_path, "US500.SIM")
    model = ExecutionPolicyFillModel(
        config=_model_config(
            "US500",
            commission_model=RateOfNotionalCommission(commission_rate_bps=Decimal("100")),
            spread_model=_dynamic_spread_model("US500", volatility_weight="1.0"),
            slippage_model=NoneExplicitSlippage(reason="unit_test"),
            dynamic_spread_features={"US500.SIM": feature_ref.as_config_payload()},
        ),
    )

    book = model.get_orderbook_for_fill_simulation(
        instrument=instrument,
        order=_FakeOrder(
            side=NautilusOrderSide.BUY,
            order_type=NautilusOrderType.MARKET,
            quantity=Quantity.from_str("1"),
            ts_init=_unix_ns(datetime(2024, 1, 1, 0, 30, tzinfo=timezone.utc)),
        ),
        best_bid=Price.from_str("100.00"),
        best_ask=Price.from_str("100.00"),
    )

    assert book is not None
    assert book.best_ask_price().as_decimal() == Decimal("101.00")


@pytest.mark.parametrize(
    "fill_timestamp_utc",
    (
        datetime(2024, 1, 1, 0, 31, tzinfo=timezone.utc),
        datetime(2024, 1, 1, 1, 0, tzinfo=timezone.utc),
    ),
)
def test_execution_policy_fill_model_rejects_dynamic_feature_timestamp_misses(
    tmp_path: Path,
    fill_timestamp_utc: datetime,
) -> None:
    instrument = _build_instrument(load_symbol_map().resolve("US500"))
    feature_ref = _write_dynamic_feature_artifact(tmp_path, "US500.SIM")
    model = ExecutionPolicyFillModel(
        config=_model_config(
            "US500",
            commission_model=RateOfNotionalCommission(commission_rate_bps=Decimal("100")),
            spread_model=_dynamic_spread_model("US500", volatility_weight="1.0"),
            slippage_model=NoneExplicitSlippage(reason="unit_test"),
            dynamic_spread_features={"US500.SIM": feature_ref.as_config_payload()},
        ),
    )

    with pytest.raises(InfrastructureError, match="no exact row for fill timestamp"):
        model.get_orderbook_for_fill_simulation(
            instrument=instrument,
            order=_FakeOrder(
                side=NautilusOrderSide.BUY,
                order_type=NautilusOrderType.MARKET,
                quantity=Quantity.from_str("1"),
                ts_init=_unix_ns(fill_timestamp_utc),
            ),
            best_bid=Price.from_str("100.00"),
            best_ask=Price.from_str("100.00"),
        )


def test_execution_policy_fill_model_leaves_dynamic_stops_on_default_path(
    tmp_path: Path,
) -> None:
    instrument = _build_instrument(load_symbol_map().resolve("US500"))
    feature_ref = _write_dynamic_feature_artifact(tmp_path, "US500.SIM")
    model = ExecutionPolicyFillModel(
        config=_model_config(
            "US500",
            commission_model=RateOfNotionalCommission(commission_rate_bps=Decimal("100")),
            spread_model=_dynamic_spread_model("US500", volatility_weight="1.0"),
            slippage_model=NoneExplicitSlippage(reason="unit_test"),
            dynamic_spread_features={"US500.SIM": feature_ref.as_config_payload()},
        ),
    )

    book = model.get_orderbook_for_fill_simulation(
        instrument=instrument,
        order=_FakeOrder(
            side=NautilusOrderSide.BUY,
            order_type=NautilusOrderType.STOP_MARKET,
            quantity=Quantity.from_str("1"),
            ts_init=_unix_ns(datetime(2024, 1, 1, 0, 30, tzinfo=timezone.utc)),
        ),
        best_bid=Price.from_str("100.00"),
        best_ask=Price.from_str("100.00"),
    )

    assert book is None


def test_execution_policy_fill_model_uses_only_market_ts_init_for_dynamic_features(
    tmp_path: Path,
) -> None:
    instrument = _build_instrument(load_symbol_map().resolve("US500"))
    feature_ref = _write_dynamic_feature_artifact(tmp_path, "US500.SIM")
    model = ExecutionPolicyFillModel(
        config=_model_config(
            "US500",
            commission_model=RateOfNotionalCommission(commission_rate_bps=Decimal("100")),
            spread_model=_dynamic_spread_model("US500", volatility_weight="1.0"),
            slippage_model=NoneExplicitSlippage(reason="unit_test"),
            dynamic_spread_features={"US500.SIM": feature_ref.as_config_payload()},
        ),
    )

    with pytest.raises(InfrastructureError, match="nonzero ts_init"):
        model.get_orderbook_for_fill_simulation(
            instrument=instrument,
            order=_FakeOrder(
                side=NautilusOrderSide.BUY,
                order_type=NautilusOrderType.MARKET,
                quantity=Quantity.from_str("1"),
                ts_init=0,
                ts_last=_unix_ns(datetime(2024, 1, 1, 0, 30, tzinfo=timezone.utc)),
            ),
            best_bid=Price.from_str("100.00"),
            best_ask=Price.from_str("100.00"),
        )


def test_execution_policy_fill_model_rejects_stale_dynamic_feature_manifest(
    tmp_path: Path,
) -> None:
    feature_ref = _write_dynamic_feature_artifact(tmp_path, "US500.SIM")
    feature_ref.manifest_path.write_text("{}", encoding="utf-8")

    with pytest.raises(InfrastructureError, match="manifest hash mismatch"):
        ExecutionPolicyFillModel(
            config=_model_config(
                "US500",
                commission_model=RateOfNotionalCommission(commission_rate_bps=Decimal("100")),
                spread_model=_dynamic_spread_model("US500", volatility_weight="1.0"),
                slippage_model=NoneExplicitSlippage(reason="unit_test"),
                dynamic_spread_features={"US500.SIM": feature_ref.as_config_payload()},
            ),
        )


def test_execution_policy_fill_model_rejects_stale_dynamic_feature_table(
    tmp_path: Path,
) -> None:
    feature_ref = _write_dynamic_feature_artifact(tmp_path, "US500.SIM")
    pd.DataFrame((_feature_row("2024-01-01T00:30:00Z", "0"),)).to_parquet(
        feature_ref.feature_table_path,
        index=False,
    )

    with pytest.raises(InfrastructureError, match="feature table hash mismatch"):
        ExecutionPolicyFillModel(
            config=_model_config(
                "US500",
                commission_model=RateOfNotionalCommission(commission_rate_bps=Decimal("100")),
                spread_model=_dynamic_spread_model("US500", volatility_weight="1.0"),
                slippage_model=NoneExplicitSlippage(reason="unit_test"),
                dynamic_spread_features={"US500.SIM": feature_ref.as_config_payload()},
            ),
        )


def test_execution_policy_fill_model_rejects_stale_observed_at_policy(
    tmp_path: Path,
) -> None:
    feature_ref = _write_dynamic_feature_artifact(tmp_path, "US500.SIM")
    manifest = DynamicSpreadFeatureArtifactManifest.model_validate_json(
        feature_ref.manifest_path.read_text(encoding="utf-8"),
    ).model_copy(update={"feature_observed_at_policy": "legacy_bar_open_policy"})
    feature_ref.manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    stale_policy_ref = feature_ref.model_copy(
        update={"manifest_hash": compute_file_sha256(feature_ref.manifest_path)},
    )

    with pytest.raises(InfrastructureError, match="observed-at policy mismatch"):
        ExecutionPolicyFillModel(
            config=_model_config(
                "US500",
                commission_model=RateOfNotionalCommission(commission_rate_bps=Decimal("100")),
                spread_model=_dynamic_spread_model("US500", volatility_weight="1.0"),
                slippage_model=NoneExplicitSlippage(reason="unit_test"),
                dynamic_spread_features={"US500.SIM": stale_policy_ref.as_config_payload()},
            ),
        )


def test_execution_policy_models_fail_fast_for_unknown_instrument_ids() -> None:
    us500_model = ExecutionPolicyFeeModel(
        config=_model_config(
            "US500",
            commission_model=RateOfNotionalCommission(commission_rate_bps=Decimal("100")),
        ),
    )
    es_instrument = _build_instrument(load_symbol_map().resolve("ES"))

    with pytest.raises(InfrastructureError, match="profile missing"):
        us500_model.get_commission(
            order=None,
            fill_qty=Quantity.from_str("1"),
            fill_px=Price.from_str("5000.00"),
            instrument=es_instrument,
        )


def test_execution_policy_models_fail_fast_for_unsupported_profile_shapes() -> None:
    bad_config = ExecutionPolicyModelConfig(
        instrument_profiles={
            "US500.SIM": {
                "instrument_id": "US500.SIM",
                "metadata": _metadata_payload(load_symbol_map().resolve("US500")),
                "profile": {
                    "symbol": "US500",
                    "instrument_type": "CFD",
                    "asset_class": "INDEX",
                    "quote_currency": "USD",
                    "commission_model": {"model": "per_share"},
                    "spread_model": {
                        "model": "static_half_spread_price",
                        "half_spread_price": "0.50",
                    },
                    "slippage_model": {"model": "fixed_ticks", "slippage_ticks": "5"},
                },
            },
        },
    )

    with pytest.raises(InfrastructureError, match="invalid execution policy model config"):
        ExecutionPolicyFeeModel(config=bad_config)


def _model_config(
    symbol: str,
    *,
    commission_model: CommissionModel,
    spread_model: SpreadModel | None = None,
    slippage_model: FixedTicksSlippage | NoneExplicitSlippage | None = None,
    dynamic_spread_features: dict[str, dict[str, JsonValue]] | None = None,
) -> ExecutionPolicyModelConfig:
    mapping = load_symbol_map().resolve(symbol)
    metadata = _metadata_from_mapping(mapping)
    profile = ResolvedExecutionCostProfile(
        symbol=mapping.mt5_symbol,
        instrument_type=ExecutionInstrumentType(mapping.instrument_type),
        asset_class=ExecutionAssetClass(mapping.asset_class),
        quote_currency=mapping.quote_currency,
        commission_model=commission_model,
        spread_model=spread_model or StaticHalfSpreadPrice(half_spread_price=Decimal("0.50")),
        slippage_model=slippage_model or FixedTicksSlippage(slippage_ticks=Decimal("5")),
    )
    instrument_profile = ExecutionPolicyInstrumentProfile(
        instrument_id=mapping.nautilus_instrument_id,
        metadata=metadata,
        profile=profile,
    )
    return ExecutionPolicyModelConfig(
        instrument_profiles={
            mapping.nautilus_instrument_id: instrument_profile.as_config_payload(),
        },
        dynamic_spread_features=dynamic_spread_features or {},
    )


def _dynamic_spread_model(symbol: str, *, volatility_weight: str) -> LogLinearDynamicHalfSpread:
    return LogLinearDynamicHalfSpread(
        base_half_spread_price=Decimal("0.50"),
        min_half_spread_price=Decimal("0.10"),
        max_half_spread_price=Decimal("2.00"),
        volatility_weight=Decimal(volatility_weight),
        liquidity_weight=Decimal("0"),
        session_buckets=(
            DynamicSpreadSessionBucket(
                session_bucket_id="regular",
                session_adjustment_log=Decimal("0"),
            ),
        ),
        provenance=DynamicSpreadCalibrationProvenance(
            symbol=symbol,
            venue="SIM",
            timeframe="30m",
            provider_or_broker="unit-test",
            sample_start_utc=datetime(2024, 1, 1, tzinfo=timezone.utc),
            sample_end_utc=datetime(2024, 1, 2, tzinfo=timezone.utc),
            row_count=2,
            data_quality_notes="fixture",
            sample_role="unit_test",
            estimator_method="manual",
            conversion_method="already_price_units",
        ),
    )


def _write_dynamic_feature_artifact(
    tmp_path: Path,
    instrument_id: str,
    *,
    rows: tuple[dict[str, object], ...] | None = None,
) -> DynamicSpreadFeatureArtifactRef:
    artifact_root = tmp_path / "dynamic_features"
    artifact_root.mkdir()
    feature_table_path = artifact_root / "features.parquet"
    manifest_path = artifact_root / "manifest.json"
    feature_rows = rows or (_feature_row("2024-01-01T00:30:00Z", "0.6931471805599453"),)
    pd.DataFrame(feature_rows).to_parquet(feature_table_path, index=False)
    feature_table_hash = compute_file_sha256(feature_table_path)
    manifest = DynamicSpreadFeatureArtifactManifest(
        dataset_id="unit-test-dataset",
        source_fingerprint="source-fingerprint",
        instrument_id=instrument_id,
        model_hash="model-hash",
        runtime_config_hash="runtime-config-hash",
        volatility_floor_price=Decimal("0.01"),
        volatility_signal_method="true_range_atr",
        dynamic_order_types=("market",),
        feature_table_path=Path("features.parquet"),
        feature_table_hash=feature_table_hash,
        row_count=len(feature_rows),
        first_fill_timestamp_utc=pd.Timestamp(
            str(feature_rows[0]["fill_timestamp_utc"]),
        ).to_pydatetime(),
        last_fill_timestamp_utc=pd.Timestamp(
            str(feature_rows[-1]["fill_timestamp_utc"]),
        ).to_pydatetime(),
    )
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    return DynamicSpreadFeatureArtifactRef(
        instrument_id=instrument_id,
        feature_table_path=feature_table_path,
        manifest_path=manifest_path,
        manifest_hash=compute_file_sha256(manifest_path),
        feature_table_hash=feature_table_hash,
        model_hash=manifest.model_hash,
        runtime_config_hash=manifest.runtime_config_hash,
        volatility_floor_price=manifest.volatility_floor_price,
        volatility_signal_method=manifest.volatility_signal_method,
        dynamic_order_types=manifest.dynamic_order_types,
    )


def _feature_row(fill_timestamp_utc: str, volatility_stress_signal: str) -> dict[str, object]:
    fill_timestamp = pd.Timestamp(fill_timestamp_utc).to_pydatetime()
    return {
        "fill_timestamp_utc": fill_timestamp,
        "feature_observed_at_utc": fill_timestamp - timedelta(minutes=30),
        "session_bucket_id": "regular",
        "volatility_stress_signal": volatility_stress_signal,
        "liquidity_stress_signal": "0",
        "liquidity_observed_volume": "10",
    }


def _unix_ns(value: datetime) -> int:
    return int(value.timestamp() * 1_000_000_000)


def _metadata_from_mapping(mapping: SymbolMapping) -> ExecutionInstrumentMetadata:
    if mapping.asset_class is None:
        raise AssertionError(f"mapping {mapping.mt5_symbol} must define asset_class")
    return ExecutionInstrumentMetadata.model_validate(_metadata_payload(mapping))


def _metadata_payload(mapping: SymbolMapping) -> dict[str, str | int]:
    if mapping.asset_class is None:
        raise AssertionError(f"mapping {mapping.mt5_symbol} must define asset_class")
    return {
        "symbol": mapping.mt5_symbol,
        "instrument_type": mapping.instrument_type,
        "asset_class": mapping.asset_class,
        "quote_currency": mapping.quote_currency,
        "tick_size": str(mapping.tick_size),
        "point_size": str(mapping.point_size),
        "lot_size": str(mapping.lot_size),
        "multiplier": str(mapping.multiplier or Decimal("1")),
        "price_precision": mapping.price_precision,
    }
