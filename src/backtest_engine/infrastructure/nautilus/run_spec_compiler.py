"""Compile canonical run specs into explicit Nautilus payloads."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from backtest_engine.config.execution_costs import DynamicSpreadRuntimeProfile
from backtest_engine.config.execution_costs import execution_costs_config_hash
from backtest_engine.config.execution_costs import load_execution_costs
from backtest_engine.config.runtime import BacktestRunSpec, RuntimeSettings
from backtest_engine.core.errors import InfrastructureError
from backtest_engine.core.types import JsonValue, NonEmptyStr
from backtest_engine.domain.execution.instrument_metadata import (
    ExecutionAssetClass,
    ExecutionInstrumentMetadata,
    ExecutionInstrumentType,
)
from backtest_engine.domain.execution.spreads import LogLinearDynamicHalfSpread
from backtest_engine.domain.market.datasets import DatasetSpec
from backtest_engine.domain.strategy.specifications import PortfolioStrategySpec
from backtest_engine.infrastructure.data.parquet_normalizer import MaterializedDataset
from backtest_engine.infrastructure.nautilus.catalogs import CatalogItem, CatalogReference
from backtest_engine.infrastructure.nautilus.dynamic_spread_features import (
    build_dynamic_spread_feature_artifacts,
)
from backtest_engine.infrastructure.nautilus.execution_models import (
    EXECUTION_POLICY_FEE_MODEL_PATH,
    EXECUTION_POLICY_FILL_MODEL_PATH,
    EXECUTION_POLICY_MODEL_CONFIG_PATH,
    ExecutionPolicyInstrumentProfile,
    build_execution_policy_model_config_payload,
)
from backtest_engine.infrastructure.nautilus.portfolio_sizing import (
    CompiledSlotSizing,
    compile_portfolio_sizing,
)
from backtest_engine.infrastructure.nautilus.symbol_map import SymbolMapping, load_symbol_map


class NautilusImportableModelSpec(BaseModel):
    """Serializable importable model config for a Nautilus venue."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_path: NonEmptyStr
    config_path: NonEmptyStr
    config: dict[str, JsonValue]


class NautilusVenueSpec(BaseModel):
    """One compiled venue definition for the Nautilus runtime."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: NonEmptyStr
    oms_type: NonEmptyStr = "HEDGING"
    account_type: NonEmptyStr = "MARGIN"
    base_currency: NonEmptyStr
    starting_balances: tuple[NonEmptyStr, ...]
    book_type: NonEmptyStr = "L1_MBP"
    fill_model: NautilusImportableModelSpec | None = None
    fee_model: NautilusImportableModelSpec | None = None


class NautilusDataSpec(BaseModel):
    """One compiled market-data slice for the Nautilus runtime."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    catalog_root: Path
    instrument_id: NonEmptyStr
    bar_type: NonEmptyStr
    start_time_utc: datetime
    end_time_utc: datetime
    normalized_bar_data_path: Path | None = None


class NautilusStrategySpec(BaseModel):
    """One compiled runtime strategy definition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    strategy_id: NonEmptyStr
    implementation_id: NonEmptyStr
    strategy_path: NonEmptyStr
    config_path: NonEmptyStr
    config: dict[str, JsonValue] = Field(default_factory=dict)


class NautilusRunSpec(BaseModel):
    """A serializable Nautilus-native payload derived from one run spec."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: NonEmptyStr
    dataset_id: NonEmptyStr
    runtime_root: Path
    artifact_root: Path
    annualization_policy: NonEmptyStr
    catalog: CatalogReference
    venues: tuple[NautilusVenueSpec, ...]
    data: tuple[NautilusDataSpec, ...]
    strategies: tuple[NautilusStrategySpec, ...]
    strategy_ids: tuple[NonEmptyStr, ...]


class DatasetMaterializer(Protocol):
    """Materialize normalized datasets for compiled run specs."""

    def materialize(self, dataset: DatasetSpec) -> MaterializedDataset:
        """Return a persisted normalized dataset."""
        ...


class NautilusCatalogBuilder(Protocol):
    """Build a Nautilus catalog from a materialized dataset."""

    def build(self, dataset: MaterializedDataset) -> CatalogReference:
        """Return the persisted Nautilus catalog reference."""
        ...


class NautilusStrategyResolver(Protocol):
    """Resolve runtime strategy definitions from canonical strategy specs."""

    def resolve(
        self,
        strategy_spec: PortfolioStrategySpec,
        catalog: CatalogReference,
        slot_sizing: CompiledSlotSizing | None = None,
    ) -> NautilusStrategySpec:
        """Return one compiled runtime strategy definition."""
        ...


class NautilusRunSpecCompiler(Protocol):
    """Compile a canonical run spec into a Nautilus-native payload."""

    def compile(self, run_spec: BacktestRunSpec) -> NautilusRunSpec:
        """Return the vendor-facing payload for one run."""
        ...


@dataclass(frozen=True)
class CanonicalNautilusRunSpecCompiler:
    """Compile canonical run specs through data and catalog materialization."""

    runtime_settings: RuntimeSettings
    dataset_materializer: DatasetMaterializer
    catalog_builder: NautilusCatalogBuilder
    strategy_resolver: NautilusStrategyResolver
    execution_costs_path: Path | None = None
    symbol_map_path: Path | None = None

    def compile(self, run_spec: BacktestRunSpec) -> NautilusRunSpec:
        materialized_dataset = self.dataset_materializer.materialize(run_spec.dataset)
        catalog = self.catalog_builder.build(materialized_dataset)
        runtime_root = self.runtime_settings.nautilus_root / run_spec.run_id
        artifact_root = runtime_root / "artifacts"
        execution_models = _compile_execution_models(
            run_spec=run_spec,
            materialized_dataset=materialized_dataset,
            items=catalog.items,
            runtime_root=runtime_root,
            execution_costs_path=self.execution_costs_path,
            symbol_map_path=self.symbol_map_path,
        )
        sizing_by_slot: dict[str, CompiledSlotSizing] = {}
        if run_spec.portfolio_policy is not None:
            compiled_sizing = compile_portfolio_sizing(
                run_spec.strategies, run_spec.portfolio_policy
            )
            sizing_by_slot = {slot.slot_id: slot for slot in compiled_sizing.slots}
        normalized_paths_by_instrument_id = {
            artifact.manifest.nautilus_instrument_id: artifact.data_path
            for artifact in materialized_dataset.artifacts
        }
        data_specs = tuple(
            NautilusDataSpec(
                catalog_root=catalog.catalog_root,
                instrument_id=item.instrument_id,
                bar_type=item.bar_type,
                start_time_utc=run_spec.execution_window.start_utc,
                end_time_utc=run_spec.execution_window.end_utc,
                normalized_bar_data_path=normalized_paths_by_instrument_id.get(
                    item.instrument_id,
                ),
            )
            for item in catalog.items
        )
        venues = (_build_shared_venue(run_spec, catalog.items, execution_models),)
        strategies = tuple(
            self.strategy_resolver.resolve(
                strategy_spec=strategy_spec,
                catalog=catalog,
                slot_sizing=sizing_by_slot.get(strategy_spec.slot_id),
            )
            for strategy_spec in run_spec.strategies
        )
        return NautilusRunSpec(
            run_id=run_spec.run_id,
            dataset_id=run_spec.dataset.dataset_id,
            runtime_root=runtime_root,
            artifact_root=artifact_root,
            annualization_policy=(
                run_spec.portfolio_policy.annualization_policy
                if run_spec.portfolio_policy is not None
                else self.runtime_settings.default_annualization_policy
            ),
            catalog=catalog,
            venues=venues,
            data=data_specs,
            strategies=strategies,
            strategy_ids=tuple(strategy.strategy_id for strategy in strategies),
        )


def _build_shared_venue(
    run_spec: BacktestRunSpec,
    items: tuple[CatalogItem, ...],
    execution_models: "_CompiledExecutionModels",
) -> NautilusVenueSpec:
    venues = {item.venue for item in items}
    quote_currencies = {item.quote_currency for item in items}
    if len(venues) != 1 or len(quote_currencies) != 1:
        raise InfrastructureError(
            "compiled run spec requires one shared venue and quote currency",
            venues=",".join(sorted(venues)),
            quote_currencies=",".join(sorted(quote_currencies)),
            run_id=run_spec.run_id,
        )
    quote_currency = next(iter(quote_currencies))
    oms_type, account_type, book_type = _venue_defaults(run_spec)
    return NautilusVenueSpec(
        name=next(iter(venues)),
        oms_type=oms_type,
        account_type=account_type,
        base_currency=quote_currency,
        starting_balances=(f"{run_spec.capital_base.amount} {quote_currency}",),
        book_type=book_type,
        fill_model=execution_models.fill_model,
        fee_model=execution_models.fee_model,
    )


@dataclass(frozen=True)
class _CompiledExecutionModels:
    fill_model: NautilusImportableModelSpec | None
    fee_model: NautilusImportableModelSpec | None


def _compile_execution_models(
    *,
    run_spec: BacktestRunSpec,
    materialized_dataset: MaterializedDataset,
    items: tuple[CatalogItem, ...],
    runtime_root: Path,
    execution_costs_path: Path | None,
    symbol_map_path: Path | None,
) -> _CompiledExecutionModels:
    if run_spec.execution_policy is None:
        return _CompiledExecutionModels(fill_model=None, fee_model=None)

    execution_costs = load_execution_costs(execution_costs_path)
    config_content_hash = execution_costs_config_hash(execution_costs)
    _validate_execution_costs_config_hash(
        run_spec=run_spec,
        execution_costs_path=execution_costs_path,
        actual_config_content_hash=config_content_hash,
    )
    requested_profile_id = run_spec.execution_policy.execution_costs.profile_id
    if execution_costs.profile_id != requested_profile_id:
        raise InfrastructureError(
            "execution-cost profile_id did not match loaded profile",
            requested_profile_id=requested_profile_id,
            loaded_profile_id=execution_costs.profile_id,
            run_id=run_spec.run_id,
        )

    symbol_map = load_symbol_map(symbol_map_path)
    instrument_profiles: dict[str, ExecutionPolicyInstrumentProfile] = {}
    dynamic_runtime_profiles: dict[str, DynamicSpreadRuntimeProfile] = {}
    for item in items:
        if item.instrument_id in instrument_profiles:
            raise InfrastructureError(
                "duplicate Nautilus instrument_id in compiled catalog",
                instrument_id=item.instrument_id,
                run_id=run_spec.run_id,
            )
        try:
            mapping = symbol_map.resolve(item.symbol)
        except KeyError as exc:
            raise InfrastructureError(
                "missing symbol-map metadata for execution policy instrument",
                symbol=item.symbol,
                instrument_id=item.instrument_id,
                run_id=run_spec.run_id,
            ) from exc
        if mapping.nautilus_instrument_id != item.instrument_id:
            raise InfrastructureError(
                "symbol-map instrument_id does not match compiled catalog item",
                symbol=item.symbol,
                symbol_map_instrument_id=mapping.nautilus_instrument_id,
                catalog_instrument_id=item.instrument_id,
                run_id=run_spec.run_id,
            )
        metadata = _execution_metadata_from_mapping(mapping)
        try:
            profile = execution_costs.resolve_profile(metadata)
        except ValueError as exc:
            raise InfrastructureError(
                "failed to resolve execution-cost profile for Nautilus instrument",
                profile_id=execution_costs.profile_id,
                symbol=item.symbol,
                instrument_id=item.instrument_id,
                run_id=run_spec.run_id,
            ) from exc
        instrument_profiles[item.instrument_id] = ExecutionPolicyInstrumentProfile(
            instrument_id=item.instrument_id,
            metadata=metadata,
            profile=profile,
        )
        if isinstance(profile.spread_model, LogLinearDynamicHalfSpread):
            _require_dynamic_spread_config_hash(
                run_spec=run_spec,
                actual_config_content_hash=config_content_hash,
            )
            _validate_dynamic_spread_compile_provenance(
                spread_model=profile.spread_model,
                item=item,
                run_spec=run_spec,
            )
            dynamic_runtime_profile = execution_costs.resolve_dynamic_spread_runtime(metadata)
            if dynamic_runtime_profile is None:
                raise InfrastructureError(
                    "dynamic spread profile requires dynamic_spread_runtime config",
                    profile_id=execution_costs.profile_id,
                    symbol=item.symbol,
                    instrument_id=item.instrument_id,
                    run_id=run_spec.run_id,
                )
            dynamic_runtime_profiles[item.instrument_id] = dynamic_runtime_profile

    dynamic_feature_refs = build_dynamic_spread_feature_artifacts(
        materialized_dataset=materialized_dataset,
        catalog_items=items,
        execution_start_utc=run_spec.execution_window.start_utc,
        execution_end_utc=run_spec.execution_window.end_utc,
        runtime_root=runtime_root,
        instrument_profiles=instrument_profiles,
        runtime_profiles=dynamic_runtime_profiles,
    )
    config_payload = build_execution_policy_model_config_payload(
        instrument_profiles,
        dynamic_spread_features=dynamic_feature_refs,
    )
    return _CompiledExecutionModels(
        fill_model=NautilusImportableModelSpec(
            model_path=EXECUTION_POLICY_FILL_MODEL_PATH,
            config_path=EXECUTION_POLICY_MODEL_CONFIG_PATH,
            config=config_payload,
        ),
        fee_model=NautilusImportableModelSpec(
            model_path=EXECUTION_POLICY_FEE_MODEL_PATH,
            config_path=EXECUTION_POLICY_MODEL_CONFIG_PATH,
            config=config_payload,
        ),
    )


def _validate_execution_costs_config_hash(
    *,
    run_spec: BacktestRunSpec,
    execution_costs_path: Path | None,
    actual_config_content_hash: str,
) -> None:
    if run_spec.execution_policy is None:
        return
    expected_hash = run_spec.execution_policy.execution_costs.config_content_hash
    if expected_hash is not None and expected_hash != actual_config_content_hash:
        raise InfrastructureError(
            "execution-cost config_content_hash does not match loaded profile",
            expected_config_content_hash=expected_hash,
            actual_config_content_hash=actual_config_content_hash,
            run_id=run_spec.run_id,
        )
    if execution_costs_path is not None and expected_hash is None:
        raise InfrastructureError(
            "custom execution-cost profile requires config_content_hash",
            execution_costs_path=str(execution_costs_path),
            actual_config_content_hash=actual_config_content_hash,
            run_id=run_spec.run_id,
        )


def _validate_dynamic_spread_compile_provenance(
    *,
    spread_model: LogLinearDynamicHalfSpread,
    item: CatalogItem,
    run_spec: BacktestRunSpec,
) -> None:
    if spread_model.provenance.timeframe != item.timeframe:
        raise InfrastructureError(
            "dynamic spread provenance timeframe must match catalog item",
            symbol=item.symbol,
            instrument_id=item.instrument_id,
            provenance_timeframe=spread_model.provenance.timeframe,
            catalog_timeframe=item.timeframe,
            run_id=run_spec.run_id,
        )
    if spread_model.provenance.venue != item.venue:
        raise InfrastructureError(
            "dynamic spread provenance venue must match catalog item",
            symbol=item.symbol,
            instrument_id=item.instrument_id,
            provenance_venue=spread_model.provenance.venue,
            catalog_venue=item.venue,
            run_id=run_spec.run_id,
        )


def _require_dynamic_spread_config_hash(
    *,
    run_spec: BacktestRunSpec,
    actual_config_content_hash: str,
) -> None:
    if run_spec.execution_policy is None:
        return
    expected_hash = run_spec.execution_policy.execution_costs.config_content_hash
    if expected_hash is None:
        raise InfrastructureError(
            "dynamic spread profile requires config_content_hash",
            actual_config_content_hash=actual_config_content_hash,
            run_id=run_spec.run_id,
        )


def _execution_metadata_from_mapping(mapping: SymbolMapping) -> ExecutionInstrumentMetadata:
    if mapping.asset_class is None:
        raise InfrastructureError(
            "execution policy requires asset_class metadata",
            symbol=mapping.mt5_symbol,
            instrument_id=mapping.nautilus_instrument_id,
        )
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


def _venue_defaults(run_spec: BacktestRunSpec) -> tuple[str, str, str]:
    oms_type = "HEDGING"
    account_type = "MARGIN"
    book_type = "L1_MBP"
    if run_spec.execution_policy is None or run_spec.execution_policy.venue_overrides is None:
        return oms_type, account_type, book_type

    overrides = run_spec.execution_policy.venue_overrides
    return (
        overrides.oms_type or oms_type,
        overrides.account_type or account_type,
        overrides.book_type or book_type,
    )


__all__ = [
    "CanonicalNautilusRunSpecCompiler",
    "DatasetMaterializer",
    "NautilusImportableModelSpec",
    "NautilusCatalogBuilder",
    "NautilusDataSpec",
    "NautilusRunSpec",
    "NautilusRunSpecCompiler",
    "NautilusStrategyResolver",
    "NautilusStrategySpec",
    "NautilusVenueSpec",
]
