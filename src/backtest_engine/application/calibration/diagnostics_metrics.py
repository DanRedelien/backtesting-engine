"""Metric calculations for spread calibration diagnostics."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from statistics import mean, median
from typing import Any

import pandas as pd

from backtest_engine.application.calibration.diagnostics_types import (
    CalibrationDiagnosticRow,
    PredictionKind,
    RowId,
)
from backtest_engine.core.errors import ApplicationError


AGGREGATE_METRIC_KEYS = (
    "mean_log_error",
    "median_log_error",
    "p05_log_error",
    "p95_log_error",
    "mae_log",
    "rmse_log",
    "severe_underpricing_rate_1_5x",
    "severe_underpricing_rate_2_0x",
)


def prediction_metrics(
    rows: Iterable[CalibrationDiagnosticRow],
    prediction_kind: PredictionKind,
    *,
    minimum_regression_rows: int,
) -> dict[str, Any]:
    """Return primary log-scale and secondary ratio diagnostics for one sample."""

    row_tuple = tuple(rows)
    observed, predicted = _observed_and_predicted(row_tuple, prediction_kind)
    log_errors = [math.log(prediction / target) for target, prediction in zip(observed, predicted)]
    ratios = [target / prediction for target, prediction in zip(observed, predicted)]
    regression = regression_metrics(
        observed,
        predicted,
        minimum_regression_rows=minimum_regression_rows,
    )
    return {
        "row_count": len(row_tuple),
        "mean_log_error": mean(log_errors),
        "median_log_error": median(log_errors),
        "p05_log_error": _quantile(log_errors, 0.05),
        "p95_log_error": _quantile(log_errors, 0.95),
        "mae_log": _mae(log_errors),
        "rmse_log": _rmse(log_errors),
        "geometric_mean_ratio": math.exp(mean(math.log(ratio) for ratio in ratios)),
        "median_ratio": median(ratios),
        "mean_ratio_secondary": mean(ratios),
        "severe_underpricing_rate_1_5x": _rate(ratio >= 1.5 for ratio in ratios),
        "severe_underpricing_rate_2_0x": _rate(ratio >= 2.0 for ratio in ratios),
        **regression,
    }


def saturation_metrics(rows: Iterable[CalibrationDiagnosticRow]) -> dict[str, float]:
    """Return prediction clipping and target flooring rates for one sample."""

    row_tuple = tuple(rows)
    if not row_tuple:
        return {
            "min_clip_rate": 0.0,
            "max_clip_rate": 0.0,
            "target_floor_rate": 0.0,
        }
    min_count = 0
    max_count = 0
    target_floor_count = 0
    for row in row_tuple:
        if row.clip_status == "min":
            min_count += 1
        elif row.clip_status == "max":
            max_count += 1
        elif row.clip_status != "none":
            raise ApplicationError(
                "spread calibration diagnostics received an unknown clip status",
                clip_status=row.clip_status,
            )
        if row.target_floored:
            target_floor_count += 1
    row_count = len(row_tuple)
    return {
        "min_clip_rate": min_count / row_count,
        "max_clip_rate": max_count / row_count,
        "target_floor_rate": target_floor_count / row_count,
    }


def row_weighted_aggregate_metrics(
    rows: Iterable[CalibrationDiagnosticRow],
    prediction_kind: PredictionKind,
    *,
    minimum_regression_rows: int,
) -> dict[str, Any]:
    """Return aggregate log-scale metrics where each calibration row has equal weight."""

    row_tuple = tuple(rows)
    if not row_tuple:
        return {"row_count": 0, "symbol_count": 0}
    metrics = prediction_metrics(
        row_tuple,
        prediction_kind,
        minimum_regression_rows=minimum_regression_rows,
    )
    return {
        "row_count": len(row_tuple),
        "symbol_count": len({row.symbol for row in row_tuple}),
        **{key: metrics[key] for key in AGGREGATE_METRIC_KEYS},
    }


def symbol_equal_weighted_aggregate_metrics(
    prediction_kind: PredictionKind,
    rows: Iterable[CalibrationDiagnosticRow],
) -> dict[str, Any]:
    """Return aggregate log-scale metrics where each symbol has equal weight."""

    row_tuple = tuple(rows)
    if not row_tuple:
        return {"row_count": 0, "symbol_count": 0}
    rows_by_symbol: dict[str, list[CalibrationDiagnosticRow]] = {}
    for row in row_tuple:
        rows_by_symbol.setdefault(row.symbol, []).append(row)

    weighted_errors: list[tuple[float, float]] = []
    weighted_abs_errors: list[tuple[float, float]] = []
    weighted_squared_errors: list[tuple[float, float]] = []
    weighted_underpricing_1_5x: list[tuple[float, float]] = []
    weighted_underpricing_2_0x: list[tuple[float, float]] = []
    symbol_weight = 1.0 / len(rows_by_symbol)
    for symbol_rows in rows_by_symbol.values():
        row_weight = symbol_weight / len(symbol_rows)
        for row in symbol_rows:
            observed = row.observed_effective
            predicted = row.predicted(prediction_kind)
            _validate_observed_predicted((observed,), (predicted,))
            log_error = math.log(predicted / observed)
            ratio = observed / predicted
            weighted_errors.append((log_error, row_weight))
            weighted_abs_errors.append((abs(log_error), row_weight))
            weighted_squared_errors.append((log_error * log_error, row_weight))
            weighted_underpricing_1_5x.append((1.0 if ratio >= 1.5 else 0.0, row_weight))
            weighted_underpricing_2_0x.append((1.0 if ratio >= 2.0 else 0.0, row_weight))

    return {
        "row_count": len(row_tuple),
        "symbol_count": len(rows_by_symbol),
        "mean_log_error": _weighted_mean(weighted_errors),
        "median_log_error": _weighted_quantile(weighted_errors, 0.50),
        "p05_log_error": _weighted_quantile(weighted_errors, 0.05),
        "p95_log_error": _weighted_quantile(weighted_errors, 0.95),
        "mae_log": _weighted_mean(weighted_abs_errors),
        "rmse_log": math.sqrt(_weighted_mean(weighted_squared_errors)),
        "severe_underpricing_rate_1_5x": _weighted_mean(weighted_underpricing_1_5x),
        "severe_underpricing_rate_2_0x": _weighted_mean(weighted_underpricing_2_0x),
    }


def decile_table(
    rows: Iterable[CalibrationDiagnosticRow],
    prediction_kind: PredictionKind,
    *,
    decile_count: int,
) -> dict[str, Any]:
    """Return deterministic per-symbol decile diagnostics for one prediction view."""

    row_tuple = tuple(rows)
    if not row_tuple:
        return {"bucket_count": 0, "reason": "empty_sample", "rows": []}
    predictions = [row.predicted(prediction_kind) for row in row_tuple]
    _validate_positive_finite(predictions, field_name=prediction_kind)
    unique_prediction_count = len(set(predictions))
    if unique_prediction_count < 2:
        return {
            "bucket_count": 1,
            "reason": "fewer_than_two_unique_predictions",
            "rows": [_bucket_summary("all", row_tuple, prediction_kind)],
        }

    assignments = pd.qcut(
        pd.Series(predictions, dtype="float64"),
        q=min(decile_count, unique_prediction_count),
        labels=False,
        duplicates="drop",
    )
    bucket_ids = sorted(int(bucket_id) for bucket_id in assignments.dropna().unique())
    table_rows = []
    for bucket_id in bucket_ids:
        bucket_rows = tuple(
            row for row, assigned in zip(row_tuple, assignments) if int(assigned) == bucket_id
        )
        table_rows.append(_bucket_summary(f"d{bucket_id + 1:02d}", bucket_rows, prediction_kind))
    reason = None
    if len(bucket_ids) < decile_count:
        reason = "duplicate_predictions_dropped"
    return {
        "bucket_count": len(bucket_ids),
        "reason": reason,
        "rows": table_rows,
    }


def conditional_summary_table(
    rows: Iterable[CalibrationDiagnosticRow],
    group_labels_by_row_id: Mapping[RowId, str],
    *,
    baseline_predictions_by_name: Mapping[str, Mapping[RowId, float]],
) -> list[dict[str, Any]]:
    """Return grouped ratio/log-error summaries for deterministic regime diagnostics."""

    row_tuple = tuple(rows)
    grouped: dict[str, list[CalibrationDiagnosticRow]] = {}
    for row in row_tuple:
        label = group_labels_by_row_id[row.row_id]
        grouped.setdefault(label, []).append(row)

    table: list[dict[str, Any]] = []
    for label in sorted(grouped):
        group_rows = tuple(grouped[label])
        dynamic_summary = log_error_summary(
            [row.observed_effective for row in group_rows],
            [row.effective_predicted for row in group_rows],
        )
        payload: dict[str, Any] = {
            "bucket": label,
            "row_count": len(group_rows),
            "geometric_mean_ratio": dynamic_summary["geometric_mean_ratio"],
            "median_log_error": dynamic_summary["median_log_error"],
            "mean_log_error": dynamic_summary["mean_log_error"],
            "mae_log": dynamic_summary["mae_log"],
            "rmse_log": dynamic_summary["rmse_log"],
        }
        for baseline_name, predictions_by_row_id in baseline_predictions_by_name.items():
            baseline_predictions = [predictions_by_row_id[row.row_id] for row in group_rows]
            baseline_summary = log_error_summary(
                [row.observed_effective for row in group_rows],
                baseline_predictions,
            )
            payload[f"{baseline_name}_mae_log"] = baseline_summary["mae_log"]
            payload[f"{baseline_name}_rmse_log"] = baseline_summary["rmse_log"]
        table.append(payload)
    return table


def log_error_summary(
    observed: Iterable[float],
    predicted: Iterable[float],
) -> dict[str, float]:
    """Return compact log-error metrics for arbitrary prediction vectors."""

    observed_values = tuple(float(value) for value in observed)
    predicted_values = tuple(float(value) for value in predicted)
    _validate_observed_predicted(observed_values, predicted_values)
    log_errors = [
        math.log(prediction / target)
        for target, prediction in zip(observed_values, predicted_values)
    ]
    ratios = [
        target / prediction for target, prediction in zip(observed_values, predicted_values)
    ]
    return {
        "mean_log_error": mean(log_errors),
        "median_log_error": median(log_errors),
        "mae_log": _mae(log_errors),
        "rmse_log": _rmse(log_errors),
        "geometric_mean_ratio": math.exp(mean(math.log(ratio) for ratio in ratios)),
    }


def regression_metrics(
    observed: Iterable[float],
    predicted: Iterable[float],
    *,
    minimum_regression_rows: int,
) -> dict[str, dict[str, float | str | None]]:
    """Return OLS and Spearman diagnostics on log observed versus log predicted."""

    observed_values = tuple(float(value) for value in observed)
    predicted_values = tuple(float(value) for value in predicted)
    _validate_observed_predicted(observed_values, predicted_values)
    if len(observed_values) < minimum_regression_rows:
        reason = "insufficient_sample"
        return {
            "alpha_log": _metric(None, reason),
            "beta_log": _metric(None, reason),
            "r2_log": _metric(None, reason),
            "rank_corr": _metric(None, reason),
        }

    log_observed = [math.log(value) for value in observed_values]
    log_predicted = [math.log(value) for value in predicted_values]
    ols = _ols_log_regression(log_observed, log_predicted)
    rank_corr = _spearman_rank_corr(observed_values, predicted_values)
    return {
        "alpha_log": ols["alpha_log"],
        "beta_log": ols["beta_log"],
        "r2_log": ols["r2_log"],
        "rank_corr": rank_corr,
    }


def _observed_and_predicted(
    rows: tuple[CalibrationDiagnosticRow, ...],
    prediction_kind: PredictionKind,
) -> tuple[list[float], list[float]]:
    if not rows:
        raise ApplicationError("spread calibration diagnostics require at least one row")
    observed = [row.observed_effective for row in rows]
    predicted = [row.predicted(prediction_kind) for row in rows]
    _validate_observed_predicted(observed, predicted)
    return observed, predicted


def _bucket_summary(
    bucket: str,
    rows: tuple[CalibrationDiagnosticRow, ...],
    prediction_kind: PredictionKind,
) -> dict[str, float | int | str]:
    observed = [row.observed_effective for row in rows]
    predicted = [row.predicted(prediction_kind) for row in rows]
    summary = log_error_summary(observed, predicted)
    return {
        "bucket": bucket,
        "row_count": len(rows),
        "mean_predicted_half_spread": mean(predicted),
        "mean_observed_half_spread": mean(observed),
        "geometric_mean_ratio": summary["geometric_mean_ratio"],
        "median_log_error": summary["median_log_error"],
    }


def _ols_log_regression(
    log_observed: list[float],
    log_predicted: list[float],
) -> dict[str, dict[str, float | str | None]]:
    if len(set(log_predicted)) < 2:
        reason = "constant_prediction"
        return {
            "alpha_log": _metric(None, reason),
            "beta_log": _metric(None, reason),
            "r2_log": _metric(None, reason),
        }
    mean_x = mean(log_predicted)
    mean_y = mean(log_observed)
    centered_x = [value - mean_x for value in log_predicted]
    centered_y = [value - mean_y for value in log_observed]
    denominator = sum(value * value for value in centered_x)
    if denominator <= 0.0:
        reason = "constant_prediction"
        return {
            "alpha_log": _metric(None, reason),
            "beta_log": _metric(None, reason),
            "r2_log": _metric(None, reason),
        }
    beta = sum(x_value * y_value for x_value, y_value in zip(centered_x, centered_y)) / denominator
    alpha = mean_y - beta * mean_x
    if len(set(log_observed)) < 2:
        return {
            "alpha_log": _metric(alpha),
            "beta_log": _metric(beta),
            "r2_log": _metric(None, "constant_target"),
        }
    fitted = [alpha + beta * value for value in log_predicted]
    sse = sum((target - prediction) ** 2 for target, prediction in zip(log_observed, fitted))
    sst = sum((target - mean_y) ** 2 for target in log_observed)
    if sst <= 0.0:
        return {
            "alpha_log": _metric(alpha),
            "beta_log": _metric(beta),
            "r2_log": _metric(None, "constant_target"),
        }
    return {
        "alpha_log": _metric(alpha),
        "beta_log": _metric(beta),
        "r2_log": _metric(1.0 - sse / sst),
    }


def _spearman_rank_corr(
    observed: tuple[float, ...],
    predicted: tuple[float, ...],
) -> dict[str, float | str | None]:
    observed_ranks = pd.Series(observed, dtype="float64").rank(method="average")
    predicted_ranks = pd.Series(predicted, dtype="float64").rank(method="average")
    if observed_ranks.nunique() < 2 or predicted_ranks.nunique() < 2:
        return _metric(None, "constant_ranks")
    correlation = _pearson(
        [float(value) for value in observed_ranks.to_list()],
        [float(value) for value in predicted_ranks.to_list()],
    )
    if correlation is None:
        return _metric(None, "constant_ranks")
    return _metric(correlation)


def _pearson(left: list[float], right: list[float]) -> float | None:
    left_mean = mean(left)
    right_mean = mean(right)
    left_centered = [value - left_mean for value in left]
    right_centered = [value - right_mean for value in right]
    left_ss = sum(value * value for value in left_centered)
    right_ss = sum(value * value for value in right_centered)
    if left_ss <= 0.0 or right_ss <= 0.0:
        return None
    return sum(
        left_value * right_value for left_value, right_value in zip(left_centered, right_centered)
    ) / math.sqrt(left_ss * right_ss)


def _metric(value: float | None, reason: str | None = None) -> dict[str, float | str | None]:
    return {"value": value, "reason": reason}


def _quantile(values: list[float], quantile: float) -> float:
    return float(pd.Series(values, dtype="float64").quantile(quantile))


def _rmse(values: list[float]) -> float:
    return math.sqrt(sum(value * value for value in values) / len(values))


def _mae(values: list[float]) -> float:
    return sum(abs(value) for value in values) / len(values)


def _rate(flags: Iterable[bool]) -> float:
    values = tuple(flags)
    if not values:
        return 0.0
    return sum(1 for value in values if value) / len(values)


def _weighted_mean(values_and_weights: Iterable[tuple[float, float]]) -> float:
    pairs = tuple(values_and_weights)
    total_weight = sum(weight for _value, weight in pairs)
    if total_weight <= 0.0:
        raise ApplicationError("weighted calibration diagnostics require positive total weight")
    return sum(value * weight for value, weight in pairs) / total_weight


def _weighted_quantile(
    values_and_weights: Iterable[tuple[float, float]],
    quantile: float,
) -> float:
    pairs = tuple(sorted(values_and_weights, key=lambda pair: pair[0]))
    if not pairs:
        raise ApplicationError("weighted calibration diagnostics require at least one value")
    total_weight = sum(weight for _value, weight in pairs)
    if total_weight <= 0.0:
        raise ApplicationError("weighted calibration diagnostics require positive total weight")
    threshold = total_weight * quantile
    cumulative_weight = 0.0
    for value, weight in pairs:
        cumulative_weight += weight
        if cumulative_weight >= threshold:
            return value
    return pairs[-1][0]


def _validate_observed_predicted(
    observed: Iterable[float],
    predicted: Iterable[float],
) -> None:
    observed_values = tuple(float(value) for value in observed)
    predicted_values = tuple(float(value) for value in predicted)
    if len(observed_values) != len(predicted_values):
        raise ApplicationError("observed and predicted diagnostic vectors must align")
    _validate_positive_finite(observed_values, field_name="observed_effective")
    _validate_positive_finite(predicted_values, field_name="predicted_half_spread")


def _validate_positive_finite(values: Iterable[float], *, field_name: str) -> None:
    invalid = [value for value in values if value <= 0.0 or not math.isfinite(value)]
    if invalid:
        raise ApplicationError(
            "spread calibration diagnostics require finite positive numeric inputs",
            field_name=field_name,
        )


__all__ = [
    "AGGREGATE_METRIC_KEYS",
    "conditional_summary_table",
    "decile_table",
    "log_error_summary",
    "prediction_metrics",
    "regression_metrics",
    "row_weighted_aggregate_metrics",
    "saturation_metrics",
    "symbol_equal_weighted_aggregate_metrics",
]
