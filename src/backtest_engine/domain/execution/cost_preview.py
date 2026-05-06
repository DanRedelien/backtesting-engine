"""Combined deterministic execution-cost previews."""

from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Sequence

from pydantic import BaseModel, ConfigDict, field_validator

from backtest_engine.core.enums import OrderSide, OrderType
from backtest_engine.core.types import Symbol
from backtest_engine.domain.execution.commissions import (
    CommissionPreview,
    CommissionPreviewInput,
    ResolvedExecutionCostProfile,
    preview_commission,
)
from backtest_engine.domain.execution.instrument_metadata import ExecutionInstrumentMetadata
from backtest_engine.domain.execution.slippage import (
    SlippagePreview,
    SlippagePreviewInput,
    preview_slippage,
)
from backtest_engine.domain.execution.spreads import (
    DynamicSpreadBlockedReason,
    DynamicSpreadFeatureInput,
    SpreadPreview,
    SpreadPreviewInput,
    SpreadPreviewStatus,
    SpreadReferencePriceBasis,
    preview_spread,
)


class ExecutionCostPreviewStatus(str, Enum):
    """Combined cost preview status."""

    APPLIED = "applied"
    BLOCKED_BY_LIMIT = "blocked_by_limit"
    BLOCKED_BY_MODEL_STATE = "blocked_by_model_state"


class ExecutionCostPreviewInput(BaseModel):
    """Per-leg input for deterministic commission, spread, and slippage preview."""

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=False)

    metadata: ExecutionInstrumentMetadata
    profile: ResolvedExecutionCostProfile
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    reference_price: Decimal
    limit_price: Decimal | None = None
    reference_price_basis: SpreadReferencePriceBasis = SpreadReferencePriceBasis.LAST_EXTERNAL
    dynamic_spread_features: DynamicSpreadFeatureInput | None = None

    @field_validator("quantity", "reference_price", "limit_price", mode="before")
    @classmethod
    def _coerce_decimal(cls, value: Decimal | float | int | str | None) -> Decimal | None:
        if value is None:
            return None
        return Decimal(str(value))

    @field_validator("reference_price", "limit_price")
    @classmethod
    def _require_positive_price(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and value <= Decimal("0"):
            raise ValueError("combined cost preview prices must be positive")
        return value


class ExecutionCostPreview(BaseModel):
    """Per-symbol combined execution-cost preview for one order leg."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: Symbol
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    reference_price: Decimal
    final_effective_price: Decimal | None
    status: ExecutionCostPreviewStatus
    spread_preview: SpreadPreview
    slippage_preview: SlippagePreview | None
    commission_preview: CommissionPreview | None
    reason_code: DynamicSpreadBlockedReason | None = None
    protection_reason: str | None = None


def preview_execution_cost(input_: ExecutionCostPreviewInput) -> ExecutionCostPreview:
    """Compose spread, slippage, and commission previews for one symbol/order leg."""

    _validate_profile_matches_metadata(input_.metadata, input_.profile)

    spread_preview = preview_spread(
        SpreadPreviewInput(
            metadata=input_.metadata,
            spread_model=input_.profile.spread_model,
            side=input_.side,
            order_type=input_.order_type,
            reference_price=input_.reference_price,
            limit_price=input_.limit_price,
            reference_price_basis=input_.reference_price_basis,
            dynamic_spread_features=input_.dynamic_spread_features,
        ),
    )
    if spread_preview.status is not SpreadPreviewStatus.APPLIED:
        status = (
            ExecutionCostPreviewStatus.BLOCKED_BY_LIMIT
            if spread_preview.status is SpreadPreviewStatus.BLOCKED_BY_LIMIT
            else ExecutionCostPreviewStatus.BLOCKED_BY_MODEL_STATE
        )
        return ExecutionCostPreview(
            symbol=input_.metadata.symbol,
            side=input_.side,
            order_type=input_.order_type,
            quantity=input_.quantity,
            reference_price=input_.reference_price,
            final_effective_price=None,
            status=status,
            spread_preview=spread_preview,
            slippage_preview=None,
            commission_preview=None,
            reason_code=spread_preview.reason_code,
            protection_reason=spread_preview.protection_reason,
        )

    if spread_preview.effective_price is None:
        raise ValueError("applied spread preview must carry an effective price")

    slippage_preview = preview_slippage(
        SlippagePreviewInput(
            metadata=input_.metadata,
            slippage_model=input_.profile.slippage_model,
            side=input_.side,
            order_type=input_.order_type,
            price_base=spread_preview.effective_price,
            limit_price=input_.limit_price,
        ),
    )
    final_effective_price = slippage_preview.effective_price
    commission_preview = preview_commission(
        CommissionPreviewInput(
            metadata=input_.metadata,
            profile=input_.profile,
            quantity=input_.quantity,
            price=final_effective_price,
        ),
    )
    return ExecutionCostPreview(
        symbol=input_.metadata.symbol,
        side=input_.side,
        order_type=input_.order_type,
        quantity=input_.quantity,
        reference_price=input_.reference_price,
        final_effective_price=final_effective_price,
        status=ExecutionCostPreviewStatus.APPLIED,
        spread_preview=spread_preview,
        slippage_preview=slippage_preview,
        commission_preview=commission_preview,
    )


def preview_execution_costs_for_legs(
    inputs: Sequence[ExecutionCostPreviewInput],
) -> tuple[ExecutionCostPreview, ...]:
    """Preview costs per symbol/per leg without synthetic spread netting."""

    return tuple(preview_execution_cost(input_) for input_ in inputs)


def _validate_profile_matches_metadata(
    metadata: ExecutionInstrumentMetadata,
    profile: ResolvedExecutionCostProfile,
) -> None:
    if profile.symbol != metadata.symbol:
        raise ValueError("execution cost profile symbol must match instrument metadata symbol")
    if profile.quote_currency != metadata.quote_currency:
        raise ValueError("execution cost profile quote_currency must match instrument metadata")


__all__ = [
    "ExecutionCostPreview",
    "ExecutionCostPreviewInput",
    "ExecutionCostPreviewStatus",
    "preview_execution_cost",
    "preview_execution_costs_for_legs",
]
