"""Shared acceptance policy for provider-managed source-slice coverage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfoNotFoundError

from backtest_engine.core.time import ensure_utc
from backtest_engine.domain.market.calendars import (
    TradingCalendarSpec,
    gap_is_expected,
    resolve_trading_calendar,
)

NON_TRADING_END_GAP_TOLERANCE = timedelta(hours=72)
TIMEFRAME_TO_MINUTES = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "4h": 240,
    "1d": 1_440,
}

BoundaryStatus = Literal["covered", "expected_gap", "tolerated_gap", "missing"]


@dataclass(frozen=True)
class CoverageAssessment:
    """Typed acceptance result for one requested source-window coverage check."""

    start_status: BoundaryStatus
    end_status: BoundaryStatus
    start_gap: timedelta
    end_gap: timedelta

    @property
    def accepted(self) -> bool:
        return self.start_status != "missing" and self.end_status != "missing"


def assess_requested_coverage(
    *,
    actual_start_utc: datetime,
    actual_end_utc: datetime,
    requested_start_utc: datetime,
    requested_end_utc: datetime,
    timeframe: str | None = None,
    calendar_id: str | None = None,
    timezone_name: str | None = None,
    end_tolerance: timedelta = NON_TRADING_END_GAP_TOLERANCE,
) -> CoverageAssessment:
    """Return one canonical decision for requested-window coverage acceptance."""

    calendar = resolve_coverage_calendar(calendar_id=calendar_id, timezone_name=timezone_name)
    timeframe_minutes = TIMEFRAME_TO_MINUTES.get(timeframe) if timeframe is not None else None

    actual_start = ensure_utc(actual_start_utc)
    actual_end = ensure_utc(actual_end_utc)
    requested_start = ensure_utc(requested_start_utc)
    requested_end = ensure_utc(requested_end_utc)

    start_gap = max(actual_start - requested_start, timedelta(0))
    end_gap = max(requested_end - actual_end, timedelta(0))

    if actual_start <= requested_start:
        start_status: BoundaryStatus = "covered"
    elif boundary_gap_is_expected(
        earlier_utc=requested_start,
        later_utc=actual_start,
        timeframe_minutes=timeframe_minutes,
        calendar=calendar,
    ):
        start_status = "expected_gap"
    else:
        start_status = "missing"

    if actual_end >= requested_end:
        end_status: BoundaryStatus = "covered"
    elif boundary_gap_is_expected(
        earlier_utc=actual_end,
        later_utc=requested_end,
        timeframe_minutes=timeframe_minutes,
        calendar=calendar,
    ):
        end_status = "expected_gap"
    elif end_gap <= end_tolerance:
        end_status = "tolerated_gap"
    else:
        end_status = "missing"

    return CoverageAssessment(
        start_status=start_status,
        end_status=end_status,
        start_gap=start_gap,
        end_gap=end_gap,
    )


def describe_coverage_shortfall(assessment: CoverageAssessment) -> str:
    """Return a human-readable description for uncovered window boundaries."""

    parts: list[str] = []
    if assessment.start_status == "missing" and assessment.start_gap > timedelta(0):
        parts.append(f"start gap: {_format_gap(assessment.start_gap)}")
    if assessment.end_status == "missing" and assessment.end_gap > timedelta(0):
        parts.append(f"end gap: {_format_gap(assessment.end_gap)}")
    if not parts:
        return "no gap"
    return "; ".join(parts)


def resolve_coverage_calendar(
    *,
    calendar_id: str | None,
    timezone_name: str | None,
) -> TradingCalendarSpec | None:
    if calendar_id is None:
        return None
    try:
        return resolve_trading_calendar(calendar_id, timezone_name=timezone_name)
    except (ValueError, ZoneInfoNotFoundError):
        return None


def boundary_gap_is_expected(
    *,
    earlier_utc: datetime,
    later_utc: datetime,
    timeframe_minutes: int | None,
    calendar: TradingCalendarSpec | None,
) -> bool:
    if timeframe_minutes is None or calendar is None:
        return False
    return gap_is_expected(
        ensure_utc(earlier_utc),
        ensure_utc(later_utc),
        timeframe_minutes=timeframe_minutes,
        calendar=calendar,
    )


def _format_gap(delta: timedelta) -> str:
    hours = delta.total_seconds() / 3600
    if hours < 48:
        return f"{hours:.1f}h"
    return f"{hours / 24:.1f} days"


__all__ = [
    "BoundaryStatus",
    "CoverageAssessment",
    "NON_TRADING_END_GAP_TOLERANCE",
    "TIMEFRAME_TO_MINUTES",
    "assess_requested_coverage",
    "boundary_gap_is_expected",
    "describe_coverage_shortfall",
    "resolve_coverage_calendar",
]
