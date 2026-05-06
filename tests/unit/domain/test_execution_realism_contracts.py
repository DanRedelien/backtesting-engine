from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from backtest_engine.core.enums import OrderSide, OrderType
from backtest_engine.domain.execution.commissions import (
    CommissionModelName,
    CommissionModelPatch,
    CommissionPreviewInput,
    ExecutionCostProfilePatch,
    FixedPerContractCommission,
    RateOfNotionalCommission,
    ResolvedExecutionCostProfile,
    ZeroExplicitCommission,
    preview_commission,
    preview_commissions_for_legs,
    resolve_execution_cost_profile,
    resolve_execution_cost_profiles,
    validate_commission_model,
)
from backtest_engine.domain.execution.cost_preview import (
    ExecutionCostPreviewInput,
    ExecutionCostPreviewStatus,
    preview_execution_cost,
    preview_execution_costs_for_legs,
)
from backtest_engine.domain.execution.instrument_metadata import (
    ExecutionAssetClass,
    ExecutionInstrumentMetadata,
    ExecutionInstrumentType,
)
from backtest_engine.domain.execution.order_economics import (
    DefaultLiquidityRole,
    OrderPriceBehavior,
    classify_order_execution,
)
from backtest_engine.domain.execution.orders import OrderIntent
from backtest_engine.domain.execution.spreads import (
    BufferedStaticSpread,
    SpreadModelName,
    SpreadModelPatch,
    SpreadPreviewInput,
    SpreadPreviewStatus,
    StaticHalfSpreadPrice,
    StaticHalfSpreadTicks,
    calculate_half_spread_price,
    preview_spread,
    preview_spreads_for_legs,
    validate_spread_model,
)
from backtest_engine.domain.execution.slippage import (
    BpsOfPriceSlippage,
    FixedTicksSlippage,
    NoneExplicitSlippage,
    SlippageModelName,
    SlippageModelPatch,
    SlippagePreviewInput,
    SlippagePreviewStatus,
    calculate_slippage_price,
    preview_slippage,
    validate_slippage_model,
)


def test_stop_limit_order_type_serializes_as_stable_string() -> None:
    intent = OrderIntent(
        strategy_id="strategy-stop-limit",
        symbol="ES",
        side=OrderSide.BUY,
        order_type="stop_limit",
        quantity="1",
        stop_price="5000.25",
        limit_price="5000.50",
    )

    assert OrderType("stop_limit") is OrderType.STOP_LIMIT
    assert intent.order_type is OrderType.STOP_LIMIT
    assert intent.model_dump(mode="json")["order_type"] == "stop_limit"


def test_market_and_stop_are_market_like_taker_default() -> None:
    for order_type in (OrderType.MARKET, OrderType.STOP):
        contract = classify_order_execution(order_type)

        assert contract.is_market_like
        assert not contract.is_limit_like
        assert contract.price_behavior is OrderPriceBehavior.MARKET_LIKE
        assert contract.default_liquidity_role is DefaultLiquidityRole.TAKER
        assert not contract.passive_fill_requires_explicit_policy
        assert contract.adverse_slippage_allowed
        assert not contract.adverse_price_must_respect_limit


def test_limit_and_stop_limit_are_limit_like_without_passive_default() -> None:
    for order_type in (OrderType.LIMIT, OrderType.STOP_LIMIT):
        contract = classify_order_execution(order_type)

        assert contract.is_limit_like
        assert not contract.is_market_like
        assert contract.price_behavior is OrderPriceBehavior.LIMIT_LIKE
        assert contract.default_liquidity_role is DefaultLiquidityRole.TAKER
        assert contract.passive_fill_requires_explicit_policy
        assert not contract.adverse_slippage_allowed
        assert contract.adverse_price_must_respect_limit


def test_instrument_metadata_contract_coerces_and_validates_units() -> None:
    metadata = ExecutionInstrumentMetadata(
        symbol="ES",
        instrument_type=ExecutionInstrumentType.FUTURES,
        asset_class=ExecutionAssetClass.INDEX,
        quote_currency="usd",
        tick_size="0.25",
        point_size=0.25,
        lot_size=1,
        multiplier="50",
        price_precision=2,
    )

    assert metadata.quote_currency == "USD"
    assert metadata.tick_size == Decimal("0.25")
    assert metadata.point_size == Decimal("0.25")
    assert metadata.lot_size == Decimal("1")
    assert metadata.multiplier == Decimal("50")


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("tick_size", "0"),
        ("point_size", "-0.01"),
        ("lot_size", "0"),
        ("multiplier", "-1"),
    ),
)
def test_instrument_metadata_requires_positive_decimal_units(
    field_name: str,
    value: str,
) -> None:
    payload = {
        "symbol": "EURUSD",
        "instrument_type": ExecutionInstrumentType.CURRENCY_PAIR,
        "asset_class": ExecutionAssetClass.FX,
        "quote_currency": "USD",
        "tick_size": "0.00001",
        "point_size": "0.00001",
        "lot_size": "100000",
        "multiplier": "1",
        "price_precision": 5,
    }
    payload[field_name] = value

    with pytest.raises(ValidationError, match="must be positive"):
        ExecutionInstrumentMetadata.model_validate(payload)


def test_rate_of_notional_commission_model_requires_positive_bps() -> None:
    with pytest.raises(ValidationError, match="zero_explicit"):
        validate_commission_model(
            {"model": "rate_of_notional", "commission_rate_bps": "0"},
        )


def test_fixed_per_contract_commission_model_requires_amount_and_currency() -> None:
    model = validate_commission_model(
        {
            "model": "fixed_per_contract",
            "amount_per_contract": "2.25",
            "currency": "usd",
        },
    )

    assert isinstance(model, FixedPerContractCommission)
    assert model.amount_per_contract == Decimal("2.25")
    assert model.currency == "USD"


def test_spread_model_validation_requires_explicit_positive_units() -> None:
    with pytest.raises(ValidationError, match="half_spread_price must be positive"):
        validate_spread_model(
            {"model": "static_half_spread_price", "half_spread_price": "0"},
        )

    with pytest.raises(ValidationError, match="half_spread_ticks must be positive"):
        validate_spread_model(
            {"model": "static_half_spread_ticks", "half_spread_ticks": "-1"},
        )


def test_slippage_model_validation_requires_explicit_positive_units() -> None:
    with pytest.raises(ValidationError, match="slippage_ticks must be positive"):
        validate_slippage_model(
            {"model": "fixed_ticks", "slippage_ticks": "0"},
        )

    with pytest.raises(ValidationError, match="slippage_bps must be positive"):
        validate_slippage_model(
            {"model": "bps_of_price", "slippage_bps": "-1"},
        )

    with pytest.raises(ValidationError, match="reason"):
        validate_slippage_model({"model": "none_explicit"})


def test_missing_commission_model_does_not_resolve_to_implicit_zero_for_cfd() -> None:
    metadata = _execution_metadata(
        symbol="US500",
        instrument_type=ExecutionInstrumentType.CFD,
        asset_class=ExecutionAssetClass.INDEX,
        quote_currency="USD",
        lot_size="1",
        multiplier="1",
    )

    with pytest.raises(ValueError, match="zero_explicit"):
        resolve_execution_cost_profile(metadata, asset_class_default=None)


def test_missing_commission_model_does_not_resolve_to_implicit_zero_for_futures() -> None:
    metadata = _execution_metadata(
        symbol="ES",
        instrument_type=ExecutionInstrumentType.FUTURES,
        asset_class=ExecutionAssetClass.INDEX,
        quote_currency="USD",
        tick_size="0.25",
        point_size="0.25",
        lot_size="1",
        multiplier="50",
    )

    with pytest.raises(ValueError, match="zero_explicit"):
        resolve_execution_cost_profile(metadata, asset_class_default=None)


def test_missing_spread_model_does_not_resolve_to_implicit_zero() -> None:
    metadata = _execution_metadata(
        symbol="US500",
        instrument_type=ExecutionInstrumentType.CFD,
        asset_class=ExecutionAssetClass.INDEX,
        quote_currency="USD",
        lot_size="1",
        multiplier="1",
    )

    with pytest.raises(ValueError, match="no explicit spread model"):
        resolve_execution_cost_profile(
            metadata,
            ExecutionCostProfilePatch(
                commission_model=CommissionModelPatch(
                    model=CommissionModelName.RATE_OF_NOTIONAL,
                    commission_rate_bps="0.40",
                ),
            ),
        )


def test_missing_slippage_model_does_not_resolve_to_implicit_zero() -> None:
    metadata = _execution_metadata(
        symbol="US500",
        instrument_type=ExecutionInstrumentType.CFD,
        asset_class=ExecutionAssetClass.INDEX,
        quote_currency="USD",
        lot_size="1",
        multiplier="1",
    )

    with pytest.raises(ValueError, match="none_explicit"):
        resolve_execution_cost_profile(
            metadata,
            ExecutionCostProfilePatch(
                commission_model=CommissionModelPatch(
                    model=CommissionModelName.RATE_OF_NOTIONAL,
                    commission_rate_bps="0.40",
                ),
                spread_model=_static_price_spread_patch(),
            ),
        )


def test_zero_commission_requires_explicit_selected_model() -> None:
    metadata = _execution_metadata(
        symbol="US500",
        instrument_type=ExecutionInstrumentType.CFD,
        asset_class=ExecutionAssetClass.INDEX,
        quote_currency="USD",
        lot_size="1",
        multiplier="1",
    )

    profile = resolve_execution_cost_profile(
        metadata,
        ExecutionCostProfilePatch(
            commission_model=CommissionModelPatch(
                model=CommissionModelName.ZERO_EXPLICIT,
                reason="Broker promotional schedule explicitly charges no commission.",
            ),
            spread_model=_static_price_spread_patch(),
            slippage_model=_none_slippage_patch(),
        ),
    )
    preview = preview_commission(
        CommissionPreviewInput(
            metadata=metadata,
            profile=profile,
            quantity="3",
            price="5000",
        ),
    )

    assert isinstance(profile.commission_model, ZeroExplicitCommission)
    assert preview.commission_amount == Decimal("0")


def test_fixed_fee_currency_mismatch_raises_without_fx_conversion() -> None:
    with pytest.raises(ValidationError, match="FX conversion is not supported"):
        ResolvedExecutionCostProfile(
            symbol="ES",
            instrument_type=ExecutionInstrumentType.FUTURES,
            asset_class=ExecutionAssetClass.INDEX,
            quote_currency="USD",
            commission_model=FixedPerContractCommission(
                amount_per_contract="2.25",
                currency="EUR",
            ),
            spread_model=_static_price_spread_model(),
            slippage_model=_fixed_slippage_model(),
        )


def test_asset_class_default_and_symbol_override_resolve_complete_profiles() -> None:
    us500_metadata = _execution_metadata(
        symbol="US500",
        instrument_type=ExecutionInstrumentType.CFD,
        asset_class=ExecutionAssetClass.INDEX,
        quote_currency="USD",
        lot_size="1",
        multiplier="1",
    )
    es_metadata = _execution_metadata(
        symbol="ES",
        instrument_type=ExecutionInstrumentType.FUTURES,
        asset_class=ExecutionAssetClass.INDEX,
        quote_currency="USD",
        tick_size="0.25",
        point_size="0.25",
        lot_size="1",
        multiplier="50",
    )

    profiles = resolve_execution_cost_profiles(
        (us500_metadata, es_metadata),
        asset_class_defaults={
            ExecutionAssetClass.INDEX: ExecutionCostProfilePatch(
                commission_model=CommissionModelPatch(
                    model=CommissionModelName.RATE_OF_NOTIONAL,
                    commission_rate_bps="0.40",
                ),
                spread_model=_static_price_spread_patch("0.25"),
                slippage_model=SlippageModelPatch(
                    model=SlippageModelName.BPS_OF_PRICE,
                    slippage_bps="0.50",
                ),
            ),
        },
        symbol_overrides={
            "ES": ExecutionCostProfilePatch(
                commission_model=CommissionModelPatch(
                    model=CommissionModelName.FIXED_PER_CONTRACT,
                    amount_per_contract="2.25",
                    currency="USD",
                ),
                spread_model=SpreadModelPatch(
                    model=SpreadModelName.STATIC_HALF_SPREAD_TICKS,
                    half_spread_ticks="0.5",
                ),
                slippage_model=SlippageModelPatch(
                    model=SlippageModelName.FIXED_TICKS,
                    slippage_ticks="1",
                ),
            ),
        },
    )

    assert isinstance(profiles[0].commission_model, RateOfNotionalCommission)
    assert profiles[0].commission_model.commission_rate_bps == Decimal("0.40")
    assert isinstance(profiles[0].spread_model, StaticHalfSpreadPrice)
    assert profiles[0].spread_model.half_spread_price == Decimal("0.25")
    assert isinstance(profiles[1].commission_model, FixedPerContractCommission)
    assert profiles[1].commission_model.amount_per_contract == Decimal("2.25")
    assert isinstance(profiles[1].spread_model, StaticHalfSpreadTicks)
    assert profiles[1].spread_model.half_spread_ticks == Decimal("0.5")
    assert isinstance(profiles[0].slippage_model, BpsOfPriceSlippage)
    assert profiles[0].slippage_model.slippage_bps == Decimal("0.50")
    assert isinstance(profiles[1].slippage_model, FixedTicksSlippage)
    assert profiles[1].slippage_model.slippage_ticks == Decimal("1")


def test_symbol_override_can_override_inherited_commission_rate_field() -> None:
    metadata = _execution_metadata(
        symbol="EURUSD",
        instrument_type=ExecutionInstrumentType.CURRENCY_PAIR,
        asset_class=ExecutionAssetClass.FX,
        quote_currency="USD",
        tick_size="0.00001",
        point_size="0.00001",
        lot_size="100000",
        multiplier="1",
        price_precision=5,
    )

    profile = resolve_execution_cost_profile(
        metadata,
        ExecutionCostProfilePatch(
            commission_model=CommissionModelPatch(
                model=CommissionModelName.RATE_OF_NOTIONAL,
                commission_rate_bps="0.20",
            ),
            spread_model=_static_price_spread_patch(),
            slippage_model=_none_slippage_patch(),
        ),
        ExecutionCostProfilePatch(
            commission_model=CommissionModelPatch(commission_rate_bps="0.35"),
        ),
    )

    assert isinstance(profile.commission_model, RateOfNotionalCommission)
    assert profile.commission_model.commission_rate_bps == Decimal("0.35")


def test_rate_of_notional_uses_futures_multiplier_for_absolute_notional() -> None:
    metadata = _execution_metadata(
        symbol="ES",
        instrument_type=ExecutionInstrumentType.FUTURES,
        asset_class=ExecutionAssetClass.INDEX,
        quote_currency="USD",
        tick_size="0.25",
        point_size="0.25",
        lot_size="1",
        multiplier="50",
    )
    profile = ResolvedExecutionCostProfile(
        symbol="ES",
        instrument_type=ExecutionInstrumentType.FUTURES,
        asset_class=ExecutionAssetClass.INDEX,
        quote_currency="USD",
        commission_model=RateOfNotionalCommission(commission_rate_bps="1"),
        spread_model=_static_price_spread_model(),
        slippage_model=_fixed_slippage_model(),
    )

    preview = preview_commission(
        CommissionPreviewInput(
            metadata=metadata,
            profile=profile,
            quantity="2",
            price="5000",
        ),
    )

    assert preview.absolute_notional_amount == Decimal("500000")
    assert preview.commission_amount == Decimal("50")


def test_rate_of_notional_uses_cfd_lot_size_for_absolute_notional() -> None:
    metadata = _execution_metadata(
        symbol="XAUUSD",
        instrument_type=ExecutionInstrumentType.CFD,
        asset_class=ExecutionAssetClass.COMMODITY,
        quote_currency="USD",
        tick_size="0.01",
        point_size="0.01",
        lot_size="100",
        multiplier="1",
    )
    profile = ResolvedExecutionCostProfile(
        symbol="XAUUSD",
        instrument_type=ExecutionInstrumentType.CFD,
        asset_class=ExecutionAssetClass.COMMODITY,
        quote_currency="USD",
        commission_model=RateOfNotionalCommission(commission_rate_bps="2"),
        spread_model=_static_price_spread_model(),
        slippage_model=_fixed_slippage_model(),
    )

    preview = preview_commission(
        CommissionPreviewInput(
            metadata=metadata,
            profile=profile,
            quantity="1",
            price="2300",
        ),
    )

    assert preview.absolute_notional_amount == Decimal("230000")
    assert preview.commission_amount == Decimal("46")


def test_fixed_per_contract_uses_absolute_quantity_only() -> None:
    metadata = _execution_metadata(
        symbol="NQ",
        instrument_type=ExecutionInstrumentType.FUTURES,
        asset_class=ExecutionAssetClass.INDEX,
        quote_currency="USD",
        tick_size="0.25",
        point_size="0.25",
        lot_size="1",
        multiplier="20",
    )
    profile = ResolvedExecutionCostProfile(
        symbol="NQ",
        instrument_type=ExecutionInstrumentType.FUTURES,
        asset_class=ExecutionAssetClass.INDEX,
        quote_currency="USD",
        commission_model=FixedPerContractCommission(
            amount_per_contract="2.25",
            currency="USD",
        ),
        spread_model=_static_price_spread_model(),
        slippage_model=_fixed_slippage_model(),
    )

    preview = preview_commission(
        CommissionPreviewInput(
            metadata=metadata,
            profile=profile,
            quantity="-3",
            price="18000",
        ),
    )

    assert preview.commission_amount == Decimal("6.75")


def test_statarb_style_commission_preview_returns_per_leg_breakdown() -> None:
    es_metadata = _execution_metadata(
        symbol="ES",
        instrument_type=ExecutionInstrumentType.FUTURES,
        asset_class=ExecutionAssetClass.INDEX,
        quote_currency="USD",
        tick_size="0.25",
        point_size="0.25",
        lot_size="1",
        multiplier="50",
    )
    nq_metadata = _execution_metadata(
        symbol="NQ",
        instrument_type=ExecutionInstrumentType.FUTURES,
        asset_class=ExecutionAssetClass.INDEX,
        quote_currency="USD",
        tick_size="0.25",
        point_size="0.25",
        lot_size="1",
        multiplier="20",
    )
    es_profile = ResolvedExecutionCostProfile(
        symbol="ES",
        instrument_type=ExecutionInstrumentType.FUTURES,
        asset_class=ExecutionAssetClass.INDEX,
        quote_currency="USD",
        commission_model=FixedPerContractCommission(
            amount_per_contract="2.25",
            currency="USD",
        ),
        spread_model=_static_price_spread_model("0.125"),
        slippage_model=_fixed_slippage_model(),
    )
    nq_profile = ResolvedExecutionCostProfile(
        symbol="NQ",
        instrument_type=ExecutionInstrumentType.FUTURES,
        asset_class=ExecutionAssetClass.INDEX,
        quote_currency="USD",
        commission_model=FixedPerContractCommission(
            amount_per_contract="2.25",
            currency="USD",
        ),
        spread_model=_static_price_spread_model("0.125"),
        slippage_model=_fixed_slippage_model(),
    )

    previews = preview_commissions_for_legs(
        (
            CommissionPreviewInput(
                metadata=es_metadata,
                profile=es_profile,
                quantity="1",
                price="5000",
            ),
            CommissionPreviewInput(
                metadata=nq_metadata,
                profile=nq_profile,
                quantity="-2",
                price="18000",
            ),
        ),
    )

    assert tuple(preview.symbol for preview in previews) == ("ES", "NQ")
    assert tuple(preview.commission_amount for preview in previews) == (
        Decimal("2.25"),
        Decimal("4.50"),
    )


def test_static_half_spread_price_adjusts_buy_and_sell_adversely() -> None:
    metadata = _execution_metadata(
        symbol="EURUSD",
        instrument_type=ExecutionInstrumentType.CURRENCY_PAIR,
        asset_class=ExecutionAssetClass.FX,
        quote_currency="USD",
        tick_size="0.00001",
        point_size="0.00001",
        lot_size="100000",
        multiplier="1",
        price_precision=5,
    )
    model = StaticHalfSpreadPrice(half_spread_price="0.00005")

    buy_preview = preview_spread(
        SpreadPreviewInput(
            metadata=metadata,
            spread_model=model,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            reference_price="1.10000",
        ),
    )
    sell_preview = preview_spread(
        SpreadPreviewInput(
            metadata=metadata,
            spread_model=model,
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            reference_price="1.10000",
        ),
    )

    assert buy_preview.status is SpreadPreviewStatus.APPLIED
    assert buy_preview.effective_price == Decimal("1.10005")
    assert buy_preview.signed_adjustment_price == Decimal("0.00005")
    assert sell_preview.status is SpreadPreviewStatus.APPLIED
    assert sell_preview.effective_price == Decimal("1.09995")
    assert sell_preview.signed_adjustment_price == Decimal("-0.00005")


def test_static_half_spread_ticks_uses_instrument_tick_size() -> None:
    metadata = _execution_metadata(
        symbol="ES",
        instrument_type=ExecutionInstrumentType.FUTURES,
        asset_class=ExecutionAssetClass.INDEX,
        quote_currency="USD",
        tick_size="0.25",
        point_size="0.25",
        lot_size="1",
        multiplier="50",
    )
    model = validate_spread_model(
        {"model": "static_half_spread_ticks", "half_spread_ticks": "2"},
    )

    preview = preview_spread(
        SpreadPreviewInput(
            metadata=metadata,
            spread_model=model,
            side=OrderSide.BUY,
            order_type=OrderType.STOP,
            reference_price="5000",
        ),
    )

    assert calculate_half_spread_price(metadata, model) == Decimal("0.50")
    assert preview.status is SpreadPreviewStatus.APPLIED
    assert preview.effective_price == Decimal("5000.50")


def test_buffered_static_spread_applies_explicit_positive_multiplier() -> None:
    metadata = _execution_metadata(
        symbol="BTCUSD",
        instrument_type=ExecutionInstrumentType.CFD,
        asset_class=ExecutionAssetClass.CRYPTOCURRENCY,
        quote_currency="USD",
        tick_size="0.01",
        point_size="0.01",
        lot_size="1",
        multiplier="1",
    )
    model = validate_spread_model(
        {
            "model": "buffered_static_spread",
            "base_half_spread_price": "10.00",
            "buffer_multiplier": "1.5",
        },
    )

    assert isinstance(model, BufferedStaticSpread)
    assert calculate_half_spread_price(metadata, model) == Decimal("15.000")

    with pytest.raises(ValidationError, match="buffer_multiplier must be positive"):
        validate_spread_model(
            {
                "model": "buffered_static_spread",
                "base_half_spread_price": "10.00",
                "buffer_multiplier": "0",
            },
        )


def test_limit_order_blocks_adverse_buy_spread_beyond_limit() -> None:
    metadata = _execution_metadata(
        symbol="US500",
        instrument_type=ExecutionInstrumentType.CFD,
        asset_class=ExecutionAssetClass.INDEX,
        quote_currency="USD",
        lot_size="1",
        multiplier="1",
    )

    preview = preview_spread(
        SpreadPreviewInput(
            metadata=metadata,
            spread_model=StaticHalfSpreadPrice(half_spread_price="0.10"),
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            reference_price="5000.00",
            limit_price="5000.05",
        ),
    )

    assert preview.status is SpreadPreviewStatus.BLOCKED_BY_LIMIT
    assert preview.candidate_effective_price == Decimal("5000.10")
    assert preview.effective_price is None
    assert preview.protection_reason is not None
    assert "exceeds limit price" in preview.protection_reason


def test_stop_limit_blocks_adverse_sell_spread_beyond_limit() -> None:
    metadata = _execution_metadata(
        symbol="US500",
        instrument_type=ExecutionInstrumentType.CFD,
        asset_class=ExecutionAssetClass.INDEX,
        quote_currency="USD",
        lot_size="1",
        multiplier="1",
    )

    preview = preview_spread(
        SpreadPreviewInput(
            metadata=metadata,
            spread_model=StaticHalfSpreadPrice(half_spread_price="0.10"),
            side=OrderSide.SELL,
            order_type=OrderType.STOP_LIMIT,
            reference_price="5000.00",
            limit_price="4999.95",
        ),
    )

    assert preview.status is SpreadPreviewStatus.BLOCKED_BY_LIMIT
    assert preview.candidate_effective_price == Decimal("4999.90")
    assert preview.effective_price is None
    assert preview.protection_reason is not None
    assert "is below limit price" in preview.protection_reason


def test_limit_order_applies_spread_when_adjustment_respects_limit() -> None:
    metadata = _execution_metadata(
        symbol="US500",
        instrument_type=ExecutionInstrumentType.CFD,
        asset_class=ExecutionAssetClass.INDEX,
        quote_currency="USD",
        lot_size="1",
        multiplier="1",
    )

    preview = preview_spread(
        SpreadPreviewInput(
            metadata=metadata,
            spread_model=StaticHalfSpreadPrice(half_spread_price="0.10"),
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            reference_price="5000.00",
            limit_price="5000.10",
        ),
    )

    assert preview.status is SpreadPreviewStatus.APPLIED
    assert preview.effective_price == Decimal("5000.10")


def test_limit_like_spread_preview_requires_limit_price() -> None:
    metadata = _execution_metadata(
        symbol="US500",
        instrument_type=ExecutionInstrumentType.CFD,
        asset_class=ExecutionAssetClass.INDEX,
        quote_currency="USD",
        lot_size="1",
        multiplier="1",
    )

    with pytest.raises(ValueError, match="limit_price is required"):
        preview_spread(
            SpreadPreviewInput(
                metadata=metadata,
                spread_model=StaticHalfSpreadPrice(half_spread_price="0.10"),
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                reference_price="5000.00",
            ),
        )


def test_statarb_style_spread_preview_returns_per_leg_breakdown() -> None:
    es_metadata = _execution_metadata(
        symbol="ES",
        instrument_type=ExecutionInstrumentType.FUTURES,
        asset_class=ExecutionAssetClass.INDEX,
        quote_currency="USD",
        tick_size="0.25",
        point_size="0.25",
        lot_size="1",
        multiplier="50",
    )
    nq_metadata = _execution_metadata(
        symbol="NQ",
        instrument_type=ExecutionInstrumentType.FUTURES,
        asset_class=ExecutionAssetClass.INDEX,
        quote_currency="USD",
        tick_size="0.25",
        point_size="0.25",
        lot_size="1",
        multiplier="20",
    )

    previews = preview_spreads_for_legs(
        (
            SpreadPreviewInput(
                metadata=es_metadata,
                spread_model=StaticHalfSpreadTicks(half_spread_ticks="0.5"),
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                reference_price="5000",
            ),
            SpreadPreviewInput(
                metadata=nq_metadata,
                spread_model=StaticHalfSpreadTicks(half_spread_ticks="1"),
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                reference_price="18000",
            ),
        ),
    )

    assert tuple(preview.symbol for preview in previews) == ("ES", "NQ")
    assert tuple(preview.effective_price for preview in previews) == (
        Decimal("5000.125"),
        Decimal("17999.75"),
    )


def test_fixed_ticks_slippage_uses_instrument_tick_size() -> None:
    metadata = _execution_metadata(
        symbol="ES",
        instrument_type=ExecutionInstrumentType.FUTURES,
        asset_class=ExecutionAssetClass.INDEX,
        quote_currency="USD",
        tick_size="0.25",
        point_size="0.25",
        lot_size="1",
        multiplier="50",
    )
    model = validate_slippage_model(
        {"model": "fixed_ticks", "slippage_ticks": "2"},
    )

    preview = preview_slippage(
        SlippagePreviewInput(
            metadata=metadata,
            slippage_model=model,
            side=OrderSide.BUY,
            order_type=OrderType.STOP,
            price_base="5000",
        ),
    )

    assert calculate_slippage_price(metadata, model, "5000") == Decimal("0.50")
    assert preview.status is SlippagePreviewStatus.APPLIED
    assert preview.effective_price == Decimal("5000.50")


def test_slippage_adjusts_buy_and_sell_adversely() -> None:
    metadata = _execution_metadata(
        symbol="EURUSD",
        instrument_type=ExecutionInstrumentType.CURRENCY_PAIR,
        asset_class=ExecutionAssetClass.FX,
        quote_currency="USD",
        tick_size="0.00001",
        point_size="0.00001",
        lot_size="100000",
        multiplier="1",
        price_precision=5,
    )
    model = FixedTicksSlippage(slippage_ticks="5")

    buy_preview = preview_slippage(
        SlippagePreviewInput(
            metadata=metadata,
            slippage_model=model,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            price_base="1.10000",
        ),
    )
    sell_preview = preview_slippage(
        SlippagePreviewInput(
            metadata=metadata,
            slippage_model=model,
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            price_base="1.10000",
        ),
    )

    assert buy_preview.effective_price == Decimal("1.10005")
    assert buy_preview.signed_adjustment_price == Decimal("0.00005")
    assert sell_preview.effective_price == Decimal("1.09995")
    assert sell_preview.signed_adjustment_price == Decimal("-0.00005")


def test_bps_slippage_uses_positive_price_base() -> None:
    metadata = _execution_metadata(
        symbol="BTCUSD",
        instrument_type=ExecutionInstrumentType.CFD,
        asset_class=ExecutionAssetClass.CRYPTOCURRENCY,
        quote_currency="USD",
        tick_size="0.01",
        point_size="0.01",
        lot_size="1",
        multiplier="1",
    )
    model = BpsOfPriceSlippage(slippage_bps="2.5")

    preview = preview_slippage(
        SlippagePreviewInput(
            metadata=metadata,
            slippage_model=model,
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            price_base="100.00",
        ),
    )

    assert calculate_slippage_price(metadata, model, "100.00") == Decimal("0.02500")
    assert preview.effective_price == Decimal("99.97500")

    with pytest.raises(ValueError, match="price_base must be positive"):
        calculate_slippage_price(metadata, model, "0")


def test_none_explicit_slippage_is_a_selected_zero_model() -> None:
    metadata = _execution_metadata(
        symbol="US500",
        instrument_type=ExecutionInstrumentType.CFD,
        asset_class=ExecutionAssetClass.INDEX,
        quote_currency="USD",
        lot_size="1",
        multiplier="1",
    )
    model = NoneExplicitSlippage(reason="Execution venue reports no extra slippage model.")

    preview = preview_slippage(
        SlippagePreviewInput(
            metadata=metadata,
            slippage_model=model,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            price_base="5000.00",
        ),
    )

    assert preview.status is SlippagePreviewStatus.NONE_EXPLICIT
    assert preview.adverse_slippage_applied is False
    assert preview.effective_price == Decimal("5000.00")


@pytest.mark.parametrize("order_type", (OrderType.LIMIT, OrderType.STOP_LIMIT))
def test_limit_like_orders_receive_zero_adverse_slippage(order_type: OrderType) -> None:
    metadata = _execution_metadata(
        symbol="US500",
        instrument_type=ExecutionInstrumentType.CFD,
        asset_class=ExecutionAssetClass.INDEX,
        quote_currency="USD",
        lot_size="1",
        multiplier="1",
    )

    preview = preview_slippage(
        SlippagePreviewInput(
            metadata=metadata,
            slippage_model=FixedTicksSlippage(slippage_ticks="10"),
            side=OrderSide.BUY,
            order_type=order_type,
            price_base="5000.00",
            limit_price="5000.00",
        ),
    )

    assert preview.status is SlippagePreviewStatus.ZERO_LIMIT_PROTECTED
    assert preview.slippage_price == Decimal("0")
    assert preview.signed_adjustment_price == Decimal("0")
    assert preview.effective_price == Decimal("5000.00")


def test_combined_preview_applies_market_and_stop_spread_slippage_then_commission() -> None:
    metadata = _execution_metadata(
        symbol="US500",
        instrument_type=ExecutionInstrumentType.CFD,
        asset_class=ExecutionAssetClass.INDEX,
        quote_currency="USD",
        tick_size="0.01",
        point_size="0.01",
        lot_size="1",
        multiplier="1",
    )
    profile = _rate_cost_profile(
        metadata=metadata,
        commission_rate_bps="100",
        spread_model=StaticHalfSpreadPrice(half_spread_price="0.50"),
        slippage_model=FixedTicksSlippage(slippage_ticks="5"),
    )

    market_preview = preview_execution_cost(
        ExecutionCostPreviewInput(
            metadata=metadata,
            profile=profile,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity="2",
            reference_price="100.00",
        ),
    )
    stop_preview = preview_execution_cost(
        ExecutionCostPreviewInput(
            metadata=metadata,
            profile=profile,
            side=OrderSide.SELL,
            order_type=OrderType.STOP,
            quantity="-2",
            reference_price="100.00",
        ),
    )

    assert market_preview.status is ExecutionCostPreviewStatus.APPLIED
    assert market_preview.final_effective_price == Decimal("100.55")
    assert market_preview.commission_preview is not None
    assert market_preview.commission_preview.price == Decimal("100.55")
    assert market_preview.commission_preview.commission_amount == Decimal("2.0110")
    assert stop_preview.status is ExecutionCostPreviewStatus.APPLIED
    assert stop_preview.final_effective_price == Decimal("99.45")
    assert stop_preview.commission_preview is not None
    assert stop_preview.commission_preview.price == Decimal("99.45")
    assert stop_preview.commission_preview.commission_amount == Decimal("1.9890")


@pytest.mark.parametrize(
    ("order_type", "side", "limit_price", "expected_price"),
    (
        (OrderType.LIMIT, OrderSide.BUY, "100.05", Decimal("100.05")),
        (OrderType.STOP_LIMIT, OrderSide.SELL, "99.95", Decimal("99.95")),
    ),
)
def test_combined_preview_keeps_limit_like_orders_inside_limit_price(
    order_type: OrderType,
    side: OrderSide,
    limit_price: str,
    expected_price: Decimal,
) -> None:
    metadata = _execution_metadata(
        symbol="US500",
        instrument_type=ExecutionInstrumentType.CFD,
        asset_class=ExecutionAssetClass.INDEX,
        quote_currency="USD",
        tick_size="0.01",
        point_size="0.01",
        lot_size="1",
        multiplier="1",
    )
    profile = _rate_cost_profile(
        metadata=metadata,
        commission_rate_bps="100",
        spread_model=StaticHalfSpreadPrice(half_spread_price="0.05"),
        slippage_model=FixedTicksSlippage(slippage_ticks="10"),
    )

    preview = preview_execution_cost(
        ExecutionCostPreviewInput(
            metadata=metadata,
            profile=profile,
            side=side,
            order_type=order_type,
            quantity="1",
            reference_price="100.00",
            limit_price=limit_price,
        ),
    )

    assert preview.status is ExecutionCostPreviewStatus.APPLIED
    assert preview.final_effective_price == expected_price
    assert preview.slippage_preview is not None
    assert preview.slippage_preview.status is SlippagePreviewStatus.ZERO_LIMIT_PROTECTED
    assert preview.slippage_preview.signed_adjustment_price == Decimal("0")
    assert preview.commission_preview is not None
    assert preview.commission_preview.price == expected_price


def test_combined_preview_stops_when_spread_is_blocked_by_limit() -> None:
    metadata = _execution_metadata(
        symbol="US500",
        instrument_type=ExecutionInstrumentType.CFD,
        asset_class=ExecutionAssetClass.INDEX,
        quote_currency="USD",
        lot_size="1",
        multiplier="1",
    )
    profile = _rate_cost_profile(
        metadata=metadata,
        commission_rate_bps="100",
        spread_model=StaticHalfSpreadPrice(half_spread_price="0.10"),
        slippage_model=FixedTicksSlippage(slippage_ticks="10"),
    )

    preview = preview_execution_cost(
        ExecutionCostPreviewInput(
            metadata=metadata,
            profile=profile,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity="1",
            reference_price="100.00",
            limit_price="100.05",
        ),
    )

    assert preview.status is ExecutionCostPreviewStatus.BLOCKED_BY_LIMIT
    assert preview.final_effective_price is None
    assert preview.spread_preview.status is SpreadPreviewStatus.BLOCKED_BY_LIMIT
    assert preview.slippage_preview is None
    assert preview.commission_preview is None


def test_statarb_style_combined_preview_returns_per_leg_breakdown() -> None:
    es_metadata = _execution_metadata(
        symbol="ES",
        instrument_type=ExecutionInstrumentType.FUTURES,
        asset_class=ExecutionAssetClass.INDEX,
        quote_currency="USD",
        tick_size="0.25",
        point_size="0.25",
        lot_size="1",
        multiplier="50",
    )
    nq_metadata = _execution_metadata(
        symbol="NQ",
        instrument_type=ExecutionInstrumentType.FUTURES,
        asset_class=ExecutionAssetClass.INDEX,
        quote_currency="USD",
        tick_size="0.25",
        point_size="0.25",
        lot_size="1",
        multiplier="20",
    )
    es_profile = ResolvedExecutionCostProfile(
        symbol="ES",
        instrument_type=ExecutionInstrumentType.FUTURES,
        asset_class=ExecutionAssetClass.INDEX,
        quote_currency="USD",
        commission_model=FixedPerContractCommission(
            amount_per_contract="2.25",
            currency="USD",
        ),
        spread_model=StaticHalfSpreadTicks(half_spread_ticks="0.5"),
        slippage_model=FixedTicksSlippage(slippage_ticks="1"),
    )
    nq_profile = ResolvedExecutionCostProfile(
        symbol="NQ",
        instrument_type=ExecutionInstrumentType.FUTURES,
        asset_class=ExecutionAssetClass.INDEX,
        quote_currency="USD",
        commission_model=FixedPerContractCommission(
            amount_per_contract="2.25",
            currency="USD",
        ),
        spread_model=StaticHalfSpreadTicks(half_spread_ticks="1"),
        slippage_model=FixedTicksSlippage(slippage_ticks="1"),
    )

    previews = preview_execution_costs_for_legs(
        (
            ExecutionCostPreviewInput(
                metadata=es_metadata,
                profile=es_profile,
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity="1",
                reference_price="5000",
            ),
            ExecutionCostPreviewInput(
                metadata=nq_metadata,
                profile=nq_profile,
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                quantity="-2",
                reference_price="18000",
            ),
        ),
    )

    assert tuple(preview.symbol for preview in previews) == ("ES", "NQ")
    assert tuple(preview.final_effective_price for preview in previews) == (
        Decimal("5000.375"),
        Decimal("17999.50"),
    )
    assert tuple(
        preview.commission_preview.commission_amount
        for preview in previews
        if preview.commission_preview is not None
    ) == (Decimal("2.25"), Decimal("4.50"))


def _execution_metadata(
    *,
    symbol: str,
    instrument_type: ExecutionInstrumentType,
    asset_class: ExecutionAssetClass,
    quote_currency: str,
    tick_size: str = "0.01",
    point_size: str = "0.01",
    lot_size: str,
    multiplier: str,
    price_precision: int = 2,
) -> ExecutionInstrumentMetadata:
    return ExecutionInstrumentMetadata(
        symbol=symbol,
        instrument_type=instrument_type,
        asset_class=asset_class,
        quote_currency=quote_currency,
        tick_size=tick_size,
        point_size=point_size,
        lot_size=lot_size,
        multiplier=multiplier,
        price_precision=price_precision,
    )


def _static_price_spread_model(half_spread_price: str = "0.01") -> StaticHalfSpreadPrice:
    return StaticHalfSpreadPrice(half_spread_price=half_spread_price)


def _static_price_spread_patch(half_spread_price: str = "0.01") -> SpreadModelPatch:
    return SpreadModelPatch(
        model=SpreadModelName.STATIC_HALF_SPREAD_PRICE,
        half_spread_price=half_spread_price,
    )


def _fixed_slippage_model(slippage_ticks: str = "1") -> FixedTicksSlippage:
    return FixedTicksSlippage(slippage_ticks=slippage_ticks)


def _none_slippage_patch() -> SlippageModelPatch:
    return SlippageModelPatch(
        model=SlippageModelName.NONE_EXPLICIT,
        reason="Explicit deterministic preview with no additional slippage.",
    )


def _rate_cost_profile(
    *,
    metadata: ExecutionInstrumentMetadata,
    commission_rate_bps: str,
    spread_model: StaticHalfSpreadPrice,
    slippage_model: FixedTicksSlippage,
) -> ResolvedExecutionCostProfile:
    return ResolvedExecutionCostProfile(
        symbol=metadata.symbol,
        instrument_type=metadata.instrument_type,
        asset_class=metadata.asset_class,
        quote_currency=metadata.quote_currency,
        commission_model=RateOfNotionalCommission(commission_rate_bps=commission_rate_bps),
        spread_model=spread_model,
        slippage_model=slippage_model,
    )
