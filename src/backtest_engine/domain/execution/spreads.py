"""Pure spread-model contracts and deterministic spread previews."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal, DecimalException
from enum import Enum
from typing import Annotated, Literal, Sequence, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

from backtest_engine.core.enums import OrderSide, OrderType
from backtest_engine.core.types import NonEmptyStr, Symbol, Timeframe
from backtest_engine.domain.execution.instrument_metadata import ExecutionInstrumentMetadata
from backtest_engine.domain.execution.order_economics import classify_order_execution


class SpreadModelName(str, Enum):
    """Supported explicit deterministic spread models."""

    STATIC_HALF_SPREAD_PRICE = "static_half_spread_price"
    STATIC_HALF_SPREAD_TICKS = "static_half_spread_ticks"
    BUFFERED_STATIC_SPREAD = "buffered_static_spread"
    LOG_LINEAR_DYNAMIC_HALF_SPREAD = "log_linear_dynamic_half_spread"


class SpreadReferencePriceBasis(str, Enum):
    """Reference price basis used by bar-driven deterministic spread previews."""

    LAST_EXTERNAL = "LAST-EXTERNAL"


class SpreadPreviewStatus(str, Enum):
    """Result status for deterministic spread preview."""

    APPLIED = "applied"
    BLOCKED_BY_LIMIT = "blocked_by_limit"
    BLOCKED_BY_MODEL_STATE = "blocked_by_model_state"


class DynamicSpreadEvaluationStatus(str, Enum):
    """Result status for pure dynamic half-spread evaluation."""

    APPLIED = "applied"
    BLOCKED_BY_MODEL_STATE = "blocked_by_model_state"


class DynamicSpreadBlockedReason(str, Enum):
    """Machine-readable blocked reasons for dynamic spread evaluation."""

    MISSING_DYNAMIC_FEATURES = "missing_dynamic_features"
    MISSING_VOLATILITY_SIGNAL = "missing_volatility_signal"
    MISSING_LIQUIDITY_SIGNAL = "missing_liquidity_signal"
    MISSING_LIQUIDITY_OBSERVATION = "missing_liquidity_observation"
    NON_POSITIVE_LIQUIDITY_OBSERVATION = "non_positive_liquidity_observation"
    NON_FINITE_DYNAMIC_INPUT = "non_finite_dynamic_input"
    UNKNOWN_SESSION_BUCKET = "unknown_session_bucket"
    PROVENANCE_SYMBOL_MISMATCH = "provenance_symbol_mismatch"
    UNSUPPORTED_ORDER_TYPE = "unsupported_order_type"
    NON_POSITIVE_EFFECTIVE_PRICE = "non_positive_effective_price"


def _coerce_decimal(value: Decimal | float | int | str) -> Decimal:
    return Decimal(str(value))


def _coerce_optional_decimal(value: Decimal | float | int | str | None) -> Decimal | None:
    if value is None:
        return None
    return _coerce_decimal(value)


def _require_finite_decimal(value: Decimal) -> Decimal:
    if not value.is_finite():
        raise ValueError("dynamic spread decimal fields must be finite")
    return value


def _require_non_negative_decimal(value: Decimal) -> Decimal:
    _require_finite_decimal(value)
    if value < Decimal("0"):
        raise ValueError(
            "dynamic spread widen-only weights and session adjustments must be non-negative"
        )
    return value


def _require_positive_dynamic_price(value: Decimal) -> Decimal:
    _require_finite_decimal(value)
    if value <= Decimal("0"):
        raise ValueError("dynamic spread price bounds must be positive")
    return value


def _require_utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("dynamic spread timestamps must be timezone-aware UTC")
    if value.utcoffset() != timedelta(0):
        raise ValueError(
            "dynamic spread timestamps must be UTC, not normalized from another timezone"
        )
    return value


class StaticHalfSpreadPrice(BaseModel):
    """Use a fixed half-spread already expressed in instrument price units."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model: Literal["static_half_spread_price"] = "static_half_spread_price"
    half_spread_price: Decimal

    @field_validator("half_spread_price", mode="before")
    @classmethod
    def _coerce_decimal(cls, value: Decimal | float | int | str) -> Decimal:
        return Decimal(str(value))

    @field_validator("half_spread_price")
    @classmethod
    def _require_positive_price(cls, value: Decimal) -> Decimal:
        if value <= Decimal("0"):
            raise ValueError("half_spread_price must be positive")
        return value


class StaticHalfSpreadTicks(BaseModel):
    """Use a fixed half-spread in ticks, converted through metadata tick_size."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model: Literal["static_half_spread_ticks"] = "static_half_spread_ticks"
    half_spread_ticks: Decimal

    @field_validator("half_spread_ticks", mode="before")
    @classmethod
    def _coerce_decimal(cls, value: Decimal | float | int | str) -> Decimal:
        return Decimal(str(value))

    @field_validator("half_spread_ticks")
    @classmethod
    def _require_positive_ticks(cls, value: Decimal) -> Decimal:
        if value <= Decimal("0"):
            raise ValueError("half_spread_ticks must be positive")
        return value


class BufferedStaticSpread(BaseModel):
    """Apply an explicit positive multiplier to a static price half-spread."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model: Literal["buffered_static_spread"] = "buffered_static_spread"
    base_half_spread_price: Decimal
    buffer_multiplier: Decimal

    @field_validator("base_half_spread_price", "buffer_multiplier", mode="before")
    @classmethod
    def _coerce_decimal(cls, value: Decimal | float | int | str) -> Decimal:
        return Decimal(str(value))

    @field_validator("base_half_spread_price")
    @classmethod
    def _require_positive_price(cls, value: Decimal) -> Decimal:
        if value <= Decimal("0"):
            raise ValueError("base_half_spread_price must be positive")
        return value

    @field_validator("buffer_multiplier")
    @classmethod
    def _require_positive_multiplier(cls, value: Decimal) -> Decimal:
        if value <= Decimal("0"):
            raise ValueError("buffer_multiplier must be positive")
        return value


class DynamicSpreadSessionBucket(BaseModel):
    """Calendar-derived session adjustment row for a dynamic spread model."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    session_bucket_id: NonEmptyStr
    session_adjustment_log: Decimal

    @field_validator("session_adjustment_log", mode="before")
    @classmethod
    def _coerce_decimal(cls, value: Decimal | float | int | str) -> Decimal:
        return _coerce_decimal(value)

    @field_validator("session_adjustment_log")
    @classmethod
    def _require_widen_only_adjustment(cls, value: Decimal) -> Decimal:
        return _require_non_negative_decimal(value)


class DynamicSpreadCalibrationProvenance(BaseModel):
    """Audit trail for price-unit dynamic spread parameters."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: Symbol
    venue: NonEmptyStr
    timeframe: Timeframe
    provider_or_broker: NonEmptyStr
    sample_start_utc: datetime
    sample_end_utc: datetime
    row_count: int = Field(gt=0)
    data_quality_notes: NonEmptyStr
    sample_role: NonEmptyStr
    estimator_method: NonEmptyStr
    conversion_method: NonEmptyStr

    @field_validator("sample_start_utc", "sample_end_utc")
    @classmethod
    def _require_utc(cls, value: datetime) -> datetime:
        return _require_utc_datetime(value)

    @model_validator(mode="after")
    def _validate_sample_window(self) -> "DynamicSpreadCalibrationProvenance":
        if self.sample_start_utc >= self.sample_end_utc:
            raise ValueError(
                "dynamic spread provenance sample_start_utc must be before sample_end_utc"
            )
        return self


class LogLinearDynamicHalfSpread(BaseModel):
    """Widen-only log-linear dynamic half-spread in instrument price units."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model: Literal["log_linear_dynamic_half_spread"] = "log_linear_dynamic_half_spread"
    base_half_spread_price: Decimal
    min_half_spread_price: Decimal
    max_half_spread_price: Decimal
    volatility_weight: Decimal
    liquidity_weight: Decimal
    session_buckets: tuple[DynamicSpreadSessionBucket, ...] = Field(min_length=1)
    provenance: DynamicSpreadCalibrationProvenance

    @field_validator(
        "base_half_spread_price",
        "min_half_spread_price",
        "max_half_spread_price",
        "volatility_weight",
        "liquidity_weight",
        mode="before",
    )
    @classmethod
    def _coerce_decimal(cls, value: Decimal | float | int | str) -> Decimal:
        return _coerce_decimal(value)

    @field_validator("base_half_spread_price", "min_half_spread_price", "max_half_spread_price")
    @classmethod
    def _require_positive_prices(cls, value: Decimal) -> Decimal:
        return _require_positive_dynamic_price(value)

    @field_validator("volatility_weight", "liquidity_weight")
    @classmethod
    def _require_widen_only_weights(cls, value: Decimal) -> Decimal:
        return _require_non_negative_decimal(value)

    @model_validator(mode="after")
    def _validate_bounds_and_sessions(self) -> "LogLinearDynamicHalfSpread":
        if not (
            self.min_half_spread_price <= self.base_half_spread_price <= self.max_half_spread_price
        ):
            raise ValueError(
                "dynamic spread bounds must satisfy "
                "0 < min_half_spread_price <= base_half_spread_price <= max_half_spread_price",
            )
        bucket_ids = [bucket.session_bucket_id for bucket in self.session_buckets]
        if len(bucket_ids) != len(set(bucket_ids)):
            raise ValueError("dynamic spread session_bucket_id values must be unique")
        return self


class DynamicSpreadFeatureInput(BaseModel):
    """Precomputed ex-ante stress signals for one dynamic spread evaluation."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=True)

    fill_timestamp_utc: datetime
    feature_observed_at_utc: datetime
    session_bucket_id: NonEmptyStr
    volatility_stress_signal: Decimal | None = None
    liquidity_stress_signal: Decimal | None = None
    liquidity_observed_volume: Decimal | None = None

    @field_validator("fill_timestamp_utc", "feature_observed_at_utc")
    @classmethod
    def _require_utc(cls, value: datetime) -> datetime:
        return _require_utc_datetime(value)

    @field_validator(
        "volatility_stress_signal",
        "liquidity_stress_signal",
        "liquidity_observed_volume",
        mode="before",
    )
    @classmethod
    def _coerce_decimal(cls, value: Decimal | float | int | str | None) -> Decimal | None:
        return _coerce_optional_decimal(value)

    @model_validator(mode="after")
    def _validate_observation_time(self) -> "DynamicSpreadFeatureInput":
        if self.feature_observed_at_utc >= self.fill_timestamp_utc:
            raise ValueError("feature_observed_at_utc must be before fill_timestamp_utc")
        return self


class DynamicSpreadEvaluation(BaseModel):
    """Pure dynamic half-spread formula result or blocked model state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: DynamicSpreadEvaluationStatus
    blocked_reason: DynamicSpreadBlockedReason | None = None
    effective_half_spread_price: Decimal | None = None
    log_effective_half_spread: Decimal | None = None
    base_half_spread_price: Decimal
    min_half_spread_price: Decimal
    max_half_spread_price: Decimal
    session_bucket_id: NonEmptyStr | None = None
    session_adjustment_log: Decimal | None = None
    volatility_stress_signal: Decimal | None = None
    liquidity_stress_signal: Decimal | None = None
    volatility_contribution_log: Decimal | None = None
    liquidity_contribution_log: Decimal | None = None

    @model_validator(mode="after")
    def _validate_status_shape(self) -> "DynamicSpreadEvaluation":
        if self.status is DynamicSpreadEvaluationStatus.APPLIED:
            if self.effective_half_spread_price is None:
                raise ValueError("applied dynamic spread evaluations require a half-spread price")
            if self.blocked_reason is not None:
                raise ValueError("applied dynamic spread evaluations must not carry blocked_reason")
        if (
            self.status is DynamicSpreadEvaluationStatus.BLOCKED_BY_MODEL_STATE
            and self.blocked_reason is None
        ):
            raise ValueError("blocked dynamic spread evaluations require blocked_reason")
        return self


SpreadModel: TypeAlias = Annotated[
    StaticHalfSpreadPrice
    | StaticHalfSpreadTicks
    | BufferedStaticSpread
    | LogLinearDynamicHalfSpread,
    Field(discriminator="model"),
]
_SPREAD_MODEL_ADAPTER: TypeAdapter[SpreadModel] = TypeAdapter(SpreadModel)


class SpreadModelPatch(BaseModel):
    """Partial spread model used before inheritance is resolved."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model: SpreadModelName | None = None
    half_spread_price: Decimal | None = None
    half_spread_ticks: Decimal | None = None
    base_half_spread_price: Decimal | None = None
    buffer_multiplier: Decimal | None = None
    min_half_spread_price: Decimal | None = None
    max_half_spread_price: Decimal | None = None
    volatility_weight: Decimal | None = None
    liquidity_weight: Decimal | None = None
    session_buckets: tuple[DynamicSpreadSessionBucket, ...] | None = None
    provenance: DynamicSpreadCalibrationProvenance | None = None

    @field_validator(
        "half_spread_price",
        "half_spread_ticks",
        "base_half_spread_price",
        "buffer_multiplier",
        "min_half_spread_price",
        "max_half_spread_price",
        "volatility_weight",
        "liquidity_weight",
        mode="before",
    )
    @classmethod
    def _coerce_decimal(cls, value: Decimal | float | int | str | None) -> Decimal | None:
        return _coerce_optional_decimal(value)

    def as_payload(self) -> dict[str, object]:
        """Return a final-model validation payload with unset fields removed."""

        return self.model_dump(mode="json", exclude_none=True)


class SpreadPreviewInput(BaseModel):
    """Per-leg input for deterministic adverse spread preview."""

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=False)

    metadata: ExecutionInstrumentMetadata
    spread_model: SpreadModel
    side: OrderSide
    order_type: OrderType
    reference_price: Decimal
    limit_price: Decimal | None = None
    reference_price_basis: SpreadReferencePriceBasis = SpreadReferencePriceBasis.LAST_EXTERNAL
    dynamic_spread_features: DynamicSpreadFeatureInput | None = None

    @field_validator("reference_price", "limit_price", mode="before")
    @classmethod
    def _coerce_decimal(cls, value: Decimal | float | int | str | None) -> Decimal | None:
        if value is None:
            return None
        return Decimal(str(value))

    @field_validator("reference_price", "limit_price")
    @classmethod
    def _require_positive_price(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and value <= Decimal("0"):
            raise ValueError("spread preview prices must be positive")
        return value


class SpreadPreview(BaseModel):
    """Deterministic per-symbol adverse spread adjustment for one order leg."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: Symbol
    spread_model_name: SpreadModelName
    side: OrderSide
    order_type: OrderType
    reference_price_basis: SpreadReferencePriceBasis
    reference_price: Decimal
    half_spread_price: Decimal | None
    signed_adjustment_price: Decimal | None
    candidate_effective_price: Decimal | None
    effective_price: Decimal | None
    limit_price: Decimal | None
    status: SpreadPreviewStatus
    reason_code: DynamicSpreadBlockedReason | None = None
    protection_reason: str | None = None
    dynamic_spread_evaluation: DynamicSpreadEvaluation | None = None


def validate_spread_model(payload: object) -> SpreadModel:
    """Validate a concrete spread model payload."""

    return _SPREAD_MODEL_ADAPTER.validate_python(payload)


def dynamic_spread_provenance_matches_symbol(
    spread_model: LogLinearDynamicHalfSpread,
    symbol: str,
) -> bool:
    """Return whether dynamic spread provenance belongs to the execution symbol."""

    return _normalize_symbol(spread_model.provenance.symbol) == _normalize_symbol(symbol)


def calculate_half_spread_price(
    metadata: ExecutionInstrumentMetadata,
    spread_model: SpreadModel,
    dynamic_spread_features: DynamicSpreadFeatureInput | None = None,
) -> Decimal:
    """Resolve a spread model into an instrument price-unit half-spread."""

    if isinstance(spread_model, StaticHalfSpreadPrice):
        return spread_model.half_spread_price
    if isinstance(spread_model, StaticHalfSpreadTicks):
        return spread_model.half_spread_ticks * metadata.tick_size
    if isinstance(spread_model, BufferedStaticSpread):
        return spread_model.base_half_spread_price * spread_model.buffer_multiplier

    if not dynamic_spread_provenance_matches_symbol(spread_model, metadata.symbol):
        raise ValueError("dynamic spread provenance symbol must match instrument metadata symbol")

    evaluation = evaluate_dynamic_half_spread(spread_model, dynamic_spread_features)
    if (
        evaluation.status is DynamicSpreadEvaluationStatus.BLOCKED_BY_MODEL_STATE
        or evaluation.effective_half_spread_price is None
    ):
        raise ValueError(f"dynamic spread evaluation blocked: {evaluation.blocked_reason}")
    return evaluation.effective_half_spread_price


def evaluate_dynamic_half_spread(
    spread_model: LogLinearDynamicHalfSpread,
    features: DynamicSpreadFeatureInput | None,
) -> DynamicSpreadEvaluation:
    """Evaluate the approved widen-only log-linear dynamic half-spread formula."""

    if features is None:
        return _blocked_dynamic_evaluation(
            spread_model,
            features,
            DynamicSpreadBlockedReason.MISSING_DYNAMIC_FEATURES,
        )

    session_bucket = _find_session_bucket(spread_model, features.session_bucket_id)
    if session_bucket is None:
        return _blocked_dynamic_evaluation(
            spread_model,
            features,
            DynamicSpreadBlockedReason.UNKNOWN_SESSION_BUCKET,
        )

    volatility_signal = _resolve_stress_signal(
        features.volatility_stress_signal,
        spread_model.volatility_weight,
        DynamicSpreadBlockedReason.MISSING_VOLATILITY_SIGNAL,
    )
    if isinstance(volatility_signal, DynamicSpreadBlockedReason):
        return _blocked_dynamic_evaluation(spread_model, features, volatility_signal)

    liquidity_reason = _validate_liquidity_inputs(spread_model, features)
    if liquidity_reason is not None:
        return _blocked_dynamic_evaluation(spread_model, features, liquidity_reason)
    liquidity_signal = _resolve_stress_signal(
        features.liquidity_stress_signal,
        spread_model.liquidity_weight,
        DynamicSpreadBlockedReason.MISSING_LIQUIDITY_SIGNAL,
    )
    if isinstance(liquidity_signal, DynamicSpreadBlockedReason):
        return _blocked_dynamic_evaluation(spread_model, features, liquidity_signal)

    try:
        log_base = spread_model.base_half_spread_price.ln()
        log_min = spread_model.min_half_spread_price.ln()
        log_max = spread_model.max_half_spread_price.ln()
    except DecimalException:
        return _blocked_dynamic_evaluation(
            spread_model,
            features,
            DynamicSpreadBlockedReason.NON_FINITE_DYNAMIC_INPUT,
        )

    try:
        cap_headroom_before_session_log = log_max - log_base
    except DecimalException:
        return _blocked_dynamic_evaluation(
            spread_model,
            features,
            DynamicSpreadBlockedReason.NON_FINITE_DYNAMIC_INPUT,
        )

    if (
        cap_headroom_before_session_log <= Decimal("0")
        or session_bucket.session_adjustment_log >= cap_headroom_before_session_log
    ):
        return _applied_dynamic_evaluation(
            spread_model=spread_model,
            features=features,
            session_bucket=session_bucket,
            effective_half_spread_price=spread_model.max_half_spread_price,
            log_effective=log_max,
            volatility_signal=volatility_signal,
            liquidity_signal=liquidity_signal,
        )

    try:
        cap_headroom_log = cap_headroom_before_session_log - session_bucket.session_adjustment_log
    except DecimalException:
        return _blocked_dynamic_evaluation(
            spread_model,
            features,
            DynamicSpreadBlockedReason.NON_FINITE_DYNAMIC_INPUT,
        )

    if _contribution_reaches_cap(
        spread_model.volatility_weight,
        volatility_signal,
        cap_headroom_log,
    ) or _contribution_reaches_cap(
        spread_model.liquidity_weight,
        liquidity_signal,
        cap_headroom_log,
    ):
        return _applied_dynamic_evaluation(
            spread_model=spread_model,
            features=features,
            session_bucket=session_bucket,
            effective_half_spread_price=spread_model.max_half_spread_price,
            log_effective=log_max,
            volatility_signal=volatility_signal,
            liquidity_signal=liquidity_signal,
        )

    try:
        volatility_contribution_log = spread_model.volatility_weight * volatility_signal
        liquidity_contribution_log = spread_model.liquidity_weight * liquidity_signal
        log_effective = (
            log_base
            + volatility_contribution_log
            + liquidity_contribution_log
            + session_bucket.session_adjustment_log
        )
    except DecimalException:
        return _blocked_dynamic_evaluation(
            spread_model,
            features,
            DynamicSpreadBlockedReason.NON_FINITE_DYNAMIC_INPUT,
        )

    if not log_effective.is_finite():
        return _blocked_dynamic_evaluation(
            spread_model,
            features,
            DynamicSpreadBlockedReason.NON_FINITE_DYNAMIC_INPUT,
        )
    if log_effective >= log_max:
        effective_half_spread_price = spread_model.max_half_spread_price
    elif log_effective <= log_min:
        effective_half_spread_price = spread_model.min_half_spread_price
    else:
        try:
            effective_half_spread_price = log_effective.exp()
        except DecimalException:
            return _blocked_dynamic_evaluation(
                spread_model,
                features,
                DynamicSpreadBlockedReason.NON_FINITE_DYNAMIC_INPUT,
            )

    return _applied_dynamic_evaluation(
        spread_model=spread_model,
        features=features,
        session_bucket=session_bucket,
        effective_half_spread_price=effective_half_spread_price,
        log_effective=log_effective,
        volatility_signal=volatility_signal,
        liquidity_signal=liquidity_signal,
        volatility_contribution_log=volatility_contribution_log,
        liquidity_contribution_log=liquidity_contribution_log,
    )


def preview_spread(input_: SpreadPreviewInput) -> SpreadPreview:
    """Return a deterministic adverse spread preview for one symbol/order leg."""

    economics = classify_order_execution(input_.order_type)
    if isinstance(input_.spread_model, LogLinearDynamicHalfSpread):
        return _preview_dynamic_spread(input_, input_.spread_model, economics.is_market_like)

    half_spread_price = calculate_half_spread_price(input_.metadata, input_.spread_model)
    signed_adjustment_price = _signed_adverse_adjustment(input_.side, half_spread_price)
    candidate_effective_price = input_.reference_price + signed_adjustment_price

    if candidate_effective_price <= Decimal("0"):
        return _blocked_model_state_preview(
            input_,
            half_spread_price,
            signed_adjustment_price,
            candidate_effective_price,
            DynamicSpreadBlockedReason.NON_POSITIVE_EFFECTIVE_PRICE,
            "spread-adjusted price must be positive",
        )

    if economics.adverse_price_must_respect_limit:
        limit_price = _require_limit_price(input_)
        if _violates_limit(input_.side, candidate_effective_price, limit_price):
            return _blocked_preview(
                input_,
                half_spread_price,
                signed_adjustment_price,
                candidate_effective_price,
                limit_price,
            )

    return SpreadPreview(
        symbol=input_.metadata.symbol,
        spread_model_name=SpreadModelName(input_.spread_model.model),
        side=input_.side,
        order_type=input_.order_type,
        reference_price_basis=input_.reference_price_basis,
        reference_price=input_.reference_price,
        half_spread_price=half_spread_price,
        signed_adjustment_price=signed_adjustment_price,
        candidate_effective_price=candidate_effective_price,
        effective_price=candidate_effective_price,
        limit_price=input_.limit_price,
        status=SpreadPreviewStatus.APPLIED,
    )


def preview_spreads_for_legs(
    inputs: Sequence[SpreadPreviewInput],
) -> tuple[SpreadPreview, ...]:
    """Preview spread adjustments per symbol/per leg without synthetic netting."""

    return tuple(preview_spread(input_) for input_ in inputs)


def _signed_adverse_adjustment(side: OrderSide, half_spread_price: Decimal) -> Decimal:
    if side is OrderSide.BUY:
        return half_spread_price
    return -half_spread_price


def _preview_dynamic_spread(
    input_: SpreadPreviewInput,
    spread_model: LogLinearDynamicHalfSpread,
    is_market_like: bool,
) -> SpreadPreview:
    if not dynamic_spread_provenance_matches_symbol(spread_model, input_.metadata.symbol):
        return _blocked_model_state_preview(
            input_,
            None,
            None,
            None,
            DynamicSpreadBlockedReason.PROVENANCE_SYMBOL_MISMATCH,
            "dynamic spread provenance symbol must match instrument metadata symbol",
        )

    if not is_market_like:
        return _blocked_model_state_preview(
            input_,
            None,
            None,
            None,
            DynamicSpreadBlockedReason.UNSUPPORTED_ORDER_TYPE,
            "dynamic spread is supported only for taker-like market and stop orders",
        )

    evaluation = evaluate_dynamic_half_spread(spread_model, input_.dynamic_spread_features)
    if (
        evaluation.status is DynamicSpreadEvaluationStatus.BLOCKED_BY_MODEL_STATE
        or evaluation.effective_half_spread_price is None
    ):
        reason: DynamicSpreadBlockedReason = (
            evaluation.blocked_reason or DynamicSpreadBlockedReason.NON_FINITE_DYNAMIC_INPUT
        )
        return _blocked_model_state_preview(
            input_,
            None,
            None,
            None,
            reason,
            f"dynamic spread evaluation blocked: {reason.value}",
            dynamic_spread_evaluation=evaluation,
        )

    half_spread_price = evaluation.effective_half_spread_price
    signed_adjustment_price = _signed_adverse_adjustment(input_.side, half_spread_price)
    candidate_effective_price = input_.reference_price + signed_adjustment_price
    if candidate_effective_price <= Decimal("0"):
        return _blocked_model_state_preview(
            input_,
            half_spread_price,
            signed_adjustment_price,
            candidate_effective_price,
            DynamicSpreadBlockedReason.NON_POSITIVE_EFFECTIVE_PRICE,
            "spread-adjusted price must be positive",
            dynamic_spread_evaluation=evaluation,
        )

    return SpreadPreview(
        symbol=input_.metadata.symbol,
        spread_model_name=SpreadModelName(spread_model.model),
        side=input_.side,
        order_type=input_.order_type,
        reference_price_basis=input_.reference_price_basis,
        reference_price=input_.reference_price,
        half_spread_price=half_spread_price,
        signed_adjustment_price=signed_adjustment_price,
        candidate_effective_price=candidate_effective_price,
        effective_price=candidate_effective_price,
        limit_price=input_.limit_price,
        status=SpreadPreviewStatus.APPLIED,
        dynamic_spread_evaluation=evaluation,
    )


def _contribution_reaches_cap(
    weight: Decimal,
    signal: Decimal,
    cap_headroom_log: Decimal,
) -> bool:
    if weight == Decimal("0"):
        return False
    try:
        return weight * signal >= cap_headroom_log
    except DecimalException:
        return True


def _applied_dynamic_evaluation(
    *,
    spread_model: LogLinearDynamicHalfSpread,
    features: DynamicSpreadFeatureInput,
    session_bucket: DynamicSpreadSessionBucket,
    effective_half_spread_price: Decimal,
    log_effective: Decimal,
    volatility_signal: Decimal,
    liquidity_signal: Decimal,
    volatility_contribution_log: Decimal | None = None,
    liquidity_contribution_log: Decimal | None = None,
) -> DynamicSpreadEvaluation:
    return DynamicSpreadEvaluation(
        status=DynamicSpreadEvaluationStatus.APPLIED,
        effective_half_spread_price=effective_half_spread_price,
        log_effective_half_spread=log_effective,
        base_half_spread_price=spread_model.base_half_spread_price,
        min_half_spread_price=spread_model.min_half_spread_price,
        max_half_spread_price=spread_model.max_half_spread_price,
        session_bucket_id=features.session_bucket_id,
        session_adjustment_log=session_bucket.session_adjustment_log,
        volatility_stress_signal=volatility_signal,
        liquidity_stress_signal=liquidity_signal,
        volatility_contribution_log=volatility_contribution_log,
        liquidity_contribution_log=liquidity_contribution_log,
    )


def _resolve_stress_signal(
    signal: Decimal | None,
    weight: Decimal,
    missing_reason: DynamicSpreadBlockedReason,
) -> Decimal | DynamicSpreadBlockedReason:
    if weight == Decimal("0"):
        if signal is None:
            return Decimal("0")
        if not signal.is_finite():
            return DynamicSpreadBlockedReason.NON_FINITE_DYNAMIC_INPUT
        return max(Decimal("0"), signal)
    if signal is None:
        return missing_reason
    if not signal.is_finite():
        return DynamicSpreadBlockedReason.NON_FINITE_DYNAMIC_INPUT
    return max(Decimal("0"), signal)


def _validate_liquidity_inputs(
    spread_model: LogLinearDynamicHalfSpread,
    features: DynamicSpreadFeatureInput,
) -> DynamicSpreadBlockedReason | None:
    if spread_model.liquidity_weight == Decimal("0"):
        return None
    if features.liquidity_observed_volume is None:
        return DynamicSpreadBlockedReason.MISSING_LIQUIDITY_OBSERVATION
    if not features.liquidity_observed_volume.is_finite():
        return DynamicSpreadBlockedReason.NON_FINITE_DYNAMIC_INPUT
    if features.liquidity_observed_volume <= Decimal("0"):
        return DynamicSpreadBlockedReason.NON_POSITIVE_LIQUIDITY_OBSERVATION
    return None


def _find_session_bucket(
    spread_model: LogLinearDynamicHalfSpread,
    session_bucket_id: str,
) -> DynamicSpreadSessionBucket | None:
    return next(
        (
            bucket
            for bucket in spread_model.session_buckets
            if bucket.session_bucket_id == session_bucket_id
        ),
        None,
    )


def _blocked_dynamic_evaluation(
    spread_model: LogLinearDynamicHalfSpread,
    features: DynamicSpreadFeatureInput | None,
    reason: DynamicSpreadBlockedReason,
) -> DynamicSpreadEvaluation:
    return DynamicSpreadEvaluation(
        status=DynamicSpreadEvaluationStatus.BLOCKED_BY_MODEL_STATE,
        blocked_reason=reason,
        base_half_spread_price=spread_model.base_half_spread_price,
        min_half_spread_price=spread_model.min_half_spread_price,
        max_half_spread_price=spread_model.max_half_spread_price,
        session_bucket_id=features.session_bucket_id if features is not None else None,
        volatility_stress_signal=_finite_or_none(features.volatility_stress_signal)
        if features is not None
        else None,
        liquidity_stress_signal=_finite_or_none(features.liquidity_stress_signal)
        if features is not None
        else None,
    )


def _finite_or_none(value: Decimal | None) -> Decimal | None:
    if value is None or not value.is_finite():
        return None
    return value


def _normalize_symbol(symbol: str) -> str:
    return symbol.strip().upper()


def _require_limit_price(input_: SpreadPreviewInput) -> Decimal:
    if input_.limit_price is None:
        raise ValueError("limit_price is required for LIMIT and STOP_LIMIT spread previews")
    return input_.limit_price


def _violates_limit(
    side: OrderSide,
    candidate_effective_price: Decimal,
    limit_price: Decimal,
) -> bool:
    if side is OrderSide.BUY:
        return candidate_effective_price > limit_price
    return candidate_effective_price < limit_price


def _blocked_preview(
    input_: SpreadPreviewInput,
    half_spread_price: Decimal,
    signed_adjustment_price: Decimal,
    candidate_effective_price: Decimal,
    limit_price: Decimal,
) -> SpreadPreview:
    return SpreadPreview(
        symbol=input_.metadata.symbol,
        spread_model_name=SpreadModelName(input_.spread_model.model),
        side=input_.side,
        order_type=input_.order_type,
        reference_price_basis=input_.reference_price_basis,
        reference_price=input_.reference_price,
        half_spread_price=half_spread_price,
        signed_adjustment_price=signed_adjustment_price,
        candidate_effective_price=candidate_effective_price,
        effective_price=None,
        limit_price=limit_price,
        status=SpreadPreviewStatus.BLOCKED_BY_LIMIT,
        protection_reason=_limit_protection_reason(
            input_.side, candidate_effective_price, limit_price
        ),
    )


def _blocked_model_state_preview(
    input_: SpreadPreviewInput,
    half_spread_price: Decimal | None,
    signed_adjustment_price: Decimal | None,
    candidate_effective_price: Decimal | None,
    reason_code: DynamicSpreadBlockedReason,
    protection_reason: str,
    *,
    dynamic_spread_evaluation: DynamicSpreadEvaluation | None = None,
) -> SpreadPreview:
    return SpreadPreview(
        symbol=input_.metadata.symbol,
        spread_model_name=SpreadModelName(input_.spread_model.model),
        side=input_.side,
        order_type=input_.order_type,
        reference_price_basis=input_.reference_price_basis,
        reference_price=input_.reference_price,
        half_spread_price=half_spread_price,
        signed_adjustment_price=signed_adjustment_price,
        candidate_effective_price=candidate_effective_price,
        effective_price=None,
        limit_price=input_.limit_price,
        status=SpreadPreviewStatus.BLOCKED_BY_MODEL_STATE,
        reason_code=reason_code,
        protection_reason=protection_reason,
        dynamic_spread_evaluation=dynamic_spread_evaluation,
    )


def _limit_protection_reason(
    side: OrderSide,
    candidate_effective_price: Decimal,
    limit_price: Decimal,
) -> str:
    if side is OrderSide.BUY:
        return (
            f"BUY spread-adjusted price {candidate_effective_price} exceeds "
            f"limit price {limit_price}"
        )
    return (
        f"SELL spread-adjusted price {candidate_effective_price} is below limit price {limit_price}"
    )


__all__ = [
    "BufferedStaticSpread",
    "DynamicSpreadBlockedReason",
    "DynamicSpreadCalibrationProvenance",
    "DynamicSpreadEvaluation",
    "DynamicSpreadEvaluationStatus",
    "DynamicSpreadFeatureInput",
    "DynamicSpreadSessionBucket",
    "LogLinearDynamicHalfSpread",
    "SpreadModel",
    "SpreadModelName",
    "SpreadModelPatch",
    "SpreadPreview",
    "SpreadPreviewInput",
    "SpreadPreviewStatus",
    "SpreadReferencePriceBasis",
    "StaticHalfSpreadPrice",
    "StaticHalfSpreadTicks",
    "calculate_half_spread_price",
    "dynamic_spread_provenance_matches_symbol",
    "evaluate_dynamic_half_spread",
    "preview_spread",
    "preview_spreads_for_legs",
    "validate_spread_model",
]
