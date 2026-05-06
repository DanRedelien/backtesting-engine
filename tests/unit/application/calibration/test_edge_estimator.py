from __future__ import annotations

import math

import pytest

from backtest_engine.application.calibration.edge import edge_spread, estimate_edge_spread


def test_edge_spread_matches_reference_fixture() -> None:
    open_values = [99.268728, 99.949389, 99.037372, 98.617758, 97.106084, 97.041004]
    high_values = [100.085996, 100.343551, 99.251673, 98.973541, 97.985839, 97.306494]
    low_values = [98.889634, 99.523119, 97.693192, 97.418306, 96.668414, 96.585325]
    close_values = [99.958515, 99.848422, 98.103148, 97.635734, 97.970854, 97.121379]

    signed = edge_spread(open_values, high_values, low_values, close_values, signed=True)
    absolute = edge_spread(open_values, high_values, low_values, close_values)

    assert signed == pytest.approx(0.004461295205774465)
    assert absolute == pytest.approx(abs(signed))


def test_edge_spread_can_return_signed_negative_estimates() -> None:
    open_values = [100.688844, 101.231128, 100.991363, 100.718396, 102.063282, 102.657494]
    high_values = [101.339329, 101.384652, 101.415051, 101.360478, 103.513611, 103.482068]
    low_values = [100.477109, 100.642686, 100.532806, 100.40699, 101.649815, 102.196132]
    close_values = [101.208306, 101.038656, 101.159781, 101.23368, 103.048776, 103.129374]

    signed = edge_spread(open_values, high_values, low_values, close_values, signed=True)
    absolute = edge_spread(open_values, high_values, low_values, close_values)

    assert signed == pytest.approx(-0.003754854246732123)
    assert absolute == pytest.approx(abs(signed))


def test_edge_estimate_reports_invalid_windows() -> None:
    short = estimate_edge_spread([100.0, 101.0], [101.0, 102.0], [99.0, 100.0], [100.5, 101.5])
    non_positive = estimate_edge_spread(
        [100.0, 0.0, 101.0],
        [101.0, 1.0, 102.0],
        [99.0, 0.5, 100.0],
        [100.5, 0.7, 101.5],
    )
    invalid_ohlc = estimate_edge_spread(
        [100.0, 101.0, 102.0],
        [101.0, 99.0, 103.0],
        [99.0, 100.0, 101.0],
        [100.5, 100.5, 102.5],
    )
    flat = estimate_edge_spread(
        [100.0, 100.0, 100.0],
        [100.0, 100.0, 100.0],
        [100.0, 100.0, 100.0],
        [100.0, 100.0, 100.0],
    )

    assert short.invalid_reason == "n_lt_3"
    assert non_positive.invalid_reason == "non_positive_price"
    assert invalid_ohlc.invalid_reason == "invalid_ohlc"
    assert flat.invalid_reason == "nt_lt_2"


def test_edge_spread_returns_nan_for_estimator_invalid_window() -> None:
    result = edge_spread(
        [100.0, 100.0, 100.0],
        [100.0, 100.0, 100.0],
        [100.0, 100.0, 100.0],
        [100.0, 100.0, 100.0],
    )

    assert math.isnan(result)


def test_edge_spread_rejects_length_mismatch() -> None:
    with pytest.raises(ValueError, match="same length"):
        edge_spread([100.0, 101.0, 102.0], [101.0, 102.0], [99.0, 100.0], [100.5])


def test_edge_spread_parity_with_optional_bidask_package() -> None:
    bidask = pytest.importorskip("bidask")
    open_values = [99.268728, 99.949389, 99.037372, 98.617758, 97.106084, 97.041004]
    high_values = [100.085996, 100.343551, 99.251673, 98.973541, 97.985839, 97.306494]
    low_values = [98.889634, 99.523119, 97.693192, 97.418306, 96.668414, 96.585325]
    close_values = [99.958515, 99.848422, 98.103148, 97.635734, 97.970854, 97.121379]

    expected = bidask.edge(open_values, high_values, low_values, close_values, sign=True)

    assert edge_spread(
        open_values, high_values, low_values, close_values, signed=True
    ) == pytest.approx(expected)
