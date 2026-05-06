from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from backtest_engine.core.enums import OrderSide, OrderType
from backtest_engine.domain.execution.instrument_metadata import (
    ExecutionAssetClass,
    ExecutionInstrumentMetadata,
    ExecutionInstrumentType,
)
from backtest_engine.domain.execution.commissions import (
    RateOfNotionalCommission,
    ResolvedExecutionCostProfile,
)
from backtest_engine.domain.execution.cost_preview import (
    ExecutionCostPreviewInput,
    ExecutionCostPreviewStatus,
    preview_execution_cost,
)
from backtest_engine.domain.execution.slippage import FixedTicksSlippage
from backtest_engine.domain.execution.spreads import (
    DynamicSpreadBlockedReason,
    DynamicSpreadCalibrationProvenance,
    DynamicSpreadEvaluationStatus,
    DynamicSpreadFeatureInput,
    DynamicSpreadSessionBucket,
    LogLinearDynamicHalfSpread,
    SpreadModelName,
    SpreadPreviewInput,
    SpreadPreviewStatus,
    StaticHalfSpreadPrice,
    calculate_half_spread_price,
    evaluate_dynamic_half_spread,
    preview_spread,
    validate_spread_model,
)


def test_log_linear_dynamic_half_spread_formula_uses_precomputed_stress_signals() -> None:
    model = _dynamic_model(
        base_half_spread_price="1",
        min_half_spread_price="0.50",
        max_half_spread_price="20",
        volatility_weight="0.50",
        liquidity_weight="0.25",
        session_adjustment_log="0.10",
    )

    evaluation = evaluate_dynamic_half_spread(
        model,
        _features(volatility_stress_signal="2", liquidity_stress_signal="4"),
    )

    assert evaluation.status is DynamicSpreadEvaluationStatus.APPLIED
    assert evaluation.log_effective_half_spread == Decimal("2.10")
    assert evaluation.volatility_contribution_log == Decimal("1.00")
    assert evaluation.liquidity_contribution_log == Decimal("1.00")
    assert evaluation.effective_half_spread_price is not None
    assert float(evaluation.effective_half_spread_price) == pytest.approx(8.1661699)


def test_dynamic_half_spread_is_widen_only_for_negative_raw_signals() -> None:
    model = _dynamic_model(
        base_half_spread_price="0.25",
        min_half_spread_price="0.10",
        max_half_spread_price="2.00",
        volatility_weight="1.00",
        liquidity_weight="1.00",
        session_adjustment_log="0",
    )

    evaluation = evaluate_dynamic_half_spread(
        model,
        _features(volatility_stress_signal="-10", liquidity_stress_signal="-5"),
    )

    assert evaluation.status is DynamicSpreadEvaluationStatus.APPLIED
    assert evaluation.volatility_stress_signal == Decimal("0")
    assert evaluation.liquidity_stress_signal == Decimal("0")
    assert evaluation.effective_half_spread_price == Decimal("0.25")


def test_dynamic_half_spread_saturates_before_huge_finite_signal_multiplication() -> None:
    model = _dynamic_model(
        base_half_spread_price="1",
        min_half_spread_price="0.50",
        max_half_spread_price="2",
        volatility_weight="1",
        liquidity_weight="0",
        session_adjustment_log="0",
    )

    evaluation = evaluate_dynamic_half_spread(
        model,
        _features(volatility_stress_signal="1E+1000000", liquidity_stress_signal=None),
    )

    assert evaluation.status is DynamicSpreadEvaluationStatus.APPLIED
    assert evaluation.effective_half_spread_price == Decimal("2")


def test_dynamic_half_spread_saturates_before_huge_session_adjustment_arithmetic() -> None:
    model = _dynamic_model(
        base_half_spread_price="1",
        min_half_spread_price="0.50",
        max_half_spread_price="2",
        volatility_weight="0",
        liquidity_weight="0",
        session_adjustment_log="1E+1000000",
    )

    evaluation = evaluate_dynamic_half_spread(
        model,
        _features(volatility_stress_signal=None, liquidity_stress_signal=None),
    )

    assert evaluation.status is DynamicSpreadEvaluationStatus.APPLIED
    assert evaluation.effective_half_spread_price == Decimal("2")


def test_dynamic_half_spread_tiny_weights_do_not_overflow_cap_comparison() -> None:
    model = _dynamic_model(
        base_half_spread_price="1",
        min_half_spread_price="0.50",
        max_half_spread_price="2",
        volatility_weight="1E-1000001",
        liquidity_weight="0",
        session_adjustment_log="0",
    )

    evaluation = evaluate_dynamic_half_spread(
        model,
        _features(volatility_stress_signal="1", liquidity_stress_signal=None),
    )

    assert evaluation.status is DynamicSpreadEvaluationStatus.APPLIED
    assert evaluation.effective_half_spread_price is not None
    assert evaluation.effective_half_spread_price >= Decimal("1")
    assert evaluation.effective_half_spread_price < Decimal("2")


def test_dynamic_spread_model_validates_bounds_weights_sessions_and_provenance() -> None:
    payload = _dynamic_model_payload()
    model = validate_spread_model(payload)

    assert isinstance(model, LogLinearDynamicHalfSpread)
    assert model.model == SpreadModelName.LOG_LINEAR_DYNAMIC_HALF_SPREAD.value

    missing_provenance = dict(payload)
    missing_provenance.pop("provenance")
    with pytest.raises(ValidationError, match="provenance"):
        validate_spread_model(missing_provenance)

    invalid_bounds = dict(payload, min_half_spread_price="2.00")
    with pytest.raises(ValidationError, match="min_half_spread_price"):
        validate_spread_model(invalid_bounds)

    negative_weight = dict(payload, volatility_weight="-0.01")
    with pytest.raises(ValidationError, match="non-negative"):
        validate_spread_model(negative_weight)

    duplicate_sessions = dict(
        payload,
        session_buckets=[
            {"session_bucket_id": "regular", "session_adjustment_log": "0"},
            {"session_bucket_id": "regular", "session_adjustment_log": "0.10"},
        ],
    )
    with pytest.raises(ValidationError, match="unique"):
        validate_spread_model(duplicate_sessions)


def test_dynamic_spread_feature_timestamps_must_be_utc_and_strictly_before_fill() -> None:
    with pytest.raises(ValidationError, match="timezone-aware UTC"):
        _features(feature_observed_at_utc=datetime(2024, 1, 2, 9, 45))

    with pytest.raises(ValidationError, match="must be UTC"):
        _features(
            feature_observed_at_utc=datetime(
                2024,
                1,
                2,
                11,
                45,
                tzinfo=timezone(timedelta(hours=2)),
            ),
        )

    with pytest.raises(ValidationError, match="before fill_timestamp_utc"):
        _features(
            fill_timestamp_utc=datetime(2024, 1, 2, 10, tzinfo=timezone.utc),
            feature_observed_at_utc=datetime(2024, 1, 2, 10, tzinfo=timezone.utc),
        )


def test_dynamic_evaluation_blocks_missing_dynamic_features() -> None:
    evaluation = evaluate_dynamic_half_spread(_dynamic_model(), None)

    assert evaluation.status is DynamicSpreadEvaluationStatus.BLOCKED_BY_MODEL_STATE
    assert evaluation.blocked_reason is DynamicSpreadBlockedReason.MISSING_DYNAMIC_FEATURES

    preview = preview_spread(
        SpreadPreviewInput(
            metadata=_metadata(),
            spread_model=_dynamic_model(),
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            reference_price="5000",
        ),
    )

    assert preview.status is SpreadPreviewStatus.BLOCKED_BY_MODEL_STATE
    assert preview.reason_code is DynamicSpreadBlockedReason.MISSING_DYNAMIC_FEATURES
    assert preview.effective_price is None


def test_dynamic_spread_preview_blocks_provenance_symbol_mismatch() -> None:
    preview = preview_spread(
        SpreadPreviewInput(
            metadata=_metadata(symbol="NQ"),
            spread_model=_dynamic_model(),
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            reference_price="18000",
            dynamic_spread_features=_features(),
        ),
    )

    assert preview.status is SpreadPreviewStatus.BLOCKED_BY_MODEL_STATE
    assert preview.reason_code is DynamicSpreadBlockedReason.PROVENANCE_SYMBOL_MISMATCH
    assert preview.effective_price is None


def test_resolved_profile_rejects_dynamic_provenance_symbol_mismatch() -> None:
    with pytest.raises(ValueError, match="dynamic spread provenance symbol"):
        _profile(_metadata(symbol="NQ"), _dynamic_model())


def test_combined_preview_propagates_dynamic_spread_model_state_reason() -> None:
    metadata = _metadata()
    profile = _profile(metadata, _dynamic_model())

    preview = preview_execution_cost(
        ExecutionCostPreviewInput(
            metadata=metadata,
            profile=profile,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity="1",
            reference_price="5000",
        ),
    )

    assert preview.status is ExecutionCostPreviewStatus.BLOCKED_BY_MODEL_STATE
    assert preview.reason_code is DynamicSpreadBlockedReason.MISSING_DYNAMIC_FEATURES
    assert preview.final_effective_price is None
    assert preview.slippage_preview is None
    assert preview.commission_preview is None


def test_dynamic_evaluation_blocks_non_finite_feature_inputs() -> None:
    model = _dynamic_model(liquidity_weight="0")
    evaluation = evaluate_dynamic_half_spread(
        model,
        _features(volatility_stress_signal="NaN", liquidity_stress_signal=None),
    )

    assert evaluation.status is DynamicSpreadEvaluationStatus.BLOCKED_BY_MODEL_STATE
    assert evaluation.blocked_reason is DynamicSpreadBlockedReason.NON_FINITE_DYNAMIC_INPUT


def test_dynamic_evaluation_blocks_unknown_session_bucket() -> None:
    evaluation = evaluate_dynamic_half_spread(
        _dynamic_model(),
        _features(session_bucket_id="unknown"),
    )

    assert evaluation.status is DynamicSpreadEvaluationStatus.BLOCKED_BY_MODEL_STATE
    assert evaluation.blocked_reason is DynamicSpreadBlockedReason.UNKNOWN_SESSION_BUCKET


def test_dynamic_liquidity_feature_requires_signal_and_positive_observed_volume() -> None:
    model = _dynamic_model(liquidity_weight="1")

    missing_volume = evaluate_dynamic_half_spread(
        model,
        _features(liquidity_stress_signal="0.10", liquidity_observed_volume=None),
    )
    zero_volume = evaluate_dynamic_half_spread(
        model,
        _features(liquidity_stress_signal="0.10", liquidity_observed_volume="0"),
    )
    missing_signal = evaluate_dynamic_half_spread(
        model,
        _features(liquidity_stress_signal=None, liquidity_observed_volume="1000"),
    )

    assert missing_volume.blocked_reason is DynamicSpreadBlockedReason.MISSING_LIQUIDITY_OBSERVATION
    assert zero_volume.blocked_reason is DynamicSpreadBlockedReason.NON_POSITIVE_LIQUIDITY_OBSERVATION
    assert missing_signal.blocked_reason is DynamicSpreadBlockedReason.MISSING_LIQUIDITY_SIGNAL


@pytest.mark.parametrize("order_type", (OrderType.LIMIT, OrderType.STOP_LIMIT))
def test_dynamic_spread_preview_blocks_limit_like_orders(order_type: OrderType) -> None:
    preview = preview_spread(
        SpreadPreviewInput(
            metadata=_metadata(),
            spread_model=_dynamic_model(),
            side=OrderSide.BUY,
            order_type=order_type,
            reference_price="5000",
            limit_price="5000.25",
            dynamic_spread_features=_features(),
        ),
    )

    assert preview.status is SpreadPreviewStatus.BLOCKED_BY_MODEL_STATE
    assert preview.reason_code is DynamicSpreadBlockedReason.UNSUPPORTED_ORDER_TYPE
    assert preview.effective_price is None


def test_dynamic_spread_preview_blocks_non_positive_synthetic_prices() -> None:
    preview = preview_spread(
        SpreadPreviewInput(
            metadata=_metadata(),
            spread_model=_dynamic_model(base_half_spread_price="2", max_half_spread_price="2"),
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            reference_price="1",
            dynamic_spread_features=_features(),
        ),
    )

    assert preview.status is SpreadPreviewStatus.BLOCKED_BY_MODEL_STATE
    assert preview.reason_code is DynamicSpreadBlockedReason.NON_POSITIVE_EFFECTIVE_PRICE
    assert preview.candidate_effective_price == Decimal("-1")
    assert preview.effective_price is None


def test_dynamic_calculate_half_spread_requires_unblocked_evaluation() -> None:
    model = _dynamic_model(base_half_spread_price="0.25", max_half_spread_price="2")

    assert calculate_half_spread_price(_metadata(), model, _features()) == Decimal("0.25")

    with pytest.raises(ValueError, match="dynamic spread evaluation blocked"):
        calculate_half_spread_price(_metadata(), model)


def test_static_spread_preview_does_not_require_dynamic_features() -> None:
    preview = preview_spread(
        SpreadPreviewInput(
            metadata=_metadata(),
            spread_model=StaticHalfSpreadPrice(half_spread_price="0.10"),
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            reference_price="5000",
        ),
    )

    assert preview.status is SpreadPreviewStatus.APPLIED
    assert preview.reason_code is None
    assert preview.effective_price == Decimal("5000.10")


def _dynamic_model(
    *,
    base_half_spread_price: str = "0.25",
    min_half_spread_price: str = "0.10",
    max_half_spread_price: str = "2.00",
    volatility_weight: str = "1.00",
    liquidity_weight: str = "1.00",
    session_adjustment_log: str = "0",
) -> LogLinearDynamicHalfSpread:
    return LogLinearDynamicHalfSpread(
        base_half_spread_price=base_half_spread_price,
        min_half_spread_price=min_half_spread_price,
        max_half_spread_price=max_half_spread_price,
        volatility_weight=volatility_weight,
        liquidity_weight=liquidity_weight,
        session_buckets=(
            DynamicSpreadSessionBucket(
                session_bucket_id="regular",
                session_adjustment_log=session_adjustment_log,
            ),
        ),
        provenance=_provenance(),
    )


def _dynamic_model_payload() -> dict[str, object]:
    return {
        "model": "log_linear_dynamic_half_spread",
        "base_half_spread_price": "0.25",
        "min_half_spread_price": "0.10",
        "max_half_spread_price": "2.00",
        "volatility_weight": "0.50",
        "liquidity_weight": "0.25",
        "session_buckets": [
            {"session_bucket_id": "regular", "session_adjustment_log": "0"},
            {"session_bucket_id": "rollover", "session_adjustment_log": "0.20"},
        ],
        "provenance": _provenance().model_dump(mode="json"),
    }


def _provenance() -> DynamicSpreadCalibrationProvenance:
    return DynamicSpreadCalibrationProvenance(
        symbol="ES",
        venue="CME",
        timeframe="15m",
        provider_or_broker="manual-test-fixture",
        sample_start_utc=datetime(2024, 1, 1, tzinfo=timezone.utc),
        sample_end_utc=datetime(2024, 2, 1, tzinfo=timezone.utc),
        row_count=1000,
        data_quality_notes="test fixture with no known gaps",
        sample_role="in_sample_fixture",
        estimator_method="manual",
        conversion_method="already_price_units",
    )


def _features(
    *,
    fill_timestamp_utc: datetime | None = None,
    feature_observed_at_utc: datetime | None = None,
    session_bucket_id: str = "regular",
    volatility_stress_signal: str | None = "0",
    liquidity_stress_signal: str | None = "0",
    liquidity_observed_volume: str | None = "1000",
) -> DynamicSpreadFeatureInput:
    return DynamicSpreadFeatureInput(
        fill_timestamp_utc=fill_timestamp_utc
        or datetime(2024, 1, 2, 10, tzinfo=timezone.utc),
        feature_observed_at_utc=feature_observed_at_utc
        or datetime(2024, 1, 2, 9, 45, tzinfo=timezone.utc),
        session_bucket_id=session_bucket_id,
        volatility_stress_signal=volatility_stress_signal,
        liquidity_stress_signal=liquidity_stress_signal,
        liquidity_observed_volume=liquidity_observed_volume,
    )


def _metadata(symbol: str = "ES") -> ExecutionInstrumentMetadata:
    return ExecutionInstrumentMetadata(
        symbol=symbol,
        instrument_type=ExecutionInstrumentType.FUTURES,
        asset_class=ExecutionAssetClass.INDEX,
        quote_currency="USD",
        tick_size="0.25",
        point_size="0.25",
        lot_size="1",
        multiplier="50",
        price_precision=2,
    )


def _profile(
    metadata: ExecutionInstrumentMetadata,
    spread_model: LogLinearDynamicHalfSpread,
) -> ResolvedExecutionCostProfile:
    return ResolvedExecutionCostProfile(
        symbol=metadata.symbol,
        instrument_type=metadata.instrument_type,
        asset_class=metadata.asset_class,
        quote_currency=metadata.quote_currency,
        commission_model=RateOfNotionalCommission(commission_rate_bps="1"),
        spread_model=spread_model,
        slippage_model=FixedTicksSlippage(slippage_ticks="1"),
    )
