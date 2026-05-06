from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Literal

import pytest

from backtest_engine.application.calibration.diagnostics import clip_prediction
from backtest_engine.application.calibration.diagnostics_baselines import (
    ROW_WEIGHTED_MATCHED_BUDGET,
    TRAIN_BUCKET_BASELINE,
    TRAIN_STATIC_BASELINE,
    baseline_predictions_for_symbol,
    fit_signal_bucket_model,
)
from backtest_engine.application.calibration.diagnostics_plots import diagnostic_symbol_png_name
from backtest_engine.application.calibration.diagnostics_metrics import (
    decile_table,
    prediction_metrics,
    regression_metrics,
    saturation_metrics,
    symbol_equal_weighted_aggregate_metrics,
)
from backtest_engine.application.calibration.diagnostics_types import CalibrationDiagnosticRow
from backtest_engine.application.calibration.publication_types import SymbolBounds
from backtest_engine.core.errors import ApplicationError


def test_prediction_metrics_report_perfect_calibration() -> None:
    rows = tuple(_row(index, observed=target, predicted=target) for index, target in enumerate((1.0, 2.0, 4.0)))

    metrics = prediction_metrics(
        rows,
        "effective_runtime_prediction",
        minimum_regression_rows=2,
    )

    assert metrics["mean_log_error"] == pytest.approx(0.0)
    assert metrics["mae_log"] == pytest.approx(0.0)
    assert metrics["rmse_log"] == pytest.approx(0.0)
    assert metrics["geometric_mean_ratio"] == pytest.approx(1.0)
    assert metrics["r2_log"]["value"] == pytest.approx(1.0)
    assert metrics["rank_corr"]["value"] == pytest.approx(1.0)


def test_prediction_metrics_report_systematic_underprediction() -> None:
    rows = tuple(
        _row(index, observed=observed, predicted=observed / 2.0)
        for index, observed in enumerate((1.0, 2.0, 4.0))
    )

    metrics = prediction_metrics(
        rows,
        "effective_runtime_prediction",
        minimum_regression_rows=2,
    )

    assert metrics["mean_log_error"] == pytest.approx(math.log(0.5))
    assert metrics["geometric_mean_ratio"] == pytest.approx(2.0)
    assert metrics["severe_underpricing_rate_1_5x"] == pytest.approx(1.0)
    assert metrics["severe_underpricing_rate_2_0x"] == pytest.approx(1.0)


def test_prediction_metrics_return_reasons_for_tied_predictions_and_constant_target() -> None:
    tied_prediction_rows = tuple(
        _row(index, observed=observed, predicted=1.0)
        for index, observed in enumerate((1.0, 2.0, 4.0))
    )
    tied_metrics = prediction_metrics(
        tied_prediction_rows,
        "effective_runtime_prediction",
        minimum_regression_rows=2,
    )

    assert tied_metrics["rank_corr"] == {"value": None, "reason": "constant_ranks"}
    assert tied_metrics["r2_log"] == {"value": None, "reason": "constant_prediction"}

    constant_target = (1.0, 1.0, 1.0)
    changing_prediction = (0.8, 1.0, 1.2)
    constant_target_metrics = regression_metrics(
        constant_target,
        changing_prediction,
        minimum_regression_rows=2,
    )

    assert constant_target_metrics["r2_log"] == {
        "value": None,
        "reason": "constant_target",
    }


def test_prediction_metrics_return_reasons_for_tiny_sample() -> None:
    metrics = prediction_metrics(
        (_row(0, observed=1.0, predicted=1.0),),
        "effective_runtime_prediction",
        minimum_regression_rows=2,
    )

    assert metrics["r2_log"] == {"value": None, "reason": "insufficient_sample"}
    assert metrics["rank_corr"] == {"value": None, "reason": "insufficient_sample"}


def test_deciles_handle_all_tied_and_duplicate_predictions() -> None:
    tied_rows = tuple(_row(index, observed=1.0 + index, predicted=1.0) for index in range(4))

    tied_table = decile_table(
        tied_rows,
        "effective_runtime_prediction",
        decile_count=10,
    )

    assert tied_table["bucket_count"] == 1
    assert tied_table["reason"] == "fewer_than_two_unique_predictions"
    assert tied_table["rows"][0]["bucket"] == "all"

    duplicate_rows = tuple(
        _row(index, observed=1.0 + index, predicted=prediction)
        for index, prediction in enumerate((1.0, 1.0, 2.0, 2.0, 3.0, 3.0))
    )
    duplicate_table = decile_table(
        duplicate_rows,
        "effective_runtime_prediction",
        decile_count=10,
    )

    assert duplicate_table["bucket_count"] < 10
    assert duplicate_table["reason"] == "duplicate_predictions_dropped"


def test_clip_and_saturation_metrics_separate_min_max_and_target_floor() -> None:
    bounds = SymbolBounds(
        base_half_spread_price=1.0,
        min_half_spread_price=0.5,
        max_half_spread_price=2.0,
    )

    assert clip_prediction(0.25, bounds).clip_status == "min"
    assert clip_prediction(3.0, bounds).clip_status == "max"
    assert clip_prediction(1.25, bounds).clip_status == "none"

    rows = (
        _row(0, observed=0.5, predicted=0.5, raw_predicted=0.25, clip_status="min", target_floored=True),
        _row(1, observed=2.0, predicted=2.0, raw_predicted=3.0, clip_status="max"),
    )

    saturation = saturation_metrics(rows)

    assert saturation["min_clip_rate"] == pytest.approx(0.5)
    assert saturation["max_clip_rate"] == pytest.approx(0.5)
    assert saturation["target_floor_rate"] == pytest.approx(0.5)


def test_clip_prediction_rejects_invalid_bounds_and_metrics_reject_non_positive_inputs() -> None:
    with pytest.raises(ApplicationError, match="invalid prediction bounds"):
        clip_prediction(
            1.0,
            SymbolBounds(
                base_half_spread_price=1.0,
                min_half_spread_price=2.0,
                max_half_spread_price=1.0,
            ),
        )

    with pytest.raises(ApplicationError, match="finite positive"):
        prediction_metrics(
            (_row(0, observed=1.0, predicted=0.0),),
            "effective_runtime_prediction",
            minimum_regression_rows=2,
        )


def test_rank_corr_uses_average_ranks_for_ties() -> None:
    metrics = regression_metrics(
        (1.0, 2.0, 2.0, 4.0),
        (1.0, 2.0, 3.0, 4.0),
        minimum_regression_rows=2,
    )

    assert metrics["rank_corr"]["value"] == pytest.approx(0.94868329805)


def test_baselines_use_holdout_matched_budget_train_static_and_train_buckets() -> None:
    train_rows = (
        _row(0, sample_role="train", observed=1.0, predicted=1.0, session_bucket_id="regular", volatility_signal=0.1, liquidity_signal=0.1),
        _row(1, sample_role="train", observed=3.0, predicted=3.0, session_bucket_id="regular", volatility_signal=0.9, liquidity_signal=0.9),
        _row(2, sample_role="train", observed=5.0, predicted=5.0, session_bucket_id="overnight", volatility_signal=0.5, liquidity_signal=0.5),
    )
    holdout_rows = (
        _row(3, observed=2.0, predicted=4.0, session_bucket_id="regular", volatility_signal=0.1, liquidity_signal=0.1),
        _row(4, observed=4.0, predicted=6.0, session_bucket_id="regular", volatility_signal=0.9, liquidity_signal=0.9),
        _row(5, observed=6.0, predicted=8.0, session_bucket_id="missing", volatility_signal=0.9, liquidity_signal=0.9),
    )
    volatility_model = fit_signal_bucket_model(
        train_rows,
        signal_name="volatility",
        bucket_labels=("low", "mid", "high"),
    )
    liquidity_model = fit_signal_bucket_model(
        train_rows,
        signal_name="liquidity",
        bucket_labels=("low", "mid", "high"),
    )

    baselines = baseline_predictions_for_symbol(
        train_rows=train_rows,
        holdout_rows=holdout_rows,
        volatility_bucket_model=volatility_model,
        liquidity_bucket_model=liquidity_model,
    )

    matched = baselines.predictions_by_name[ROW_WEIGHTED_MATCHED_BUDGET]
    train_static = baselines.predictions_by_name[TRAIN_STATIC_BASELINE]
    train_bucket = baselines.predictions_by_name[TRAIN_BUCKET_BASELINE]
    assert {matched[row.row_id] for row in holdout_rows} == {6.0}
    assert {train_static[row.row_id] for row in holdout_rows} == {3.0}
    assert train_bucket[holdout_rows[0].row_id] == pytest.approx(1.0)
    assert train_bucket[holdout_rows[1].row_id] == pytest.approx(3.0)
    assert train_bucket[holdout_rows[2].row_id] == pytest.approx(3.0)
    assert baselines.fallback_counts_by_name[TRAIN_BUCKET_BASELINE] == {
        "exact": 2,
        "session": 0,
        "symbol": 1,
    }


def test_symbol_equal_weighted_aggregate_uses_row_level_weighted_quantiles() -> None:
    many_zero_error_rows = tuple(
        _row(index, symbol="A", observed=1.0, predicted=1.0)
        for index in range(20)
    )
    one_large_error_row = (
        _row(20, symbol="B", observed=1.0, predicted=10.0),
    )

    metrics = symbol_equal_weighted_aggregate_metrics(
        "effective_runtime_prediction",
        (*many_zero_error_rows, *one_large_error_row),
    )

    assert metrics["mean_log_error"] == pytest.approx(math.log(10.0) / 2.0)
    assert metrics["p95_log_error"] == pytest.approx(math.log(10.0))
    assert metrics["symbol_count"] == 2
    assert metrics["row_count"] == 21


def test_diagnostic_symbol_png_names_survive_sanitization_collisions() -> None:
    slash_symbol_path = diagnostic_symbol_png_name("A/B")
    underscore_symbol_path = diagnostic_symbol_png_name("A_B")

    assert slash_symbol_path != underscore_symbol_path
    assert slash_symbol_path.startswith("calibration_diagnostics_A_B_")
    assert underscore_symbol_path.startswith("calibration_diagnostics_A_B_")


def _row(
    index: int,
    *,
    symbol: str = "ES",
    sample_role: Literal["train", "holdout", "purged"] = "holdout",
    observed: float,
    predicted: float,
    raw_predicted: float | None = None,
    clip_status: Literal["none", "min", "max"] = "none",
    session_bucket_id: str = "regular",
    volatility_signal: float = 0.0,
    liquidity_signal: float = 0.0,
    target_floored: bool = False,
) -> CalibrationDiagnosticRow:
    return CalibrationDiagnosticRow(
        symbol=symbol,
        sample_role=sample_role,
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=index),
        observed_raw=observed,
        observed_effective=observed,
        raw_predicted=raw_predicted if raw_predicted is not None else predicted,
        effective_predicted=predicted,
        clip_status=clip_status,
        session_bucket_id=session_bucket_id,
        volatility_signal=volatility_signal,
        liquidity_signal=liquidity_signal,
        target_floored=target_floored,
    )
