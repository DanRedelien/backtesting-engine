"""Formatting and estimation helpers for market-data CLI progress output."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from statistics import median
from typing import Iterable

from backtest_engine.core.time import ensure_utc


@dataclass(frozen=True)
class CompletedSliceDurationSample:
    """One completed slice duration eligible for batch ETA estimation."""

    duration_sec: float


def select_frontier_date_utc(
    *,
    requested_start_utc: datetime | None,
    requested_end_utc: datetime | None,
    actual_start_utc: datetime | None,
    actual_end_utc: datetime | None,
) -> datetime | None:
    """Return the UTC boundary that best represents current progress frontier."""

    if (
        requested_start_utc is None
        or requested_end_utc is None
        or actual_start_utc is None
        or actual_end_utc is None
    ):
        return None
    requested_start = ensure_utc(requested_start_utc)
    requested_end = ensure_utc(requested_end_utc)
    actual_start = ensure_utc(actual_start_utc)
    actual_end = ensure_utc(actual_end_utc)

    uncovered_start_sec = max((actual_start - requested_start).total_seconds(), 0.0)
    uncovered_end_sec = max((requested_end - actual_end).total_seconds(), 0.0)
    return actual_start if uncovered_start_sec >= uncovered_end_sec else actual_end


def format_progress_line(
    *,
    provider_id: str,
    canonical_symbol: str,
    timeframe: str,
    progress_pct: float,
    row_count: int,
    frontier_date_utc: datetime | None,
    left_sec: float | None,
) -> str:
    """Render one stable, machine-parseable progress line."""

    return " ".join(
        (
            "PROGRESS",
            provider_id,
            canonical_symbol,
            timeframe,
            f"{progress_pct:5.1f}%",
            f"rows={row_count:,}",
            f"date={format_progress_date(frontier_date_utc)}",
            f"left={format_remaining_duration(left_sec)}",
        )
    )


def format_progress_date(frontier_date_utc: datetime | None) -> str:
    """Render the progress frontier date in UTC calendar form."""

    if frontier_date_utc is None:
        return "--"
    return ensure_utc(frontier_date_utc).date().isoformat()


def format_remaining_duration(total_seconds: float | None) -> str:
    """Render a compact remaining-duration token for progress lines."""

    if total_seconds is None:
        return "--"
    clamped = max(0.0, total_seconds)
    rounded = int(round(clamped))
    hours, remainder = divmod(rounded, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours > 0:
        return f"{hours:d}h{minutes:02d}m"
    return f"{minutes:d}m{seconds:02d}s"


def format_total_duration(total_seconds: float | None) -> str:
    """Render a compact total duration token for completion lines."""

    if total_seconds is None:
        return "--"
    clamped = max(0.0, total_seconds)
    if clamped < 10.0:
        return f"{clamped:04.1f}s"
    rounded = int(round(clamped))
    hours, remainder = divmod(rounded, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def estimate_batch_remaining_sec(
    *,
    total_slices: int,
    completed_count: int,
    current_eta_sec: float | None,
    current_total_estimate_sec: float | None,
    completed_slice_samples: Iterable[CompletedSliceDurationSample],
) -> float | None:
    """Estimate remaining batch runtime from stable current and completed slices."""

    if total_slices <= 0:
        return current_eta_sec

    eligible_durations = sorted(
        sample.duration_sec
        for sample in completed_slice_samples
        if sample.duration_sec > 0.0
    )
    median_completed_sec = median(eligible_durations) if eligible_durations else None
    remaining_including_current = max(total_slices - completed_count, 0)
    remaining_after_current = max(remaining_including_current - 1, 0)
    if median_completed_sec is not None:
        if current_eta_sec is None:
            return median_completed_sec * remaining_including_current
        return current_eta_sec + (median_completed_sec * remaining_after_current)
    if current_total_estimate_sec is not None:
        if current_eta_sec is None:
            return current_total_estimate_sec * remaining_including_current
        return current_eta_sec + (current_total_estimate_sec * remaining_after_current)
    if current_eta_sec is not None and remaining_after_current == 0:
        return current_eta_sec
    return None


__all__ = [
    "CompletedSliceDurationSample",
    "estimate_batch_remaining_sec",
    "format_progress_date",
    "format_progress_line",
    "format_remaining_duration",
    "format_total_duration",
    "select_frontier_date_utc",
]
