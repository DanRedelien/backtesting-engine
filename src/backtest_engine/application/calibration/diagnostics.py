"""Deterministic diagnostics for offline spread calibration publication."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backtest_engine.application.calibration.contracts import (
    SpreadCalibrationPanelRow,
    SpreadCalibrationPublicationCommand,
)
from backtest_engine.application.calibration.diagnostics_baselines import (
    TRAIN_BUCKET_BASELINE,
    TRAIN_STATIC_BASELINE,
    baseline_comparison_table,
    baseline_predictions_for_symbol,
    fit_signal_bucket_model,
    merge_baseline_predictions,
    session_labels_by_row_id,
)
from backtest_engine.application.calibration.diagnostics_metrics import (
    conditional_summary_table,
    decile_table,
    prediction_metrics,
    row_weighted_aggregate_metrics,
    saturation_metrics,
    symbol_equal_weighted_aggregate_metrics,
)
from backtest_engine.application.calibration.diagnostics_plots import (
    write_diagnostic_artifacts,
)
from backtest_engine.application.calibration.diagnostics_types import (
    EFFECTIVE_RUNTIME_PREDICTION,
    PREDICTION_KINDS,
    RAW_MODEL_PREDICTION,
    CalibrationDiagnosticRow,
    ClippedPrediction,
    DiagnosticsArtifacts,
    SampleRole,
)
from backtest_engine.application.calibration.fitting import (
    CalibrationFitParameters,
    PreparedCalibrationRow,
    predict_log,
)
from backtest_engine.application.calibration.publication_helpers import (
    canonical_symbol,
)
from backtest_engine.application.calibration.publication_types import (
    PreparedPublication,
    SplitRows,
    SymbolBounds,
)
from backtest_engine.config.calibration import (
    SpreadCalibrationDiagnosticsSettings,
    load_calibration_diagnostics_settings,
)
from backtest_engine.core.errors import ApplicationError


@dataclass(frozen=True)
class CalibrationDiagnosticsPublication:
    """Diagnostics payload and artifacts ready for calibration report publication."""

    diagnostics: dict[str, Any]
    diagnostic_artifacts: dict[str, Any]
    artifact_paths: tuple[Path, ...]
    flags: list[dict[str, Any]]


def build_calibration_diagnostics(
    *,
    command: SpreadCalibrationPublicationCommand,
    split: SplitRows,
    prepared: PreparedPublication,
    fit: CalibrationFitParameters,
    bounds_by_symbol: dict[str, SymbolBounds],
    output_dir: Path,
    train_rows: tuple[PreparedCalibrationRow, ...],
    holdout_rows: tuple[PreparedCalibrationRow, ...],
    purged_rows: tuple[PreparedCalibrationRow, ...],
    settings: SpreadCalibrationDiagnosticsSettings | None = None,
) -> CalibrationDiagnosticsPublication:
    """Build report-only diagnostics and write deterministic PNG artifacts."""

    resolved_settings = settings or load_calibration_diagnostics_settings()
    diagnostic_rows = _diagnostic_rows(
        split=split,
        prepared=prepared,
        fit=fit,
        bounds_by_symbol=bounds_by_symbol,
        train_rows=train_rows,
        holdout_rows=holdout_rows,
        purged_rows=purged_rows,
    )
    rows_by_symbol = _rows_by_symbol(diagnostic_rows)
    holdout_rows_by_symbol = {
        symbol: tuple(row for row in rows if row.sample_role == "holdout")
        for symbol, rows in rows_by_symbol.items()
    }
    train_rows_by_symbol = {
        symbol: tuple(row for row in rows if row.sample_role == "train")
        for symbol, rows in rows_by_symbol.items()
    }

    symbol_payloads: dict[str, Any] = {}
    symbol_flags: dict[str, list[dict[str, Any]]] = {}
    per_symbol_baselines = []
    for symbol in sorted(rows_by_symbol):
        symbol_train_rows = train_rows_by_symbol[symbol]
        symbol_holdout_rows = holdout_rows_by_symbol[symbol]
        volatility_model = fit_signal_bucket_model(
            symbol_train_rows,
            signal_name="volatility",
            bucket_labels=resolved_settings.regime_bucket_labels,
        )
        liquidity_model = fit_signal_bucket_model(
            symbol_train_rows,
            signal_name="liquidity",
            bucket_labels=resolved_settings.regime_bucket_labels,
        )
        baselines = baseline_predictions_for_symbol(
            train_rows=symbol_train_rows,
            holdout_rows=symbol_holdout_rows,
            volatility_bucket_model=volatility_model,
            liquidity_bucket_model=liquidity_model,
        )
        per_symbol_baselines.append(baselines)
        holdout_metrics = {
            prediction_kind: prediction_metrics(
                symbol_holdout_rows,
                prediction_kind,
                minimum_regression_rows=resolved_settings.minimum_regression_rows,
            )
            for prediction_kind in PREDICTION_KINDS
        }
        saturation = saturation_metrics(symbol_holdout_rows)
        baseline_comparison = baseline_comparison_table(symbol_holdout_rows, baselines)
        flags = _symbol_flags(
            symbol=symbol,
            effective_metrics=holdout_metrics[EFFECTIVE_RUNTIME_PREDICTION],
            saturation=saturation,
            baseline_comparison=baseline_comparison,
            settings=resolved_settings,
        )
        symbol_flags[symbol] = flags
        symbol_payloads[symbol] = {
            "sample_counts": {
                "train": len(symbol_train_rows),
                "holdout": len(symbol_holdout_rows),
                "purged": len(tuple(row for row in rows_by_symbol[symbol] if row.sample_role == "purged")),
            },
            "row_diagnostics": [
                row.to_report()
                for row in sorted(
                    rows_by_symbol[symbol],
                    key=lambda row: (row.sample_role, row.timestamp),
                )
            ],
            "holdout": holdout_metrics,
            "saturation": saturation,
            "deciles": _deciles(symbol_holdout_rows, saturation, resolved_settings),
            "regime_bucket_policy": {
                "volatility": volatility_model.to_report(),
                "liquidity": liquidity_model.to_report(),
            },
            "regimes": {
                "session": {
                    "rows": conditional_summary_table(
                        symbol_holdout_rows,
                        session_labels_by_row_id(symbol_holdout_rows),
                        baseline_predictions_by_name=baselines.predictions_by_name,
                    )
                },
                "volatility": {
                    "rows": conditional_summary_table(
                        symbol_holdout_rows,
                        volatility_model.labels_by_row_id(symbol_holdout_rows),
                        baseline_predictions_by_name=baselines.predictions_by_name,
                    )
                },
                "liquidity": {
                    "rows": conditional_summary_table(
                        symbol_holdout_rows,
                        liquidity_model.labels_by_row_id(symbol_holdout_rows),
                        baseline_predictions_by_name=baselines.predictions_by_name,
                    )
                },
            },
            "baseline_comparison": baseline_comparison,
            "flags": flags,
        }

    all_holdout_rows = tuple(
        row for rows in holdout_rows_by_symbol.values() for row in rows
    )
    merged_baselines = merge_baseline_predictions(tuple(per_symbol_baselines))
    diagnostics = {
        "threshold_policy": _threshold_policy(resolved_settings),
        "symbols": symbol_payloads,
        "aggregate": {
            "row_weighted": {
                prediction_kind: row_weighted_aggregate_metrics(
                    all_holdout_rows,
                    prediction_kind,
                    minimum_regression_rows=resolved_settings.minimum_regression_rows,
                )
                for prediction_kind in PREDICTION_KINDS
            },
            "symbol_equal_weighted": {
                prediction_kind: symbol_equal_weighted_aggregate_metrics(
                    prediction_kind,
                    all_holdout_rows,
                )
                for prediction_kind in PREDICTION_KINDS
            },
            "baseline_comparison": baseline_comparison_table(
                all_holdout_rows,
                merged_baselines,
            ),
        },
    }
    artifacts = write_diagnostic_artifacts(
        output_dir=output_dir,
        diagnostics=diagnostics,
        holdout_rows_by_symbol=holdout_rows_by_symbol,
        settings=resolved_settings,
    )
    flags = [
        flag
        for symbol in sorted(symbol_flags)
        for flag in symbol_flags[symbol]
        if flag["severity"] in {"warning", "review_flag"}
    ]
    return CalibrationDiagnosticsPublication(
        diagnostics=diagnostics,
        diagnostic_artifacts=_artifact_payload(
            artifacts,
            report_dir=output_dir,
        ),
        artifact_paths=artifacts.all_paths,
        flags=flags,
    )


def clip_prediction(raw_prediction: float, bounds: SymbolBounds) -> ClippedPrediction:
    """Clip one raw model prediction to runtime publication bounds."""

    if not math.isfinite(raw_prediction) or raw_prediction <= 0.0:
        raise ApplicationError(
            "spread calibration diagnostics require finite positive predictions",
        )
    if (
        not math.isfinite(bounds.min_half_spread_price)
        or not math.isfinite(bounds.max_half_spread_price)
        or bounds.min_half_spread_price <= 0.0
        or bounds.max_half_spread_price <= 0.0
    ):
        raise ApplicationError("spread calibration diagnostics require finite positive bounds")
    if bounds.min_half_spread_price > bounds.max_half_spread_price:
        raise ApplicationError(
            "spread calibration diagnostics received invalid prediction bounds",
            min_half_spread_price=bounds.min_half_spread_price,
            max_half_spread_price=bounds.max_half_spread_price,
        )
    if raw_prediction < bounds.min_half_spread_price:
        return ClippedPrediction(
            raw_price=raw_prediction,
            effective_price=bounds.min_half_spread_price,
            clip_status="min",
        )
    if raw_prediction > bounds.max_half_spread_price:
        return ClippedPrediction(
            raw_price=raw_prediction,
            effective_price=bounds.max_half_spread_price,
            clip_status="max",
        )
    return ClippedPrediction(
        raw_price=raw_prediction,
        effective_price=raw_prediction,
        clip_status="none",
    )


def _diagnostic_rows(
    *,
    split: SplitRows,
    prepared: PreparedPublication,
    fit: CalibrationFitParameters,
    bounds_by_symbol: dict[str, SymbolBounds],
    train_rows: tuple[PreparedCalibrationRow, ...],
    holdout_rows: tuple[PreparedCalibrationRow, ...],
    purged_rows: tuple[PreparedCalibrationRow, ...],
) -> tuple[CalibrationDiagnosticRow, ...]:
    rows: list[CalibrationDiagnosticRow] = []
    rows.extend(
        _diagnostic_rows_for_role(
            panel_rows=split.train,
            prepared_rows=train_rows,
            sample_role="train",
            fit=fit,
            bounds_by_symbol=bounds_by_symbol,
            prepared=prepared,
        )
    )
    rows.extend(
        _diagnostic_rows_for_role(
            panel_rows=split.holdout,
            prepared_rows=holdout_rows,
            sample_role="holdout",
            fit=fit,
            bounds_by_symbol=bounds_by_symbol,
            prepared=prepared,
        )
    )
    rows.extend(
        _diagnostic_rows_for_role(
            panel_rows=split.purged,
            prepared_rows=purged_rows,
            sample_role="purged",
            fit=fit,
            bounds_by_symbol=bounds_by_symbol,
            prepared=prepared,
        )
    )
    return tuple(sorted(rows, key=lambda row: (row.symbol, row.timestamp, row.sample_role)))


def _diagnostic_rows_for_role(
    *,
    panel_rows: tuple[SpreadCalibrationPanelRow, ...],
    prepared_rows: tuple[PreparedCalibrationRow, ...],
    sample_role: SampleRole,
    fit: CalibrationFitParameters,
    bounds_by_symbol: dict[str, SymbolBounds],
    prepared: PreparedPublication,
) -> tuple[CalibrationDiagnosticRow, ...]:
    if len(panel_rows) != len(prepared_rows):
        raise ApplicationError("spread calibration diagnostic row inputs must align")
    rows: list[CalibrationDiagnosticRow] = []
    for panel_row, prepared_row in zip(panel_rows, prepared_rows):
        canonical_input_symbol = canonical_symbol(panel_row.symbol)
        canonical_output_symbol = prepared.canonical_symbol_by_input_symbol[
            canonical_input_symbol
        ]
        if canonical_output_symbol != prepared_row.symbol:
            raise ApplicationError(
                "spread calibration diagnostic row symbol mapping drifted",
                input_symbol=panel_row.symbol,
                prepared_symbol=prepared_row.symbol,
            )
        raw_prediction = math.exp(predict_log(prepared_row, fit))
        clipped = clip_prediction(raw_prediction, bounds_by_symbol[prepared_row.symbol])
        observed_raw = float(panel_row.half_spread_price)
        observed_effective = prepared_row.target_half_spread_price
        if observed_raw < 0.0 or not math.isfinite(observed_raw):
            raise ApplicationError(
                "spread calibration diagnostics require finite non-negative raw targets",
                symbol=panel_row.symbol,
            )
        rows.append(
            CalibrationDiagnosticRow(
                symbol=prepared_row.symbol,
                sample_role=sample_role,
                timestamp=prepared_row.fill_timestamp_utc,
                observed_raw=observed_raw,
                observed_effective=observed_effective,
                raw_predicted=clipped.raw_price,
                effective_predicted=clipped.effective_price,
                clip_status=clipped.clip_status,
                session_bucket_id=prepared_row.session_bucket_id,
                volatility_signal=prepared_row.volatility_signal,
                liquidity_signal=prepared_row.liquidity_signal,
                target_floored=observed_effective > observed_raw,
            )
        )
    return tuple(rows)


def _rows_by_symbol(
    rows: tuple[CalibrationDiagnosticRow, ...],
) -> dict[str, tuple[CalibrationDiagnosticRow, ...]]:
    grouped: dict[str, list[CalibrationDiagnosticRow]] = {}
    for row in rows:
        grouped.setdefault(row.symbol, []).append(row)
    return {symbol: tuple(symbol_rows) for symbol, symbol_rows in grouped.items()}


def _deciles(
    rows: tuple[CalibrationDiagnosticRow, ...],
    saturation: dict[str, float],
    settings: SpreadCalibrationDiagnosticsSettings,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        EFFECTIVE_RUNTIME_PREDICTION: decile_table(
            rows,
            EFFECTIVE_RUNTIME_PREDICTION,
            decile_count=settings.decile_count,
        )
    }
    if saturation["min_clip_rate"] > 0.0 or saturation["max_clip_rate"] > 0.0:
        payload[RAW_MODEL_PREDICTION] = decile_table(
            rows,
            RAW_MODEL_PREDICTION,
            decile_count=settings.decile_count,
        )
    return payload


def _symbol_flags(
    *,
    symbol: str,
    effective_metrics: dict[str, Any],
    saturation: dict[str, float],
    baseline_comparison: dict[str, Any],
    settings: SpreadCalibrationDiagnosticsSettings,
) -> list[dict[str, Any]]:
    thresholds = settings.thresholds
    flags = [
        _flag(
            symbol=symbol,
            code="mean_log_error_bias",
            metric="mean_log_error",
            value=abs(float(effective_metrics["mean_log_error"])),
            warning=thresholds.absolute_mean_log_error_warning,
            review=thresholds.absolute_mean_log_error_review,
            interpretation="absolute multiplicative log-bias",
        ),
        _flag(
            symbol=symbol,
            code="mae_log",
            metric="mae_log",
            value=float(effective_metrics["mae_log"]),
            warning=thresholds.mae_log_warning,
            review=thresholds.mae_log_review,
            interpretation="mean absolute log error",
        ),
        _flag(
            symbol=symbol,
            code="rmse_log",
            metric="rmse_log",
            value=float(effective_metrics["rmse_log"]),
            warning=thresholds.rmse_log_warning,
            review=thresholds.rmse_log_review,
            interpretation="root mean squared log error",
        ),
        _flag(
            symbol=symbol,
            code="severe_underpricing_rate_1_5x",
            metric="severe_underpricing_rate_1_5x",
            value=float(effective_metrics["severe_underpricing_rate_1_5x"]),
            warning=thresholds.severe_underpricing_rate_1_5x_warning,
            review=thresholds.severe_underpricing_rate_1_5x_review,
            interpretation="observed divided by predicted is at least 1.5",
        ),
        _flag(
            symbol=symbol,
            code="severe_underpricing_rate_2_0x",
            metric="severe_underpricing_rate_2_0x",
            value=float(effective_metrics["severe_underpricing_rate_2_0x"]),
            warning=thresholds.severe_underpricing_rate_2_0x_warning,
            review=thresholds.severe_underpricing_rate_2_0x_review,
            interpretation="observed divided by predicted is at least 2.0",
        ),
        _flag(
            symbol=symbol,
            code="min_clip_rate",
            metric="min_clip_rate",
            value=saturation["min_clip_rate"],
            warning=thresholds.min_clip_rate_warning,
            review=thresholds.min_clip_rate_review,
            interpretation="runtime prediction clipped to symbol minimum bound",
        ),
        _flag(
            symbol=symbol,
            code="max_clip_rate",
            metric="max_clip_rate",
            value=saturation["max_clip_rate"],
            warning=thresholds.max_clip_rate_warning,
            review=thresholds.max_clip_rate_review,
            interpretation="runtime prediction clipped to symbol maximum bound",
        ),
        _flag(
            symbol=symbol,
            code="target_floor_rate",
            metric="target_floor_rate",
            value=saturation["target_floor_rate"],
            warning=thresholds.target_floor_rate_warning,
            review=thresholds.target_floor_rate_review,
            interpretation="observed target was floored to symbol minimum half-spread",
        ),
    ]
    dynamic_mae = float(baseline_comparison["dynamic_effective_runtime"]["mae_log"])
    for baseline_name in (TRAIN_STATIC_BASELINE, TRAIN_BUCKET_BASELINE):
        degradation = dynamic_mae - float(baseline_comparison[baseline_name]["mae_log"])
        flags.append(
            _flag(
                symbol=symbol,
                code=f"dynamic_worse_than_{baseline_name}",
                metric="mae_log_degradation",
                value=degradation,
                warning=settings.thresholds.baseline_mae_degradation_warning,
                review=settings.thresholds.baseline_mae_degradation_review,
                interpretation=(
                    "dynamic effective runtime log-MAE minus deployable baseline log-MAE"
                ),
            )
        )
    return [flag for flag in flags if flag["severity"] != "unhighlighted"]


def _flag(
    *,
    symbol: str,
    code: str,
    metric: str,
    value: float,
    warning: float,
    review: float,
    interpretation: str,
) -> dict[str, Any]:
    severity = "unhighlighted"
    if value >= review:
        severity = "review_flag"
    elif value >= warning:
        severity = "warning"
    return {
        "symbol": symbol,
        "code": code,
        "metric": metric,
        "value": value,
        "severity": severity,
        "warning_threshold": warning,
        "review_threshold": review,
        "interpretation": interpretation,
        "publication_blocking": False,
    }


def _threshold_policy(settings: SpreadCalibrationDiagnosticsSettings) -> dict[str, Any]:
    return {
        "schema_version": settings.schema_version,
        "policy_name": settings.policy_name,
        "policy_description": settings.policy_description,
        "threshold_interpretation": settings.threshold_interpretation,
        "threshold_status_levels": list(settings.threshold_status_levels),
        "thresholds": settings.thresholds.model_dump(mode="json"),
        "palette": settings.palette.model_dump(mode="json"),
        "decile_count": settings.decile_count,
        "regime_bucket_labels": list(settings.regime_bucket_labels),
        "minimum_regression_rows": settings.minimum_regression_rows,
    }


def _artifact_payload(
    artifacts: DiagnosticsArtifacts,
    *,
    report_dir: Path,
) -> dict[str, Any]:
    symbol_paths = {
        symbol: path.relative_to(report_dir).as_posix()
        for symbol, path in sorted(artifacts.symbol_png_paths_by_symbol.items())
    }
    return {
        "summary_png": artifacts.summary_png_path.relative_to(report_dir).as_posix(),
        "symbol_pngs": symbol_paths,
        "path_base": "relative_to_calibration_report_directory",
    }


__all__ = [
    "CalibrationDiagnosticsPublication",
    "build_calibration_diagnostics",
    "clip_prediction",
]
