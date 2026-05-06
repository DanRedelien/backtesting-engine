"""Calibration report builders for spread publication."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backtest_engine.application.calibration.contracts import (
    PublishedCalibrationSymbol,
    SpreadCalibrationPublicationCommand,
)
from backtest_engine.application.calibration.fitting import CalibrationFitParameters
from backtest_engine.application.calibration.publication_helpers import (
    canonical_symbol,
    decimal_string,
    isoformat_utc,
)
from backtest_engine.application.calibration.publication_types import (
    PreparedPublication,
    SplitRows,
    SymbolBounds,
)
from backtest_engine.domain.execution.instrument_metadata import ExecutionAssetClass


REPORT_SCHEMA_VERSION = "spread_calibration_report.v2"


def calibration_report(
    *,
    command: SpreadCalibrationPublicationCommand,
    split: SplitRows,
    liquidity_enabled: bool,
    liquidity_reason: str,
    fitted_fit: CalibrationFitParameters,
    published_fit: CalibrationFitParameters,
    dynamic_projection_reason: str,
    prepared: PreparedPublication,
    bounds_by_symbol: dict[str, SymbolBounds],
    train_metrics: dict[str, dict[str, float]],
    holdout_metrics: dict[str, dict[str, float]],
    published_symbols: tuple[PublishedCalibrationSymbol, ...],
    execution_costs_path: Path,
    panel_path: Path,
    profile_id: str,
    config_hash: str,
    diagnostics: dict[str, Any],
    diagnostic_artifacts: dict[str, Any],
    flags: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the JSON-serializable calibration report payload."""

    result = command.calibration_result
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "calibration_id": result.calibration_id,
        "dataset_id": result.dataset_id,
        "estimator_timeframe": result.estimator_timeframe,
        "target_timeframe": command.target_timeframe,
        "edge_window_bars": result.edge_window_bars,
        "price_basis": result.price_basis,
        "fit_method": "non_negative_coordinate_descent_log_linear_dynamic_half_spread",
        "fit_settings": {
            "fit_tolerance": command.fit_tolerance,
            "max_fit_iterations": command.max_fit_iterations,
        },
        "asset_class_panel": {
            "asset_classes": sorted(asset_class.value for asset_class in prepared.asset_classes),
            "allow_mixed_asset_classes": command.allow_mixed_asset_classes,
            "rationale": mixed_asset_class_rationale(command, prepared.asset_classes),
        },
        "source_references": {
            "edge_project": "https://github.com/eguidotti/bidask",
            "python_bidask_docs": "https://pypi.org/project/bidask/",
            "r_edge_docs": "https://www.rdocumentation.org/packages/bidask/versions/2.1.5/topics/edge",
        },
        "split": {
            "train_fraction": command.train_fraction,
            "split_timestamp_utc": isoformat_utc(split.split_timestamp_utc),
            "holdout_start_utc": isoformat_utc(split.holdout_start_utc),
            "purged_gap_seconds": split.purged_gap.total_seconds(),
            "train_row_count": len(split.train),
            "holdout_row_count": len(split.holdout),
            "purged_row_count": len(split.purged),
        },
        "runtime_feature_contract": {
            "volatility_short_window_bars": result.volatility_short_window_bars,
            "volatility_baseline_window_bars": result.volatility_baseline_window_bars,
            "volatility_floor_price": decimal_string(result.volatility_floor_price),
            "volume_baseline_window_bars": result.volume_baseline_window_bars,
            "volume_floor": decimal_string(result.volume_floor),
            "session_buckets": [
                bucket.model_dump(mode="json") for bucket in result.session_buckets
            ],
        },
        "liquidity_fit": {
            "enabled": liquidity_enabled,
            "reason": liquidity_reason,
            "coverage_threshold": command.liquidity_coverage_threshold,
            "volume_semantics": command.volume_semantics.value,
            "allowed_volume_semantics": [
                semantics.value
                for semantics in command.liquidity_eligibility_policy.allowed_volume_semantics
            ],
        },
        "fitted_shared_coefficients": {
            "volatility_weight": decimal_string(fitted_fit.volatility_weight),
            "liquidity_weight": decimal_string(fitted_fit.liquidity_weight),
            "session_adjustments_log": {
                session_id: decimal_string(value)
                for session_id, value in fitted_fit.session_adjustments_log.items()
            },
            "iterations": fitted_fit.iterations,
            "converged": fitted_fit.converged,
        },
        "published_shared_coefficients": {
            "projection_reason": dynamic_projection_reason,
            "volatility_weight": decimal_string(published_fit.volatility_weight),
            "liquidity_weight": decimal_string(published_fit.liquidity_weight),
            "session_adjustments_log": {
                session_id: decimal_string(value)
                for session_id, value in published_fit.session_adjustments_log.items()
            },
            "iterations": published_fit.iterations,
            "converged": published_fit.converged,
        },
        "symbols": {
            symbol.symbol: {
                "base_half_spread_price": decimal_string(symbol.base_half_spread_price),
                "min_half_spread_price": decimal_string(symbol.min_half_spread_price),
                "max_half_spread_price": decimal_string(symbol.max_half_spread_price),
                "train_metrics": train_metrics[symbol.symbol],
                "holdout_metrics": holdout_metrics[symbol.symbol],
            }
            for symbol in published_symbols
        },
        "diagnostics": diagnostics,
        "diagnostic_artifacts": diagnostic_artifacts,
        "flags": flags,
        "symbol_summaries": [
            summary.model_dump(mode="json")
            for summary in sorted(
                result.symbol_summaries,
                key=lambda summary: canonical_symbol(summary.symbol),
            )
        ],
        "generated_execution_costs": {
            "execution_costs_path": str(execution_costs_path),
            "calibration_panel_path": str(panel_path),
            "profile_id": profile_id,
            "config_content_hash": config_hash,
            "run_profile_snippet": {
                "execution_policy": {
                    "execution_costs": {
                        "profile_id": profile_id,
                        "config_content_hash": config_hash,
                    }
                }
            },
        },
    }


def mixed_asset_class_rationale(
    command: SpreadCalibrationPublicationCommand,
    asset_classes: set[ExecutionAssetClass],
) -> str:
    """Return the report rationale for mixed asset-class handling."""

    if len(asset_classes) <= 1:
        return "homogeneous_asset_class_panel"
    if command.allow_mixed_asset_classes:
        return "operator_explicitly_allowed_mixed_asset_class_panel"
    return "mixed_asset_class_panel_blocked_before_report_publication"


__all__ = ["REPORT_SCHEMA_VERSION", "calibration_report", "mixed_asset_class_rationale"]
