from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backtest_engine.interfaces.cli.market_data.progress_output import (
    CompletedSliceDurationSample,
    estimate_batch_remaining_sec,
    select_frontier_date_utc,
)


def test_select_frontier_date_utc_prefers_backward_fill_frontier() -> None:
    frontier = select_frontier_date_utc(
        requested_start_utc=datetime(2020, 6, 1, tzinfo=timezone.utc),
        requested_end_utc=datetime(2020, 6, 20, tzinfo=timezone.utc),
        actual_start_utc=datetime(2020, 6, 10, tzinfo=timezone.utc),
        actual_end_utc=datetime(2020, 6, 20, tzinfo=timezone.utc),
    )

    assert frontier == datetime(2020, 6, 10, tzinfo=timezone.utc)


def test_select_frontier_date_utc_prefers_larger_end_gap_and_tie_breaks_to_start() -> None:
    end_gap_frontier = select_frontier_date_utc(
        requested_start_utc=datetime(2020, 6, 1, tzinfo=timezone.utc),
        requested_end_utc=datetime(2020, 6, 20, tzinfo=timezone.utc),
        actual_start_utc=datetime(2020, 6, 1, tzinfo=timezone.utc),
        actual_end_utc=datetime(2020, 6, 15, tzinfo=timezone.utc),
    )
    tie_frontier = select_frontier_date_utc(
        requested_start_utc=datetime(2020, 6, 1, tzinfo=timezone.utc),
        requested_end_utc=datetime(2020, 6, 20, tzinfo=timezone.utc),
        actual_start_utc=datetime(2020, 6, 6, tzinfo=timezone.utc),
        actual_end_utc=datetime(2020, 6, 15, tzinfo=timezone.utc),
    )

    assert end_gap_frontier == datetime(2020, 6, 15, tzinfo=timezone.utc)
    assert tie_frontier == datetime(2020, 6, 6, tzinfo=timezone.utc)


def test_select_frontier_date_utc_returns_none_when_bounds_missing() -> None:
    frontier = select_frontier_date_utc(
        requested_start_utc=datetime(2020, 6, 1, tzinfo=timezone.utc),
        requested_end_utc=datetime(2020, 6, 20, tzinfo=timezone.utc),
        actual_start_utc=None,
        actual_end_utc=datetime(2020, 6, 20, tzinfo=timezone.utc),
    )

    assert frontier is None


def test_estimate_batch_remaining_sec_uses_median_completed_duration() -> None:
    left_sec = estimate_batch_remaining_sec(
        total_slices=5,
        completed_count=3,
        current_eta_sec=40.0,
        current_total_estimate_sec=100.0,
        completed_slice_samples=(
            CompletedSliceDurationSample(duration_sec=60.0),
            CompletedSliceDurationSample(duration_sec=300.0),
            CompletedSliceDurationSample(duration_sec=90.0),
        ),
    )

    assert left_sec == pytest.approx(130.0)


def test_estimate_batch_remaining_sec_uses_completed_history_when_current_eta_is_unavailable() -> None:
    left_sec = estimate_batch_remaining_sec(
        total_slices=5,
        completed_count=2,
        current_eta_sec=None,
        current_total_estimate_sec=None,
        completed_slice_samples=(
            CompletedSliceDurationSample(duration_sec=60.0),
            CompletedSliceDurationSample(duration_sec=90.0),
        ),
    )

    assert left_sec == pytest.approx(225.0)
