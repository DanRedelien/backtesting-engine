"""Resolve Nautilus strategies from concrete strategy cartridges."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import NoReturn, TypeAlias, cast

from pydantic import BaseModel, ValidationError

from backtest_engine.core.errors import InfrastructureError
from backtest_engine.core.types import JsonValue
from backtest_engine.domain.strategy.specifications import PortfolioStrategySpec
from backtest_engine.infrastructure.nautilus.catalogs import CatalogItem, CatalogReference
from backtest_engine.infrastructure.nautilus.portfolio_sizing import CompiledSlotSizing
from backtest_engine.infrastructure.nautilus.run_spec_compiler import NautilusStrategySpec
from backtest_engine.strategies.package_contracts import (
    CompiledSlotSizingView,
    ResolvedCatalogItem,
    StrategyPackageDefinition,
)
from backtest_engine.strategies.package_loader import load_strategy_package_definition


@dataclass(frozen=True)
class _ResolverSlotSizingView:
    slot_multiplier: float


_JsonPath: TypeAlias = tuple[str | int, ...]


@dataclass(frozen=True)
class PackageBackedNautilusStrategyResolver:
    """Resolve strategy cartridges into Nautilus runtime payloads."""

    def resolve(
        self,
        strategy_spec: PortfolioStrategySpec,
        catalog: CatalogReference,
        slot_sizing: CompiledSlotSizing | None = None,
    ) -> NautilusStrategySpec:
        implementation_id = strategy_spec.strategy.implementation_id
        definition = load_strategy_package_definition(implementation_id)
        _validate_leg_count(definition, strategy_spec)
        _validate_strategy_spec(definition, strategy_spec)
        parameters = _build_parameters(definition, strategy_spec)
        strategy_items = _resolve_strategy_catalog_items(catalog, strategy_spec)
        config = _build_config(
            definition=definition,
            strategy_spec=strategy_spec,
            parameters=parameters,
            strategy_items=strategy_items,
            slot_sizing=slot_sizing,
        )
        return NautilusStrategySpec(
            strategy_id=strategy_spec.strategy.strategy_id,
            implementation_id=implementation_id,
            strategy_path=definition.strategy_path,
            config_path=definition.config_path,
            config=config,
        )


def build_default_nautilus_strategy_resolver() -> PackageBackedNautilusStrategyResolver:
    """Return the default package-backed resolver for concrete strategies."""

    return PackageBackedNautilusStrategyResolver()


def _validate_leg_count(
    definition: StrategyPackageDefinition,
    strategy_spec: PortfolioStrategySpec,
) -> None:
    leg_count = len(strategy_spec.legs)
    if leg_count < definition.min_legs:
        raise InfrastructureError(
            "strategy package does not support so few legs",
            strategy_id=strategy_spec.strategy.strategy_id,
            implementation_id=strategy_spec.strategy.implementation_id,
            min_legs=definition.min_legs,
            actual_legs=leg_count,
        )
    if definition.max_legs is not None and leg_count > definition.max_legs:
        raise InfrastructureError(
            "strategy package does not support so many legs",
            strategy_id=strategy_spec.strategy.strategy_id,
            implementation_id=strategy_spec.strategy.implementation_id,
            max_legs=definition.max_legs,
            actual_legs=leg_count,
        )


def _validate_strategy_spec(
    definition: StrategyPackageDefinition,
    strategy_spec: PortfolioStrategySpec,
) -> None:
    validator = definition.validate_strategy_spec
    if validator is None:
        return
    try:
        validator(strategy_spec)
    except InfrastructureError:
        raise
    except Exception as exc:
        raise InfrastructureError(
            "strategy package validate_strategy_spec failed",
            strategy_id=strategy_spec.strategy.strategy_id,
            implementation_id=strategy_spec.strategy.implementation_id,
            error_type=type(exc).__name__,
        ) from exc


def _build_parameters(
    definition: StrategyPackageDefinition,
    strategy_spec: PortfolioStrategySpec,
) -> BaseModel:
    try:
        parameters = definition.build_parameters(strategy_spec)
    except InfrastructureError:
        raise
    except ValidationError as exc:
        raise InfrastructureError(
            "strategy package parameter validation failed",
            strategy_id=strategy_spec.strategy.strategy_id,
            implementation_id=strategy_spec.strategy.implementation_id,
            validation_errors=exc.errors(include_url=False),
        ) from exc
    except Exception as exc:
        raise InfrastructureError(
            "strategy package build_parameters failed",
            strategy_id=strategy_spec.strategy.strategy_id,
            implementation_id=strategy_spec.strategy.implementation_id,
            error_type=type(exc).__name__,
        ) from exc

    if not isinstance(parameters, BaseModel):
        raise InfrastructureError(
            "strategy package build_parameters must return a Pydantic model",
            strategy_id=strategy_spec.strategy.strategy_id,
            implementation_id=strategy_spec.strategy.implementation_id,
            returned_type=type(parameters).__name__,
        )
    return parameters


def _build_config(
    *,
    definition: StrategyPackageDefinition,
    strategy_spec: PortfolioStrategySpec,
    parameters: BaseModel,
    strategy_items: tuple[CatalogItem, ...],
    slot_sizing: CompiledSlotSizing | None,
) -> dict[str, JsonValue]:
    try:
        config = definition.build_config(
            strategy_spec,
            parameters,
            cast(tuple[ResolvedCatalogItem, ...], strategy_items),
            _slot_sizing_view(slot_sizing),
        )
    except InfrastructureError:
        raise
    except ValidationError as exc:
        raise InfrastructureError(
            "strategy package config validation failed",
            strategy_id=strategy_spec.strategy.strategy_id,
            implementation_id=strategy_spec.strategy.implementation_id,
            validation_errors=exc.errors(include_url=False),
        ) from exc
    except Exception as exc:
        raise InfrastructureError(
            "strategy package build_config failed",
            strategy_id=strategy_spec.strategy.strategy_id,
            implementation_id=strategy_spec.strategy.implementation_id,
            error_type=type(exc).__name__,
        ) from exc

    if not isinstance(config, dict):
        raise InfrastructureError(
            "strategy package build_config must return a dictionary",
            strategy_id=strategy_spec.strategy.strategy_id,
            implementation_id=strategy_spec.strategy.implementation_id,
            returned_type=type(config).__name__,
        )

    return _validate_config_payload(
        config,
        strategy_id=strategy_spec.strategy.strategy_id,
        implementation_id=strategy_spec.strategy.implementation_id,
    )


def _slot_sizing_view(slot_sizing: CompiledSlotSizing | None) -> CompiledSlotSizingView | None:
    if slot_sizing is None:
        return None
    return cast(
        CompiledSlotSizingView,
        _ResolverSlotSizingView(slot_multiplier=float(slot_sizing.slot_multiplier)),
    )


def _validate_config_payload(
    payload: object,
    *,
    strategy_id: str,
    implementation_id: str,
) -> dict[str, JsonValue]:
    return cast(
        dict[str, JsonValue],
        _validate_json_value(
            payload,
            path=("config",),
            strategy_id=strategy_id,
            implementation_id=implementation_id,
        ),
    )


def _validate_json_value(
    value: object,
    *,
    path: _JsonPath,
    strategy_id: str,
    implementation_id: str,
) -> JsonValue:
    value_type = type(value)
    if value is None or value_type in {str, bool, int}:
        return cast(JsonValue, value)
    if value_type is float:
        if math.isfinite(cast(float, value)):
            return cast(JsonValue, value)
        _raise_non_json_config_value(
            strategy_id=strategy_id,
            implementation_id=implementation_id,
            path=path,
            value=value,
            reason="JSON numbers must be finite",
        )
    if value_type is list:
        return cast(
            JsonValue,
            [
                _validate_json_value(
                    item,
                    path=(*path, index),
                    strategy_id=strategy_id,
                    implementation_id=implementation_id,
                )
                for index, item in enumerate(cast(list[object], value))
            ],
        )
    if value_type is dict:
        validated: dict[str, JsonValue] = {}
        for key, item in cast(dict[object, object], value).items():
            if type(key) is not str:
                _raise_non_json_config_value(
                    strategy_id=strategy_id,
                    implementation_id=implementation_id,
                    path=(*path, "<key>"),
                    value=key,
                    reason="JSON object keys must be strings",
                )
            validated[key] = _validate_json_value(
                item,
                path=(*path, key),
                strategy_id=strategy_id,
                implementation_id=implementation_id,
            )
        return cast(JsonValue, validated)
    _raise_non_json_config_value(
        strategy_id=strategy_id,
        implementation_id=implementation_id,
        path=path,
        value=value,
        reason="value is not an exact JSON-compatible Python type",
    )


def _raise_non_json_config_value(
    *,
    strategy_id: str,
    implementation_id: str,
    path: _JsonPath,
    value: object,
    reason: str,
) -> NoReturn:
    raise InfrastructureError(
        "strategy package build_config returned non-serializable config payload",
        strategy_id=strategy_id,
        implementation_id=implementation_id,
        json_path=_format_json_path(path),
        invalid_type=type(value).__name__,
        reason=reason,
    )


def _format_json_path(path: _JsonPath) -> str:
    formatted = str(path[0])
    for part in path[1:]:
        if isinstance(part, int):
            formatted += f"[{part}]"
        else:
            formatted += f".{part}"
    return formatted


def _resolve_strategy_catalog_items(
    catalog: CatalogReference,
    strategy_spec: PortfolioStrategySpec,
) -> tuple[CatalogItem, ...]:
    items = tuple(_find_catalog_item(catalog, symbol=leg.symbol) for leg in strategy_spec.legs)
    if not items:
        raise InfrastructureError(
            "strategy must resolve at least one catalog item",
            strategy_id=strategy_spec.strategy.strategy_id,
            implementation_id=strategy_spec.strategy.implementation_id,
        )
    return items


def _find_catalog_item(catalog: CatalogReference, symbol: str) -> CatalogItem:
    for item in catalog.items:
        if item.symbol == symbol:
            return item
    raise InfrastructureError(
        "catalog does not contain a materialized symbol required by strategy",
        symbol=symbol,
        dataset_id=catalog.dataset_id,
    )


__all__ = [
    "PackageBackedNautilusStrategyResolver",
    "build_default_nautilus_strategy_resolver",
]
