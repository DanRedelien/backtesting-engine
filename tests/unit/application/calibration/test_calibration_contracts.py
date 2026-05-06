from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from backtest_engine.application.calibration import (
    SpreadCalibrationPanelRow,
    SpreadCalibrationResult,
    SpreadCalibrationSymbolSummary,
)


def test_panel_row_rejects_non_finite_numeric_values() -> None:
    with pytest.raises(ValidationError, match="finite"):
        _panel_row(edge_full_spread_frac_signed=math.nan)


def test_panel_row_validates_edge_price_unit_conversion() -> None:
    with pytest.raises(ValidationError, match="half_spread_price"):
        _panel_row(half_spread_price=2.0)

    with pytest.raises(ValidationError, match="edge_full_spread_frac_nonnegative"):
        _panel_row(edge_full_spread_frac_signed=-0.001, edge_full_spread_frac_nonnegative=0.001)

    with pytest.raises(ValidationError, match="negative_edge_estimate"):
        _panel_row(
            edge_full_spread_frac_signed=-0.001,
            edge_full_spread_frac_nonnegative=0.0,
            half_spread_price=0.0,
            negative_edge_estimate=False,
        )


def test_panel_row_validates_window_timestamps() -> None:
    fill_timestamp = datetime(2026, 1, 1, 0, 3, tzinfo=timezone.utc)

    with pytest.raises(ValidationError, match="edge_window_start_utc"):
        _panel_row(
            edge_window_start_utc=fill_timestamp - timedelta(microseconds=1),
            edge_window_end_utc=fill_timestamp - timedelta(minutes=1),
        )

    with pytest.raises(ValidationError, match="feature_observed_at_utc"):
        _panel_row(feature_observed_at_utc=fill_timestamp)


def test_symbol_summary_enforces_count_consistency() -> None:
    with pytest.raises(ValidationError, match="invalid_window_count"):
        SpreadCalibrationSymbolSummary(
            symbol="EURUSD",
            estimator_timeframe="1m",
            source_fingerprint="f" * 64,
            input_bar_count=3,
            eligible_window_count=2,
            usable_row_count=1,
            invalid_window_count=1,
            negative_estimate_count=0,
            invalid_reason_counts={"nt_lt_2": 2},
            positive_volume_row_count=3,
            zero_volume_row_count=0,
        )

    with pytest.raises(ValidationError, match="negative_estimate_count"):
        SpreadCalibrationSymbolSummary(
            symbol="EURUSD",
            estimator_timeframe="1m",
            source_fingerprint="f" * 64,
            input_bar_count=3,
            eligible_window_count=1,
            usable_row_count=1,
            invalid_window_count=0,
            negative_estimate_count=2,
            invalid_reason_counts={},
            positive_volume_row_count=3,
            zero_volume_row_count=0,
        )


def test_result_requires_at_least_one_panel_row() -> None:
    with pytest.raises(ValidationError, match="at least one panel row"):
        SpreadCalibrationResult(
            calibration_id="spread-calibration-123456789abc",
            dataset_id="dataset-123456789abc",
            estimator_timeframe="1m",
            edge_window_bars=3,
            price_basis="last_window_close",
            panel_rows=(),
            symbol_summaries=(),
            source_fingerprints={},
            requested_by="test",
        )


def _panel_row(**overrides: object) -> SpreadCalibrationPanelRow:
    fill_timestamp = datetime(2026, 1, 1, 0, 3, tzinfo=timezone.utc)
    payload = {
        "symbol": "EURUSD",
        "estimator_timeframe": "1m",
        "fill_timestamp_utc": fill_timestamp,
        "target_observed_at_utc": fill_timestamp - timedelta(microseconds=1),
        "feature_observed_at_utc": fill_timestamp - timedelta(microseconds=1),
        "edge_window_start_utc": datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
        "edge_window_end_utc": fill_timestamp - timedelta(microseconds=1),
        "edge_window_bars": 3,
        "session_bucket_id": "regular",
        "volatility_stress_signal": 0.0,
        "liquidity_stress_signal": 0.0,
        "liquidity_observed_volume": 1000.0,
        "edge_full_spread_frac_signed": 0.001,
        "edge_full_spread_frac_nonnegative": 0.001,
        "reference_price": 100.0,
        "half_spread_price": 0.05,
        "price_basis": "last_window_close",
        "conversion_method": "test",
        "source_fingerprint": "f" * 64,
        "validator_ruleset_version": "market_data_rules_v5",
        "negative_edge_estimate": False,
    }
    payload.update(overrides)
    return SpreadCalibrationPanelRow.model_validate(payload)
