"""Nautilus importable execution models for explicit run policies."""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, Mapping, cast

import pandas as pd
from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from nautilus_trader.backtest.models.fee import FeeModel
from nautilus_trader.backtest.models.fill import FillModel
from nautilus_trader.common.config import NautilusConfig
from nautilus_trader.model.book import OrderBook
from nautilus_trader.model.data import BookOrder
from nautilus_trader.model.enums import BookType
from nautilus_trader.model.enums import OrderSide as NautilusOrderSide
from nautilus_trader.model.enums import OrderType as NautilusOrderType
from nautilus_trader.model.objects import Currency
from nautilus_trader.model.objects import Money
from nautilus_trader.model.objects import Price
from nautilus_trader.model.objects import Quantity

from backtest_engine.core.enums import OrderSide, OrderType
from backtest_engine.core.errors import InfrastructureError
from backtest_engine.core.types import JsonValue, NonEmptyStr
from backtest_engine.domain.execution.commissions import (
    CommissionPreviewInput,
    ResolvedExecutionCostProfile,
    preview_commission,
)
from backtest_engine.domain.execution.cost_preview import (
    ExecutionCostPreviewInput,
    ExecutionCostPreviewStatus,
    preview_execution_cost,
)
from backtest_engine.domain.execution.instrument_metadata import ExecutionInstrumentMetadata
from backtest_engine.domain.execution.spreads import (
    DynamicSpreadFeatureInput,
    LogLinearDynamicHalfSpread,
)
from backtest_engine.infrastructure.nautilus.dynamic_spread_features import (
    DynamicSpreadFeatureArtifactManifest,
    DynamicSpreadFeatureArtifactRef,
    FEATURE_OBSERVED_AT_POLICY,
    compute_file_sha256,
)


EXECUTION_POLICY_FEE_MODEL_PATH = (
    "backtest_engine.infrastructure.nautilus.execution_models:ExecutionPolicyFeeModel"
)
EXECUTION_POLICY_FILL_MODEL_PATH = (
    "backtest_engine.infrastructure.nautilus.execution_models:ExecutionPolicyFillModel"
)
EXECUTION_POLICY_MODEL_CONFIG_PATH = (
    "backtest_engine.infrastructure.nautilus.execution_models:ExecutionPolicyModelConfig"
)
_SYNTHETIC_LIQUIDITY_FLOOR = Decimal("1000000")
_TimestampLike = int | float | str | datetime | pd.Timestamp
_DynamicRuntimeOrderType = Literal["market"]


class ExecutionPolicyInstrumentProfile(BaseModel):
    """One validated execution-cost profile keyed by Nautilus instrument ID."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    instrument_id: NonEmptyStr
    metadata: ExecutionInstrumentMetadata
    profile: ResolvedExecutionCostProfile

    @model_validator(mode="after")
    def _validate_profile_matches_metadata(self) -> "ExecutionPolicyInstrumentProfile":
        if self.profile.symbol != self.metadata.symbol:
            raise ValueError("execution profile symbol must match metadata symbol")
        if self.profile.quote_currency != self.metadata.quote_currency:
            raise ValueError("execution profile quote_currency must match metadata quote_currency")
        return self

    def as_config_payload(self) -> dict[str, JsonValue]:
        """Return a JSON-safe payload for Nautilus importable model configs."""

        return cast(dict[str, JsonValue], self.model_dump(mode="json"))


class ExecutionPolicyModelConfig(NautilusConfig, frozen=True):
    """Shared importable config for the policy fee and fill adapters."""

    instrument_profiles: dict[str, dict[str, Any]]
    dynamic_spread_features: dict[str, dict[str, Any]] | None = None


class ExecutionPolicyFeeModel(FeeModel):
    """Apply configured deterministic commission contracts inside Nautilus."""

    def __init__(self, config: ExecutionPolicyModelConfig | None = None) -> None:
        self._profiles = _profiles_from_config(config)

    def get_commission(
        self,
        order: Any,
        fill_qty: Any,
        fill_px: Any,
        instrument: Any,
    ) -> Money:
        del order
        instrument_profile = _profile_for_instrument(self._profiles, instrument)
        preview = preview_commission(
            CommissionPreviewInput(
                metadata=instrument_profile.metadata,
                profile=instrument_profile.profile,
                quantity=fill_qty.as_decimal(),
                price=fill_px.as_decimal(),
            ),
        )
        return Money(
            preview.commission_amount,
            Currency.from_str(preview.commission_currency),
        )


class ExecutionPolicyFillModel(FillModel):
    """Create synthetic adverse top-of-book levels for market-like orders."""

    def __init__(self, config: ExecutionPolicyModelConfig | None = None) -> None:
        super().__init__(
            prob_fill_on_limit=1.0,
            prob_fill_on_stop=1.0,
            prob_slippage=0.0,
        )
        self._profiles = _profiles_from_config(config)
        self._dynamic_spread_features = _dynamic_spread_feature_tables_from_config(config)

    def get_orderbook_for_fill_simulation(
        self,
        instrument: Any,
        order: Any,
        best_bid: Price,
        best_ask: Price,
    ) -> OrderBook | None:
        domain_order_type = _domain_order_type_or_none(order.order_type)
        if domain_order_type is None:
            return None

        instrument_profile = _profile_for_instrument(self._profiles, instrument)
        instrument_id = _instrument_id_value(instrument)
        if _dynamic_spread_uses_default_path(
            feature_tables=self._dynamic_spread_features,
            instrument_id=instrument_id,
            instrument_profile=instrument_profile,
            domain_order_type=domain_order_type,
        ):
            return None

        domain_side = _domain_order_side(order.side)
        reference_price = (
            best_ask.as_decimal() if domain_side is OrderSide.BUY else best_bid.as_decimal()
        )
        dynamic_spread_features = _dynamic_spread_features_for_order(
            feature_tables=self._dynamic_spread_features,
            instrument_id=instrument_id,
            instrument_profile=instrument_profile,
            order=order,
            domain_order_type=domain_order_type,
        )
        preview = preview_execution_cost(
            ExecutionCostPreviewInput(
                metadata=instrument_profile.metadata,
                profile=instrument_profile.profile,
                side=domain_side,
                order_type=domain_order_type,
                quantity=order.quantity.as_decimal(),
                reference_price=reference_price,
                dynamic_spread_features=dynamic_spread_features,
            ),
        )
        if (
            preview.status is not ExecutionCostPreviewStatus.APPLIED
            or preview.final_effective_price is None
        ):
            raise InfrastructureError(
                "execution policy fill model could not derive an applied fill price",
                instrument_id=_instrument_id_value(instrument),
                order_type=str(order.order_type),
            )

        return _synthetic_top_of_book(
            instrument=instrument,
            side=domain_side,
            order_quantity=order.quantity,
            best_bid=best_bid,
            best_ask=best_ask,
            effective_price=preview.final_effective_price,
        )


def build_execution_policy_model_config_payload(
    instrument_profiles: Mapping[str, ExecutionPolicyInstrumentProfile],
    *,
    dynamic_spread_features: Mapping[str, DynamicSpreadFeatureArtifactRef] | None = None,
) -> dict[str, JsonValue]:
    """Build the immutable JSON-safe config shared by policy fee/fill models."""

    return {
        "instrument_profiles": {
            instrument_id: profile.as_config_payload()
            for instrument_id, profile in sorted(instrument_profiles.items())
        },
        "dynamic_spread_features": {
            instrument_id: artifact_ref.as_config_payload()
            for instrument_id, artifact_ref in sorted((dynamic_spread_features or {}).items())
        },
    }


def _profiles_from_config(
    config: ExecutionPolicyModelConfig | None,
) -> dict[str, ExecutionPolicyInstrumentProfile]:
    if config is None:
        raise InfrastructureError("execution policy model requires importable config")

    profiles: dict[str, ExecutionPolicyInstrumentProfile] = {}
    try:
        raw_profiles = config.instrument_profiles
        for instrument_id, payload in raw_profiles.items():
            profile = ExecutionPolicyInstrumentProfile.model_validate(payload)
            if profile.instrument_id != instrument_id:
                raise InfrastructureError(
                    "execution policy profile key must match payload instrument_id",
                    profile_key=instrument_id,
                    instrument_id=profile.instrument_id,
                )
            profiles[instrument_id] = profile
    except ValidationError as exc:
        raise InfrastructureError("invalid execution policy model config") from exc

    if not profiles:
        raise InfrastructureError("execution policy model config must contain instruments")
    return profiles


@dataclass(frozen=True)
class _DynamicSpreadFeatureTable:
    instrument_id: str
    fill_timestamps_utc: tuple[datetime, ...]
    features: tuple[DynamicSpreadFeatureInput, ...]
    dynamic_order_types: tuple[_DynamicRuntimeOrderType, ...]

    def feature_for_fill_timestamp(self, fill_timestamp_utc: datetime) -> DynamicSpreadFeatureInput:
        """Return the configured feature row for the exact runtime fill timestamp."""

        index = bisect_left(self.fill_timestamps_utc, fill_timestamp_utc)
        if (
            index == len(self.fill_timestamps_utc)
            or self.fill_timestamps_utc[index] != fill_timestamp_utc
        ):
            raise InfrastructureError(
                "dynamic spread feature table has no exact row for fill timestamp",
                instrument_id=self.instrument_id,
                fill_timestamp_utc=fill_timestamp_utc.isoformat(),
                first_feature_fill_timestamp_utc=(
                    self.fill_timestamps_utc[0].isoformat() if self.fill_timestamps_utc else None
                ),
                last_feature_fill_timestamp_utc=(
                    self.fill_timestamps_utc[-1].isoformat() if self.fill_timestamps_utc else None
                ),
            )
        return self.features[index]


def _dynamic_spread_feature_tables_from_config(
    config: ExecutionPolicyModelConfig | None,
) -> dict[str, _DynamicSpreadFeatureTable]:
    if config is None:
        return {}
    tables: dict[str, _DynamicSpreadFeatureTable] = {}
    try:
        for instrument_id, payload in (config.dynamic_spread_features or {}).items():
            artifact_ref = DynamicSpreadFeatureArtifactRef.model_validate(payload)
            if artifact_ref.instrument_id != instrument_id:
                raise InfrastructureError(
                    "dynamic spread feature key must match payload instrument_id",
                    profile_key=instrument_id,
                    instrument_id=artifact_ref.instrument_id,
                )
            tables[instrument_id] = _load_dynamic_spread_feature_table(artifact_ref)
    except ValidationError as exc:
        raise InfrastructureError("invalid dynamic spread feature config") from exc
    return tables


def _load_dynamic_spread_feature_table(
    artifact_ref: DynamicSpreadFeatureArtifactRef,
) -> _DynamicSpreadFeatureTable:
    manifest_path = Path(artifact_ref.manifest_path)
    feature_table_path = Path(artifact_ref.feature_table_path)
    if compute_file_sha256(manifest_path) != artifact_ref.manifest_hash:
        raise InfrastructureError(
            "dynamic spread feature manifest hash mismatch",
            instrument_id=artifact_ref.instrument_id,
            manifest_path=str(manifest_path),
        )
    try:
        manifest = DynamicSpreadFeatureArtifactManifest.model_validate_json(
            manifest_path.read_text(encoding="utf-8"),
        )
    except Exception as exc:
        raise InfrastructureError(
            "failed to load dynamic spread feature manifest",
            instrument_id=artifact_ref.instrument_id,
            manifest_path=str(manifest_path),
        ) from exc
    if manifest.schema_version != artifact_ref.schema_version:
        raise InfrastructureError(
            "dynamic spread feature manifest schema version mismatch",
            instrument_id=artifact_ref.instrument_id,
            manifest_schema_version=manifest.schema_version,
            config_schema_version=artifact_ref.schema_version,
        )
    if manifest.feature_observed_at_policy != FEATURE_OBSERVED_AT_POLICY:
        raise InfrastructureError(
            "dynamic spread feature observed-at policy mismatch",
            instrument_id=artifact_ref.instrument_id,
            manifest_feature_observed_at_policy=manifest.feature_observed_at_policy,
            expected_feature_observed_at_policy=FEATURE_OBSERVED_AT_POLICY,
        )
    if (
        manifest.instrument_id != artifact_ref.instrument_id
        or manifest.model_hash != artifact_ref.model_hash
        or manifest.runtime_config_hash != artifact_ref.runtime_config_hash
        or _manifest_feature_table_path(manifest, manifest_path) != feature_table_path
        or manifest.feature_table_hash != artifact_ref.feature_table_hash
        or manifest.volatility_floor_price != artifact_ref.volatility_floor_price
        or manifest.volatility_signal_method != artifact_ref.volatility_signal_method
        or manifest.dynamic_order_types != artifact_ref.dynamic_order_types
    ):
        raise InfrastructureError(
            "dynamic spread feature manifest does not match fill-model config",
            instrument_id=artifact_ref.instrument_id,
        )
    if compute_file_sha256(feature_table_path) != artifact_ref.feature_table_hash:
        raise InfrastructureError(
            "dynamic spread feature table hash mismatch",
            instrument_id=artifact_ref.instrument_id,
            feature_table_path=str(feature_table_path),
        )
    try:
        frame = pd.read_parquet(feature_table_path)
    except Exception as exc:
        raise InfrastructureError(
            "failed to read dynamic spread feature table",
            instrument_id=artifact_ref.instrument_id,
            feature_table_path=str(feature_table_path),
        ) from exc

    features = tuple(_feature_input_from_row(row) for _, row in frame.iterrows())
    fill_timestamps = tuple(feature.fill_timestamp_utc for feature in features)
    if fill_timestamps != tuple(sorted(fill_timestamps)):
        raise InfrastructureError(
            "dynamic spread feature fill timestamps must be sorted",
            instrument_id=artifact_ref.instrument_id,
        )
    if len(fill_timestamps) != len(set(fill_timestamps)):
        raise InfrastructureError(
            "dynamic spread feature fill timestamps must be unique",
            instrument_id=artifact_ref.instrument_id,
        )
    if manifest.row_count != len(features):
        raise InfrastructureError(
            "dynamic spread feature manifest row count does not match table",
            instrument_id=artifact_ref.instrument_id,
            manifest_row_count=manifest.row_count,
            table_row_count=len(features),
        )
    return _DynamicSpreadFeatureTable(
        instrument_id=artifact_ref.instrument_id,
        fill_timestamps_utc=fill_timestamps,
        features=features,
        dynamic_order_types=artifact_ref.dynamic_order_types,
    )


def _manifest_feature_table_path(
    manifest: DynamicSpreadFeatureArtifactManifest,
    manifest_path: Path,
) -> Path:
    feature_table_path = Path(manifest.feature_table_path)
    if feature_table_path.is_absolute():
        return feature_table_path
    return manifest_path.parent / feature_table_path


def _feature_input_from_row(row: pd.Series) -> DynamicSpreadFeatureInput:
    payload = cast(dict[str, Any], row.to_dict())
    payload["fill_timestamp_utc"] = _coerce_runtime_timestamp(
        payload["fill_timestamp_utc"],
    )
    payload["feature_observed_at_utc"] = _coerce_runtime_timestamp(
        payload["feature_observed_at_utc"],
    )
    return DynamicSpreadFeatureInput.model_validate(payload)


def _dynamic_spread_features_for_order(
    *,
    feature_tables: Mapping[str, _DynamicSpreadFeatureTable],
    instrument_id: str,
    instrument_profile: ExecutionPolicyInstrumentProfile,
    order: Any,
    domain_order_type: OrderType,
) -> DynamicSpreadFeatureInput | None:
    if not isinstance(instrument_profile.profile.spread_model, LogLinearDynamicHalfSpread):
        return None
    feature_table = _dynamic_spread_feature_table(feature_tables, instrument_id)
    runtime_order_type = _dynamic_runtime_order_type(domain_order_type)
    if runtime_order_type not in feature_table.dynamic_order_types:
        return None
    return feature_table.feature_for_fill_timestamp(
        _simulation_timestamp_utc_from_market_order(order),
    )


def _dynamic_spread_uses_default_path(
    *,
    feature_tables: Mapping[str, _DynamicSpreadFeatureTable],
    instrument_id: str,
    instrument_profile: ExecutionPolicyInstrumentProfile,
    domain_order_type: OrderType,
) -> bool:
    if not isinstance(instrument_profile.profile.spread_model, LogLinearDynamicHalfSpread):
        return False
    feature_table = _dynamic_spread_feature_table(feature_tables, instrument_id)
    runtime_order_type = _dynamic_runtime_order_type(domain_order_type)
    return runtime_order_type not in feature_table.dynamic_order_types


def _dynamic_spread_feature_table(
    feature_tables: Mapping[str, _DynamicSpreadFeatureTable],
    instrument_id: str,
) -> _DynamicSpreadFeatureTable:
    try:
        return feature_tables[instrument_id]
    except KeyError as exc:
        raise InfrastructureError(
            "dynamic spread profile missing compiled feature table",
            instrument_id=instrument_id,
        ) from exc


def _dynamic_runtime_order_type(domain_order_type: OrderType) -> _DynamicRuntimeOrderType | None:
    if domain_order_type is OrderType.MARKET:
        return "market"
    return None


def _simulation_timestamp_utc_from_market_order(order: Any) -> datetime:
    timestamp = _unix_ns_to_utc_datetime(getattr(order, "ts_init", None))
    if timestamp is None:
        raise InfrastructureError(
            "dynamic spread MARKET fill model requires a nonzero ts_init timestamp",
        )
    return timestamp


def _unix_ns_to_utc_datetime(value: object) -> datetime | None:
    unix_ns: int
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        unix_ns = value
    elif isinstance(value, str):
        try:
            unix_ns = int(value)
        except ValueError:
            return None
    else:
        return None
    if unix_ns <= 0:
        return None
    seconds, nanoseconds = divmod(unix_ns, 1_000_000_000)
    return datetime.fromtimestamp(seconds, tz=UTC).replace(microsecond=nanoseconds // 1_000)


def _coerce_runtime_timestamp(value: _TimestampLike) -> datetime:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize(UTC)
    else:
        timestamp = timestamp.tz_convert(UTC)
    return timestamp.to_pydatetime()


def _profile_for_instrument(
    profiles: Mapping[str, ExecutionPolicyInstrumentProfile],
    instrument: Any,
) -> ExecutionPolicyInstrumentProfile:
    instrument_id = _instrument_id_value(instrument)
    try:
        return profiles[instrument_id]
    except KeyError as exc:
        raise InfrastructureError(
            "execution policy profile missing for Nautilus instrument",
            instrument_id=instrument_id,
        ) from exc


def _instrument_id_value(instrument: Any) -> str:
    value = getattr(getattr(instrument, "id", None), "value", None)
    return str(value if value is not None else instrument.id)


def _domain_order_side(side: Any) -> OrderSide:
    if side == NautilusOrderSide.BUY:
        return OrderSide.BUY
    if side == NautilusOrderSide.SELL:
        return OrderSide.SELL
    raise InfrastructureError("unsupported Nautilus order side", order_side=str(side))


def _domain_order_type_or_none(order_type: Any) -> OrderType | None:
    if order_type == NautilusOrderType.MARKET:
        return OrderType.MARKET
    if order_type in {
        NautilusOrderType.STOP_MARKET,
        NautilusOrderType.TRAILING_STOP_MARKET,
    }:
        return OrderType.STOP
    if order_type in {
        NautilusOrderType.LIMIT,
        NautilusOrderType.STOP_LIMIT,
        NautilusOrderType.MARKET_TO_LIMIT,
        NautilusOrderType.LIMIT_IF_TOUCHED,
        NautilusOrderType.TRAILING_STOP_LIMIT,
    }:
        return None
    raise InfrastructureError("unsupported Nautilus order type", order_type=str(order_type))


def _synthetic_top_of_book(
    *,
    instrument: Any,
    side: OrderSide,
    order_quantity: Quantity,
    best_bid: Price,
    best_ask: Price,
    effective_price: Decimal,
) -> OrderBook:
    bid_price = best_bid
    ask_price = best_ask
    if side is OrderSide.BUY:
        ask_price = _make_price(instrument, effective_price)
    else:
        bid_price = _make_price(instrument, effective_price)

    book = OrderBook(
        instrument_id=instrument.id,
        book_type=BookType.L2_MBP,
    )
    size = _synthetic_level_size(instrument=instrument, order_quantity=order_quantity)
    book.add(
        BookOrder(
            side=NautilusOrderSide.BUY,
            price=bid_price,
            size=size,
            order_id=1,
        ),
        0,
        0,
    )
    book.add(
        BookOrder(
            side=NautilusOrderSide.SELL,
            price=ask_price,
            size=size,
            order_id=2,
        ),
        0,
        0,
    )
    return book


def _synthetic_level_size(*, instrument: Any, order_quantity: Quantity) -> Quantity:
    order_quantity_value = order_quantity.as_decimal()
    if order_quantity_value <= 0:
        raise InfrastructureError(
            "execution policy fill model requires positive order quantity",
            quantity=str(order_quantity_value),
        )
    if order_quantity_value >= _SYNTHETIC_LIQUIDITY_FLOOR:
        return order_quantity
    return Quantity(_SYNTHETIC_LIQUIDITY_FLOOR, instrument.size_precision)


def _make_price(instrument: Any, value: Decimal) -> Price:
    return instrument.make_price(value)


__all__ = [
    "EXECUTION_POLICY_FEE_MODEL_PATH",
    "EXECUTION_POLICY_FILL_MODEL_PATH",
    "EXECUTION_POLICY_MODEL_CONFIG_PATH",
    "ExecutionPolicyFeeModel",
    "ExecutionPolicyFillModel",
    "ExecutionPolicyInstrumentProfile",
    "ExecutionPolicyModelConfig",
    "build_execution_policy_model_config_payload",
]
