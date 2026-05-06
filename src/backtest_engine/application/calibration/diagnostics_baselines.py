"""Baseline and regime-bucket helpers for spread calibration diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Any, Literal

import pandas as pd

from backtest_engine.application.calibration.diagnostics_metrics import log_error_summary
from backtest_engine.application.calibration.diagnostics_types import (
    BaselinePredictions,
    CalibrationDiagnosticRow,
    RowId,
)
from backtest_engine.core.errors import ApplicationError


ROW_WEIGHTED_MATCHED_BUDGET = "row_weighted_matched_budget"
TRAIN_STATIC_BASELINE = "train_static_baseline"
TRAIN_BUCKET_BASELINE = "train_bucket_baseline"
BASELINE_NAMES = (
    ROW_WEIGHTED_MATCHED_BUDGET,
    TRAIN_STATIC_BASELINE,
    TRAIN_BUCKET_BASELINE,
)

SignalName = Literal["volatility", "liquidity"]


@dataclass(frozen=True)
class SignalBucketModel:
    """Train-derived boundaries for applying low/mid/high signal buckets."""

    signal_name: SignalName
    labels: tuple[str, ...]
    interior_edges: tuple[float, ...]
    reason: str | None

    def label(self, value: float) -> str:
        """Apply train-derived bucket boundaries to one signal value."""

        if len(self.labels) == 1:
            return self.labels[0]
        if len(self.labels) == 2:
            return self.labels[0] if value <= self.interior_edges[0] else self.labels[1]
        first_edge, second_edge = self.interior_edges
        if value <= first_edge:
            return self.labels[0]
        if value <= second_edge:
            return self.labels[1]
        return self.labels[2]

    def labels_by_row_id(self, rows: tuple[CalibrationDiagnosticRow, ...]) -> dict[RowId, str]:
        """Return bucket labels keyed by row identity."""

        return {row.row_id: self.label(_row_signal(row, self.signal_name)) for row in rows}

    def to_report(self) -> dict[str, object]:
        """Return JSON-serializable bucket-boundary metadata."""

        return {
            "signal_name": self.signal_name,
            "labels": list(self.labels),
            "interior_edges": list(self.interior_edges),
            "reason": self.reason,
        }


def fit_signal_bucket_model(
    rows: tuple[CalibrationDiagnosticRow, ...],
    *,
    signal_name: SignalName,
    bucket_labels: tuple[str, ...],
) -> SignalBucketModel:
    """Fit deterministic signal bucket boundaries from train rows."""

    if bucket_labels != ("low", "mid", "high"):
        raise ApplicationError("calibration diagnostics require low/mid/high bucket labels")
    values = [_row_signal(row, signal_name) for row in rows]
    unique_values = sorted(set(values))
    if len(unique_values) < 2:
        return SignalBucketModel(
            signal_name=signal_name,
            labels=("all",),
            interior_edges=(),
            reason="fewer_than_two_unique_train_values",
        )

    _, bins = pd.qcut(
        pd.Series(values, dtype="float64"),
        q=min(3, len(unique_values)),
        retbins=True,
        duplicates="drop",
    )
    interval_count = len(bins) - 1
    if interval_count < 2:
        return SignalBucketModel(
            signal_name=signal_name,
            labels=("all",),
            interior_edges=(),
            reason="duplicate_train_values_dropped_to_one_bucket",
        )
    if interval_count == 2:
        return SignalBucketModel(
            signal_name=signal_name,
            labels=("low", "high"),
            interior_edges=(float(bins[1]),),
            reason="insufficient_unique_train_values_for_mid_bucket",
        )
    return SignalBucketModel(
        signal_name=signal_name,
        labels=("low", "mid", "high"),
        interior_edges=(float(bins[1]), float(bins[2])),
        reason=None,
    )


def baseline_predictions_for_symbol(
    *,
    train_rows: tuple[CalibrationDiagnosticRow, ...],
    holdout_rows: tuple[CalibrationDiagnosticRow, ...],
    volatility_bucket_model: SignalBucketModel,
    liquidity_bucket_model: SignalBucketModel,
) -> BaselinePredictions:
    """Fit deployable and matched-budget baselines for one symbol and score holdout rows."""

    if not train_rows or not holdout_rows:
        raise ApplicationError("baseline diagnostics require train and holdout rows")
    symbol = train_rows[0].symbol
    if any(row.symbol != symbol for row in (*train_rows, *holdout_rows)):
        raise ApplicationError("baseline diagnostics must be fit per symbol")

    matched_value = mean(row.effective_predicted for row in holdout_rows)
    train_static_value = mean(row.observed_effective for row in train_rows)
    train_bucket_predictions, fallback_counts = _train_bucket_predictions(
        train_rows=train_rows,
        holdout_rows=holdout_rows,
        volatility_bucket_model=volatility_bucket_model,
        liquidity_bucket_model=liquidity_bucket_model,
        symbol_train_mean=train_static_value,
    )
    return BaselinePredictions(
        predictions_by_name={
            ROW_WEIGHTED_MATCHED_BUDGET: {
                row.row_id: matched_value for row in holdout_rows
            },
            TRAIN_STATIC_BASELINE: {
                row.row_id: train_static_value for row in holdout_rows
            },
            TRAIN_BUCKET_BASELINE: train_bucket_predictions,
        },
        fallback_counts_by_name={
            ROW_WEIGHTED_MATCHED_BUDGET: {},
            TRAIN_STATIC_BASELINE: {},
            TRAIN_BUCKET_BASELINE: fallback_counts,
        },
    )


def merge_baseline_predictions(
    baselines: tuple[BaselinePredictions, ...],
) -> BaselinePredictions:
    """Merge per-symbol baseline predictions into one deterministic payload."""

    merged_predictions: dict[str, dict[RowId, float]] = {name: {} for name in BASELINE_NAMES}
    merged_fallback_counts = {
        name: {"exact": 0, "session": 0, "symbol": 0} for name in BASELINE_NAMES
    }
    for baseline in baselines:
        for name, predictions in baseline.predictions_by_name.items():
            merged_predictions[name].update(predictions)
        for name, fallback_counts in baseline.fallback_counts_by_name.items():
            for fallback_name, count in fallback_counts.items():
                merged_fallback_counts[name][fallback_name] = (
                    merged_fallback_counts[name].get(fallback_name, 0) + count
                )
    return BaselinePredictions(
        predictions_by_name=merged_predictions,
        fallback_counts_by_name=merged_fallback_counts,
    )


def baseline_comparison_table(
    holdout_rows: tuple[CalibrationDiagnosticRow, ...],
    baselines: BaselinePredictions,
) -> dict[str, Any]:
    """Compare dynamic effective predictions against each holdout baseline."""

    observed = [row.observed_effective for row in holdout_rows]
    comparison: dict[str, Any] = {
        "dynamic_effective_runtime": log_error_summary(
            observed,
            [row.effective_predicted for row in holdout_rows],
        )
    }
    for baseline_name in BASELINE_NAMES:
        predictions_by_row_id = baselines.predictions_by_name[baseline_name]
        comparison[baseline_name] = {
            **log_error_summary(
                observed,
                [predictions_by_row_id[row.row_id] for row in holdout_rows],
            ),
            "fallback_counts": baselines.fallback_counts_by_name.get(baseline_name, {}),
        }
    return comparison


def session_labels_by_row_id(rows: tuple[CalibrationDiagnosticRow, ...]) -> dict[RowId, str]:
    """Return session bucket labels keyed by row identity."""

    return {row.row_id: row.session_bucket_id for row in rows}


def _train_bucket_predictions(
    *,
    train_rows: tuple[CalibrationDiagnosticRow, ...],
    holdout_rows: tuple[CalibrationDiagnosticRow, ...],
    volatility_bucket_model: SignalBucketModel,
    liquidity_bucket_model: SignalBucketModel,
    symbol_train_mean: float,
) -> tuple[dict[RowId, float], dict[str, int]]:
    exact_values: dict[tuple[str, str, str], list[float]] = {}
    session_values: dict[str, list[float]] = {}
    for row in train_rows:
        volatility_bucket = volatility_bucket_model.label(row.volatility_signal)
        liquidity_bucket = liquidity_bucket_model.label(row.liquidity_signal)
        exact_key = (row.session_bucket_id, volatility_bucket, liquidity_bucket)
        exact_values.setdefault(exact_key, []).append(row.observed_effective)
        session_values.setdefault(row.session_bucket_id, []).append(row.observed_effective)

    exact_means = {key: mean(values) for key, values in exact_values.items()}
    session_means = {key: mean(values) for key, values in session_values.items()}
    predictions: dict[RowId, float] = {}
    fallback_counts = {"exact": 0, "session": 0, "symbol": 0}
    for row in holdout_rows:
        volatility_bucket = volatility_bucket_model.label(row.volatility_signal)
        liquidity_bucket = liquidity_bucket_model.label(row.liquidity_signal)
        exact_key = (row.session_bucket_id, volatility_bucket, liquidity_bucket)
        exact_prediction = exact_means.get(exact_key)
        if exact_prediction is not None:
            predictions[row.row_id] = exact_prediction
            fallback_counts["exact"] += 1
            continue
        session_prediction = session_means.get(row.session_bucket_id)
        if session_prediction is not None:
            predictions[row.row_id] = session_prediction
            fallback_counts["session"] += 1
            continue
        predictions[row.row_id] = symbol_train_mean
        fallback_counts["symbol"] += 1
    return predictions, fallback_counts


def _row_signal(row: CalibrationDiagnosticRow, signal_name: SignalName) -> float:
    if signal_name == "volatility":
        return row.volatility_signal
    return row.liquidity_signal


__all__ = [
    "BASELINE_NAMES",
    "ROW_WEIGHTED_MATCHED_BUDGET",
    "SignalBucketModel",
    "TRAIN_BUCKET_BASELINE",
    "TRAIN_STATIC_BASELINE",
    "baseline_comparison_table",
    "baseline_predictions_for_symbol",
    "fit_signal_bucket_model",
    "merge_baseline_predictions",
    "session_labels_by_row_id",
]
