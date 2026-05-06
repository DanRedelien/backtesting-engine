"""Pure commission-model contracts and deterministic commission previews."""

from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Annotated, Literal, Sequence, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

from backtest_engine.core.types import CurrencyCode, NonEmptyStr, Symbol
from backtest_engine.domain.execution.instrument_metadata import (
    ExecutionAssetClass,
    ExecutionInstrumentMetadata,
    ExecutionInstrumentType,
)
from backtest_engine.domain.execution.spreads import (
    LogLinearDynamicHalfSpread,
    SpreadModel,
    SpreadModelPatch,
    dynamic_spread_provenance_matches_symbol,
    validate_spread_model,
)
from backtest_engine.domain.execution.slippage import (
    SlippageModel,
    SlippageModelPatch,
    validate_slippage_model,
)


class CommissionModelName(str, Enum):
    """Supported explicit commission models."""

    RATE_OF_NOTIONAL = "rate_of_notional"
    FIXED_PER_CONTRACT = "fixed_per_contract"
    ZERO_EXPLICIT = "zero_explicit"


class RateOfNotionalCommission(BaseModel):
    """Charge commission as basis points of absolute execution notional."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model: Literal["rate_of_notional"] = "rate_of_notional"
    commission_rate_bps: Decimal

    @field_validator("commission_rate_bps", mode="before")
    @classmethod
    def _coerce_decimal(cls, value: Decimal | float | int | str) -> Decimal:
        return Decimal(str(value))

    @field_validator("commission_rate_bps")
    @classmethod
    def _require_positive_rate(cls, value: Decimal) -> Decimal:
        if value <= Decimal("0"):
            raise ValueError("commission_rate_bps must be positive; use zero_explicit for zero")
        return value


class FixedPerContractCommission(BaseModel):
    """Charge a fixed currency amount per absolute contract quantity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model: Literal["fixed_per_contract"] = "fixed_per_contract"
    amount_per_contract: Decimal
    currency: CurrencyCode

    @field_validator("amount_per_contract", mode="before")
    @classmethod
    def _coerce_decimal(cls, value: Decimal | float | int | str) -> Decimal:
        return Decimal(str(value))

    @field_validator("amount_per_contract")
    @classmethod
    def _require_positive_amount(cls, value: Decimal) -> Decimal:
        if value <= Decimal("0"):
            raise ValueError("amount_per_contract must be positive; use zero_explicit for zero")
        return value


class ZeroExplicitCommission(BaseModel):
    """Intentionally select zero explicit commission for an instrument."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model: Literal["zero_explicit"] = "zero_explicit"
    reason: NonEmptyStr


CommissionModel: TypeAlias = Annotated[
    RateOfNotionalCommission | FixedPerContractCommission | ZeroExplicitCommission,
    Field(discriminator="model"),
]
_COMMISSION_MODEL_ADAPTER: TypeAdapter[CommissionModel] = TypeAdapter(CommissionModel)


class CommissionModelPatch(BaseModel):
    """Partial commission model used before inheritance is resolved."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model: CommissionModelName | None = None
    commission_rate_bps: Decimal | None = None
    amount_per_contract: Decimal | None = None
    currency: CurrencyCode | None = None
    reason: NonEmptyStr | None = None

    @field_validator("commission_rate_bps", "amount_per_contract", mode="before")
    @classmethod
    def _coerce_decimal(cls, value: Decimal | float | int | str | None) -> Decimal | None:
        if value is None:
            return None
        return Decimal(str(value))

    def as_payload(self) -> dict[str, object]:
        """Return a final-model validation payload with unset fields removed."""

        return self.model_dump(mode="json", exclude_none=True)


class ExecutionCostProfilePatch(BaseModel):
    """Partial execution-cost assumptions inherited by asset class then symbol."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    commission_model: CommissionModelPatch | None = None
    spread_model: SpreadModelPatch | None = None
    slippage_model: SlippageModelPatch | None = None


class ResolvedExecutionCostProfile(BaseModel):
    """Final validated execution-cost profile for one execution symbol."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: Symbol
    instrument_type: ExecutionInstrumentType
    asset_class: ExecutionAssetClass
    quote_currency: CurrencyCode
    commission_model: CommissionModel
    spread_model: SpreadModel
    slippage_model: SlippageModel

    @model_validator(mode="after")
    def _validate_profile_contracts(self) -> "ResolvedExecutionCostProfile":
        if (
            isinstance(self.commission_model, FixedPerContractCommission)
            and self.commission_model.currency != self.quote_currency
        ):
            raise ValueError(
                "fixed-fee currency must match quote_currency in Phase 2; "
                "FX conversion is not supported",
            )
        if (
            isinstance(self.spread_model, LogLinearDynamicHalfSpread)
            and not dynamic_spread_provenance_matches_symbol(self.spread_model, self.symbol)
        ):
            raise ValueError("dynamic spread provenance symbol must match resolved profile symbol")
        return self


class CommissionPreviewInput(BaseModel):
    """Per-leg input for deterministic commission preview."""

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=False)

    metadata: ExecutionInstrumentMetadata
    profile: ResolvedExecutionCostProfile
    quantity: Decimal
    price: Decimal

    @field_validator("quantity", "price", mode="before")
    @classmethod
    def _coerce_decimal(cls, value: Decimal | float | int | str) -> Decimal:
        return Decimal(str(value))

    @field_validator("price")
    @classmethod
    def _require_positive_price(cls, value: Decimal) -> Decimal:
        if value <= Decimal("0"):
            raise ValueError("commission preview price must be positive")
        return value


class CommissionPreview(BaseModel):
    """Resolved per-symbol commission amount for one order leg."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: Symbol
    commission_model_name: CommissionModelName
    quantity: Decimal
    price: Decimal
    absolute_notional_amount: Decimal
    notional_currency: CurrencyCode
    commission_amount: Decimal
    commission_currency: CurrencyCode


def validate_commission_model(payload: object) -> CommissionModel:
    """Validate a concrete commission model payload."""

    return _COMMISSION_MODEL_ADAPTER.validate_python(payload)


def resolve_execution_cost_profile(
    metadata: ExecutionInstrumentMetadata,
    asset_class_default: ExecutionCostProfilePatch | None,
    symbol_override: ExecutionCostProfilePatch | None = None,
) -> ResolvedExecutionCostProfile:
    """Resolve asset-class defaults plus a symbol override into a final profile."""

    if asset_class_default is None:
        raise ValueError(
            f"no explicit commission model resolved for {metadata.symbol}; "
            "zero commission requires zero_explicit",
        )

    commission_payload = _merge_commission_patches(
        asset_class_default.commission_model,
        symbol_override.commission_model if symbol_override is not None else None,
    )
    if not commission_payload:
        raise ValueError(
            f"no explicit commission model resolved for {metadata.symbol}; "
            "zero commission requires zero_explicit",
        )

    spread_payload = _merge_spread_patches(
        asset_class_default.spread_model,
        symbol_override.spread_model if symbol_override is not None else None,
    )
    if not spread_payload:
        raise ValueError(f"no explicit spread model resolved for {metadata.symbol}")

    slippage_payload = _merge_slippage_patches(
        asset_class_default.slippage_model,
        symbol_override.slippage_model if symbol_override is not None else None,
    )
    if not slippage_payload:
        raise ValueError(
            f"no explicit slippage model resolved for {metadata.symbol}; "
            "no slippage requires none_explicit",
        )

    commission_model = validate_commission_model(commission_payload)
    spread_model = validate_spread_model(spread_payload)
    slippage_model = validate_slippage_model(slippage_payload)
    return ResolvedExecutionCostProfile(
        symbol=metadata.symbol,
        instrument_type=metadata.instrument_type,
        asset_class=metadata.asset_class,
        quote_currency=metadata.quote_currency,
        commission_model=commission_model,
        spread_model=spread_model,
        slippage_model=slippage_model,
    )


def resolve_execution_cost_profiles(
    metadata_by_leg: Sequence[ExecutionInstrumentMetadata],
    asset_class_defaults: dict[ExecutionAssetClass, ExecutionCostProfilePatch],
    symbol_overrides: dict[str, ExecutionCostProfilePatch] | None = None,
) -> tuple[ResolvedExecutionCostProfile, ...]:
    """Resolve profiles per leg, preserving the input order and symbol identity."""

    overrides = {
        symbol.strip().upper(): patch for symbol, patch in (symbol_overrides or {}).items()
    }
    resolved: list[ResolvedExecutionCostProfile] = []
    for metadata in metadata_by_leg:
        default = asset_class_defaults.get(metadata.asset_class)
        if default is None:
            raise ValueError(f"missing asset-class commission default for {metadata.asset_class}")
        override = overrides.get(metadata.symbol.strip().upper())
        resolved.append(resolve_execution_cost_profile(metadata, default, override))
    return tuple(resolved)


def calculate_absolute_notional(
    metadata: ExecutionInstrumentMetadata,
    quantity: Decimal | float | int | str,
    price: Decimal | float | int | str,
) -> Decimal:
    """Calculate absolute notional using instrument unit metadata."""

    quantity_decimal = Decimal(str(quantity))
    price_decimal = Decimal(str(price))
    if price_decimal <= Decimal("0"):
        raise ValueError("notional price must be positive")

    if metadata.instrument_type is ExecutionInstrumentType.FUTURES:
        return abs(quantity_decimal) * price_decimal * metadata.multiplier

    if metadata.instrument_type in {
        ExecutionInstrumentType.CURRENCY_PAIR,
        ExecutionInstrumentType.CFD,
    }:
        return abs(quantity_decimal) * price_decimal * metadata.lot_size * metadata.multiplier

    if metadata.instrument_type is ExecutionInstrumentType.EQUITY:
        return abs(quantity_decimal) * price_decimal * metadata.multiplier

    raise ValueError("synthetic instruments require per-leg commission previews")


def preview_commission(input_: CommissionPreviewInput) -> CommissionPreview:
    """Return a deterministic commission preview for one symbol/order leg."""

    metadata = input_.metadata
    profile = input_.profile
    if profile.symbol != metadata.symbol:
        raise ValueError("commission profile symbol must match instrument metadata symbol")
    if profile.quote_currency != metadata.quote_currency:
        raise ValueError("commission profile quote_currency must match instrument metadata")

    notional = calculate_absolute_notional(metadata, input_.quantity, input_.price)
    commission_amount = _calculate_commission_amount(
        profile.commission_model,
        input_.quantity,
        notional,
    )
    return CommissionPreview(
        symbol=metadata.symbol,
        commission_model_name=CommissionModelName(profile.commission_model.model),
        quantity=input_.quantity,
        price=input_.price,
        absolute_notional_amount=notional,
        notional_currency=metadata.quote_currency,
        commission_amount=commission_amount,
        commission_currency=_commission_currency(profile),
    )


def preview_commissions_for_legs(
    inputs: Sequence[CommissionPreviewInput],
) -> tuple[CommissionPreview, ...]:
    """Preview commissions per symbol/per leg without synthetic spread netting."""

    return tuple(preview_commission(input_) for input_ in inputs)


def _merge_commission_patches(
    asset_class_default: CommissionModelPatch | None,
    symbol_override: CommissionModelPatch | None,
) -> dict[str, object]:
    payload = asset_class_default.as_payload() if asset_class_default is not None else {}
    if symbol_override is None:
        return payload

    override_payload = symbol_override.as_payload()
    if (
        "model" in override_payload
        and "model" in payload
        and override_payload["model"] != payload["model"]
    ):
        payload = {}
    payload.update(override_payload)
    return payload


def _merge_spread_patches(
    asset_class_default: SpreadModelPatch | None,
    symbol_override: SpreadModelPatch | None,
) -> dict[str, object]:
    payload = asset_class_default.as_payload() if asset_class_default is not None else {}
    if symbol_override is None:
        return payload

    override_payload = symbol_override.as_payload()
    if (
        "model" in override_payload
        and "model" in payload
        and override_payload["model"] != payload["model"]
    ):
        payload = {}
    payload.update(override_payload)
    return payload


def _merge_slippage_patches(
    asset_class_default: SlippageModelPatch | None,
    symbol_override: SlippageModelPatch | None,
) -> dict[str, object]:
    payload = asset_class_default.as_payload() if asset_class_default is not None else {}
    if symbol_override is None:
        return payload

    override_payload = symbol_override.as_payload()
    if (
        "model" in override_payload
        and "model" in payload
        and override_payload["model"] != payload["model"]
    ):
        payload = {}
    payload.update(override_payload)
    return payload


def _calculate_commission_amount(
    commission_model: CommissionModel,
    quantity: Decimal,
    absolute_notional_amount: Decimal,
) -> Decimal:
    if isinstance(commission_model, RateOfNotionalCommission):
        return absolute_notional_amount * commission_model.commission_rate_bps / Decimal("10000")
    if isinstance(commission_model, FixedPerContractCommission):
        return abs(quantity) * commission_model.amount_per_contract
    return Decimal("0")


def _commission_currency(profile: ResolvedExecutionCostProfile) -> CurrencyCode:
    if isinstance(profile.commission_model, FixedPerContractCommission):
        return profile.commission_model.currency
    return profile.quote_currency


__all__ = [
    "CommissionModel",
    "CommissionModelName",
    "CommissionModelPatch",
    "CommissionPreview",
    "CommissionPreviewInput",
    "ExecutionCostProfilePatch",
    "FixedPerContractCommission",
    "RateOfNotionalCommission",
    "ResolvedExecutionCostProfile",
    "SlippageModel",
    "SlippageModelPatch",
    "SpreadModel",
    "SpreadModelPatch",
    "ZeroExplicitCommission",
    "calculate_absolute_notional",
    "preview_commission",
    "preview_commissions_for_legs",
    "resolve_execution_cost_profile",
    "resolve_execution_cost_profiles",
    "validate_commission_model",
]
