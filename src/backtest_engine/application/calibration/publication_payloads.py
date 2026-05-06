"""Generated execution-cost payload builders for spread calibration publication."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

from backtest_engine.application.calibration.contracts import (
    SpreadCalibrationPublicationCommand,
)
from backtest_engine.application.calibration.fitting import (
    CalibrationFitParameters,
    PreparedCalibrationRow,
)
from backtest_engine.application.calibration.publication_helpers import (
    canonical_symbol,
    decimal_string,
    isoformat_utc,
    timeframe_delta,
)
from backtest_engine.application.calibration.publication_types import SymbolBounds
from backtest_engine.config.execution_costs import load_execution_costs
from backtest_engine.core.errors import ApplicationError
from backtest_engine.domain.execution.instrument_metadata import (
    ExecutionAssetClass,
    ExecutionInstrumentMetadata,
    ExecutionInstrumentType,
)
from backtest_engine.domain.execution.spreads import LogLinearDynamicHalfSpread
from backtest_engine.infrastructure.nautilus.symbol_map import SymbolMapping


def build_execution_costs_payload(
    *,
    command: SpreadCalibrationPublicationCommand,
    fit: CalibrationFitParameters,
    bounds_by_symbol: dict[str, SymbolBounds],
    mappings_by_symbol: dict[str, SymbolMapping],
    train_rows: tuple[PreparedCalibrationRow, ...],
) -> dict[str, Any]:
    """Build the generated execution-cost YAML payload from validated inputs."""

    result = command.calibration_result
    base_config = load_execution_costs(command.base_execution_costs_path)
    payload = base_config.model_dump(mode="json", exclude_none=True)
    payload["owner"] = command.owner
    payload["description"] = command.description or (
        "Generated offline EDGE dynamic spread calibration profile. "
        "Bundled defaults remain static; this file is an explicit runtime input."
    )

    symbol_overrides = payload.setdefault("symbol_overrides", {})
    if not isinstance(symbol_overrides, dict):
        raise ApplicationError("base execution-cost payload symbol_overrides was not a mapping")

    for symbol, mapping in sorted(mappings_by_symbol.items()):
        bounds = bounds_by_symbol[symbol]
        existing_override = symbol_overrides.get(symbol, {})
        if not isinstance(existing_override, dict):
            raise ApplicationError(
                "base execution-cost symbol override was not a mapping",
                symbol=symbol,
            )
        symbol_train_rows = tuple(row for row in train_rows if row.symbol == symbol)
        if not symbol_train_rows:
            raise ApplicationError(
                "spread calibration publication requires train rows for every symbol",
                symbol=symbol,
            )
        symbol_train_start = min(row.fill_timestamp_utc for row in symbol_train_rows)
        symbol_train_end = max(row.fill_timestamp_utc for row in symbol_train_rows)
        if symbol_train_start >= symbol_train_end:
            symbol_train_end = symbol_train_start + timeframe_delta(result.estimator_timeframe)
        source_fingerprint = source_fingerprint_for_mapping(result.source_fingerprints, mapping)
        dynamic_spread_payload = {
            "model": "log_linear_dynamic_half_spread",
            "base_half_spread_price": decimal_string(bounds.base_half_spread_price),
            "min_half_spread_price": decimal_string(bounds.min_half_spread_price),
            "max_half_spread_price": decimal_string(bounds.max_half_spread_price),
            "volatility_weight": decimal_string(fit.volatility_weight),
            "liquidity_weight": decimal_string(fit.liquidity_weight),
            "session_buckets": [
                {
                    "session_bucket_id": bucket.session_bucket_id,
                    "session_adjustment_log": decimal_string(
                        fit.session_adjustments_log.get(bucket.session_bucket_id, 0.0)
                    ),
                }
                for bucket in result.session_buckets
            ],
            "provenance": {
                "symbol": mapping.mt5_symbol,
                "venue": mapping.venue,
                "timeframe": command.target_timeframe,
                "provider_or_broker": f"edge_offline:{result.dataset_id}",
                "sample_start_utc": isoformat_utc(symbol_train_start),
                "sample_end_utc": isoformat_utc(symbol_train_end),
                "row_count": len(symbol_train_rows),
                "data_quality_notes": (
                    "PASS source validation; signed EDGE estimates reset to zero; "
                    f"source_fingerprint={source_fingerprint}"
                ),
                "sample_role": "train_only_phase2_fit",
                "estimator_method": (
                    "EDGE rolling completed-window estimator; "
                    f"estimator_timeframe={result.estimator_timeframe}; "
                    f"edge_window_bars={result.edge_window_bars}"
                ),
                "conversion_method": (
                    "price-unit half_spread = last_window_close * "
                    "max(0, signed_edge_full_spread_frac) / 2"
                ),
            },
        }
        symbol_overrides[symbol] = {**existing_override, "spread_model": dynamic_spread_payload}

    dynamic_runtime = payload.get("dynamic_spread_runtime")
    if dynamic_runtime is None:
        dynamic_runtime = {"asset_class_defaults": {}, "symbol_overrides": {}}
    if not isinstance(dynamic_runtime, dict):
        raise ApplicationError("base dynamic_spread_runtime payload was not a mapping")
    dynamic_runtime.setdefault("asset_class_defaults", {})
    runtime_symbol_overrides = dynamic_runtime.setdefault("symbol_overrides", {})
    if not isinstance(runtime_symbol_overrides, dict):
        raise ApplicationError("dynamic_spread_runtime symbol_overrides was not a mapping")
    runtime_payload = runtime_profile_payload(command)
    for symbol in mappings_by_symbol:
        runtime_symbol_overrides[symbol] = runtime_payload
    payload["dynamic_spread_runtime"] = dynamic_runtime
    return payload


def runtime_profile_payload(command: SpreadCalibrationPublicationCommand) -> dict[str, Any]:
    """Return dynamic-spread runtime feature settings for published symbols."""

    result = command.calibration_result
    return {
        "volatility_short_window_bars": result.volatility_short_window_bars,
        "volatility_baseline_window_bars": result.volatility_baseline_window_bars,
        "volatility_floor_price": decimal_string(result.volatility_floor_price),
        "volatility_signal_method": "true_range_atr",
        "volume_baseline_window_bars": result.volume_baseline_window_bars,
        "volume_floor": decimal_string(result.volume_floor),
        "dynamic_order_types": ["market"],
        "session_buckets": [
            {
                "session_bucket_id": bucket.session_bucket_id,
                "weekdays": list(bucket.weekdays),
                "start_time_utc": bucket.start_time_utc.isoformat(),
                "end_time_utc": bucket.end_time_utc.isoformat(),
            }
            for bucket in result.session_buckets
        ],
    }


def validate_published_profiles(
    *,
    command: SpreadCalibrationPublicationCommand,
    loaded_config_path: Path,
    mappings: tuple[SymbolMapping, ...],
) -> None:
    """Validate generated YAML resolves dynamic spread profiles for all symbols."""

    loaded_config = load_execution_costs(loaded_config_path)
    for mapping in mappings:
        profile = loaded_config.resolve_profile(metadata_from_mapping(mapping))
        if not isinstance(profile.spread_model, LogLinearDynamicHalfSpread):
            raise ApplicationError(
                "generated execution-cost YAML did not resolve a dynamic spread profile",
                symbol=mapping.mt5_symbol,
            )
        if profile.spread_model.provenance.timeframe != command.target_timeframe:
            raise ApplicationError(
                "generated dynamic spread provenance timeframe mismatch",
                symbol=mapping.mt5_symbol,
                target_timeframe=command.target_timeframe,
                provenance_timeframe=profile.spread_model.provenance.timeframe,
            )


def metadata_from_mapping(mapping: SymbolMapping) -> ExecutionInstrumentMetadata:
    """Return execution metadata required to validate generated profile resolution."""

    if mapping.asset_class is None:
        raise ApplicationError(
            "execution-cost publication requires asset_class metadata",
            symbol=mapping.mt5_symbol,
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


def source_fingerprint_for_mapping(
    source_fingerprints: dict[str, str],
    mapping: SymbolMapping,
) -> str:
    """Resolve the calibration source fingerprint for a mapped symbol family."""

    fingerprints_by_symbol = {
        canonical_symbol(symbol): fingerprint for symbol, fingerprint in source_fingerprints.items()
    }
    for symbol in mapping.all_symbols():
        fingerprint = fingerprints_by_symbol.get(canonical_symbol(symbol))
        if fingerprint is not None:
            return fingerprint
    raise ApplicationError(
        "spread calibration publication requires source_fingerprint for every symbol",
        symbol=mapping.mt5_symbol,
    )


__all__ = [
    "build_execution_costs_payload",
    "metadata_from_mapping",
    "runtime_profile_payload",
    "source_fingerprint_for_mapping",
    "validate_published_profiles",
]
