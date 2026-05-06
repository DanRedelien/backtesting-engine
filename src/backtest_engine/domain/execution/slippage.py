"""Pure slippage-model contracts and deterministic slippage previews."""

from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Annotated, Literal, Sequence, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

from backtest_engine.core.enums import OrderSide, OrderType
from backtest_engine.core.types import NonEmptyStr, Symbol
from backtest_engine.domain.execution.instrument_metadata import ExecutionInstrumentMetadata
from backtest_engine.domain.execution.order_economics import classify_order_execution


class SlippageModelName(str, Enum):
    """Supported explicit deterministic slippage models."""

    FIXED_TICKS = "fixed_ticks"
    BPS_OF_PRICE = "bps_of_price"
    NONE_EXPLICIT = "none_explicit"


class SlippagePreviewStatus(str, Enum):
    """Result status for deterministic slippage preview."""

    APPLIED = "applied"
    NONE_EXPLICIT = "none_explicit"
    ZERO_LIMIT_PROTECTED = "zero_limit_protected"


class FixedTicksSlippage(BaseModel):
    """Use fixed adverse slippage ticks converted through metadata tick size."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model: Literal["fixed_ticks"] = "fixed_ticks"
    slippage_ticks: Decimal

    @field_validator("slippage_ticks", mode="before")
    @classmethod
    def _coerce_decimal(cls, value: Decimal | float | int | str) -> Decimal:
        return Decimal(str(value))

    @field_validator("slippage_ticks")
    @classmethod
    def _require_positive_ticks(cls, value: Decimal) -> Decimal:
        if value <= Decimal("0"):
            raise ValueError("slippage_ticks must be positive; use none_explicit for no slippage")
        return value


class BpsOfPriceSlippage(BaseModel):
    """Use basis points of an explicit positive price base."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model: Literal["bps_of_price"] = "bps_of_price"
    slippage_bps: Decimal

    @field_validator("slippage_bps", mode="before")
    @classmethod
    def _coerce_decimal(cls, value: Decimal | float | int | str) -> Decimal:
        return Decimal(str(value))

    @field_validator("slippage_bps")
    @classmethod
    def _require_positive_bps(cls, value: Decimal) -> Decimal:
        if value <= Decimal("0"):
            raise ValueError("slippage_bps must be positive; use none_explicit for no slippage")
        return value


class NoneExplicitSlippage(BaseModel):
    """Intentionally select no deterministic slippage for an instrument."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model: Literal["none_explicit"] = "none_explicit"
    reason: NonEmptyStr


SlippageModel: TypeAlias = Annotated[
    FixedTicksSlippage | BpsOfPriceSlippage | NoneExplicitSlippage,
    Field(discriminator="model"),
]
_SLIPPAGE_MODEL_ADAPTER: TypeAdapter[SlippageModel] = TypeAdapter(SlippageModel)


class SlippageModelPatch(BaseModel):
    """Partial slippage model used before inheritance is resolved."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model: SlippageModelName | None = None
    slippage_ticks: Decimal | None = None
    slippage_bps: Decimal | None = None
    reason: NonEmptyStr | None = None

    @field_validator("slippage_ticks", "slippage_bps", mode="before")
    @classmethod
    def _coerce_decimal(cls, value: Decimal | float | int | str | None) -> Decimal | None:
        if value is None:
            return None
        return Decimal(str(value))

    def as_payload(self) -> dict[str, object]:
        """Return a final-model validation payload with unset fields removed."""

        return self.model_dump(mode="json", exclude_none=True)


class SlippagePreviewInput(BaseModel):
    """Per-leg input for deterministic adverse slippage preview."""

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=False)

    metadata: ExecutionInstrumentMetadata
    slippage_model: SlippageModel
    side: OrderSide
    order_type: OrderType
    price_base: Decimal
    limit_price: Decimal | None = None

    @field_validator("price_base", "limit_price", mode="before")
    @classmethod
    def _coerce_decimal(cls, value: Decimal | float | int | str | None) -> Decimal | None:
        if value is None:
            return None
        return Decimal(str(value))

    @field_validator("price_base", "limit_price")
    @classmethod
    def _require_positive_price(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and value <= Decimal("0"):
            raise ValueError("slippage preview prices must be positive")
        return value


class SlippagePreview(BaseModel):
    """Deterministic per-symbol adverse slippage adjustment for one order leg."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: Symbol
    slippage_model_name: SlippageModelName
    side: OrderSide
    order_type: OrderType
    price_base: Decimal
    slippage_price: Decimal
    signed_adjustment_price: Decimal
    candidate_effective_price: Decimal
    effective_price: Decimal
    limit_price: Decimal | None
    status: SlippagePreviewStatus
    adverse_slippage_applied: bool
    protection_reason: str | None = None


def validate_slippage_model(payload: object) -> SlippageModel:
    """Validate a concrete slippage model payload."""

    return _SLIPPAGE_MODEL_ADAPTER.validate_python(payload)


def calculate_slippage_price(
    metadata: ExecutionInstrumentMetadata,
    slippage_model: SlippageModel,
    price_base: Decimal | float | int | str,
) -> Decimal:
    """Resolve a slippage model into instrument price units."""

    price_base_decimal = Decimal(str(price_base))
    if isinstance(slippage_model, FixedTicksSlippage):
        return slippage_model.slippage_ticks * metadata.tick_size
    if isinstance(slippage_model, BpsOfPriceSlippage):
        if price_base_decimal <= Decimal("0"):
            raise ValueError("slippage price_base must be positive")
        return price_base_decimal * slippage_model.slippage_bps / Decimal("10000")
    return Decimal("0")


def preview_slippage(input_: SlippagePreviewInput) -> SlippagePreview:
    """Return a deterministic adverse slippage preview for one symbol/order leg."""

    economics = classify_order_execution(input_.order_type)
    if not economics.adverse_slippage_allowed:
        return _zero_slippage_preview(input_, SlippagePreviewStatus.ZERO_LIMIT_PROTECTED)

    if isinstance(input_.slippage_model, NoneExplicitSlippage):
        return _zero_slippage_preview(input_, SlippagePreviewStatus.NONE_EXPLICIT)

    slippage_price = calculate_slippage_price(
        input_.metadata,
        input_.slippage_model,
        input_.price_base,
    )
    signed_adjustment_price = _signed_adverse_adjustment(input_.side, slippage_price)
    candidate_effective_price = input_.price_base + signed_adjustment_price
    return SlippagePreview(
        symbol=input_.metadata.symbol,
        slippage_model_name=SlippageModelName(input_.slippage_model.model),
        side=input_.side,
        order_type=input_.order_type,
        price_base=input_.price_base,
        slippage_price=slippage_price,
        signed_adjustment_price=signed_adjustment_price,
        candidate_effective_price=candidate_effective_price,
        effective_price=candidate_effective_price,
        limit_price=input_.limit_price,
        status=SlippagePreviewStatus.APPLIED,
        adverse_slippage_applied=True,
    )


def preview_slippages_for_legs(
    inputs: Sequence[SlippagePreviewInput],
) -> tuple[SlippagePreview, ...]:
    """Preview slippage adjustments per symbol/per leg without synthetic netting."""

    return tuple(preview_slippage(input_) for input_ in inputs)


def _zero_slippage_preview(
    input_: SlippagePreviewInput,
    status: SlippagePreviewStatus,
) -> SlippagePreview:
    reason = None
    if status is SlippagePreviewStatus.ZERO_LIMIT_PROTECTED:
        reason = f"{input_.order_type.value} orders do not receive adverse slippage"

    return SlippagePreview(
        symbol=input_.metadata.symbol,
        slippage_model_name=SlippageModelName(input_.slippage_model.model),
        side=input_.side,
        order_type=input_.order_type,
        price_base=input_.price_base,
        slippage_price=Decimal("0"),
        signed_adjustment_price=Decimal("0"),
        candidate_effective_price=input_.price_base,
        effective_price=input_.price_base,
        limit_price=input_.limit_price,
        status=status,
        adverse_slippage_applied=False,
        protection_reason=reason,
    )


def _signed_adverse_adjustment(side: OrderSide, slippage_price: Decimal) -> Decimal:
    if side is OrderSide.BUY:
        return slippage_price
    return -slippage_price


__all__ = [
    "BpsOfPriceSlippage",
    "FixedTicksSlippage",
    "NoneExplicitSlippage",
    "SlippageModel",
    "SlippageModelName",
    "SlippageModelPatch",
    "SlippagePreview",
    "SlippagePreviewInput",
    "SlippagePreviewStatus",
    "calculate_slippage_price",
    "preview_slippage",
    "preview_slippages_for_legs",
    "validate_slippage_model",
]
