"""Shared progress helpers for provider-managed historical downloads."""

from __future__ import annotations

from datetime import datetime, timedelta

from backtest_engine.core.time import ensure_utc
from backtest_engine.infrastructure.data.coverage_policy import (
    NON_TRADING_END_GAP_TOLERANCE,
    assess_requested_coverage,
    describe_coverage_shortfall,
)


def compute_requested_coverage_progress(
    *,
    requested_start_utc: datetime,
    requested_end_utc: datetime,
    actual_start_utc: datetime | None,
    actual_end_utc: datetime | None,
) -> float:
    """Return approximate requested-window coverage as a fraction in ``[0, 1]``."""

    requested_start = ensure_utc(requested_start_utc)
    requested_end = ensure_utc(requested_end_utc)
    if requested_end <= requested_start:
        return 1.0
    if actual_start_utc is None or actual_end_utc is None:
        return 0.0

    actual_start = ensure_utc(actual_start_utc)
    actual_end = ensure_utc(actual_end_utc)
    covered_start = max(requested_start, actual_start)
    covered_end = min(requested_end, actual_end)
    if covered_end <= covered_start:
        return 0.0

    requested_span_sec = (requested_end - requested_start).total_seconds()
    covered_span_sec = (covered_end - covered_start).total_seconds()
    if requested_span_sec <= 0.0:
        return 1.0
    return max(0.0, min(1.0, covered_span_sec / requested_span_sec))


def estimate_eta_sec(*, elapsed_sec: float, progress_frac: float) -> float | None:
    """Estimate remaining seconds from elapsed time and observed progress."""

    if progress_frac <= 0.0:
        return None
    if progress_frac >= 1.0:
        return 0.0
    return max(0.0, elapsed_sec * (1.0 - progress_frac) / progress_frac)


def is_coverage_sufficient(
    *,
    actual_start_utc: datetime,
    actual_end_utc: datetime,
    requested_start_utc: datetime,
    requested_end_utc: datetime,
    timeframe: str | None = None,
    calendar_id: str | None = None,
    timezone_name: str | None = None,
    end_tolerance: timedelta = NON_TRADING_END_GAP_TOLERANCE,
) -> bool:
    """Check if actual coverage satisfies the requested window."""
    return assess_requested_coverage(
        actual_start_utc=actual_start_utc,
        actual_end_utc=actual_end_utc,
        requested_start_utc=requested_start_utc,
        requested_end_utc=requested_end_utc,
        timeframe=timeframe,
        calendar_id=calendar_id,
        timezone_name=timezone_name,
        end_tolerance=end_tolerance,
    ).accepted


def describe_coverage_gap(
    *,
    actual_start_utc: datetime,
    actual_end_utc: datetime,
    requested_start_utc: datetime,
    requested_end_utc: datetime,
    timeframe: str | None = None,
    calendar_id: str | None = None,
    timezone_name: str | None = None,
) -> str:
    """Return a human-readable description of the gap between actual and requested coverage."""
    return describe_coverage_shortfall(
        assess_requested_coverage(
            actual_start_utc=actual_start_utc,
            actual_end_utc=actual_end_utc,
            requested_start_utc=requested_start_utc,
            requested_end_utc=requested_end_utc,
            timeframe=timeframe,
            calendar_id=calendar_id,
            timezone_name=timezone_name,
        )
    )


__all__ = [
    "compute_requested_coverage_progress",
    "describe_coverage_gap",
    "estimate_eta_sec",
    "is_coverage_sufficient",
]
