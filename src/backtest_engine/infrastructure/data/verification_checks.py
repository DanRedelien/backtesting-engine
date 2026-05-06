"""Individual validation checks for provider-managed market data."""

from __future__ import annotations

from datetime import datetime, timedelta
from statistics import mean, pstdev
from zoneinfo import ZoneInfoNotFoundError

import pandas as pd

from backtest_engine.domain.market.calendars import (
    TradingCalendarSpec,
    gap_is_expected,
    resolve_trading_calendar,
)
from backtest_engine.infrastructure.data.coverage_policy import (
    TIMEFRAME_TO_MINUTES,
    assess_requested_coverage,
)
from backtest_engine.infrastructure.data.market_data_contracts import (
    SourceSliceManifest,
    ValidationWindowSummary,
)
from backtest_engine.infrastructure.data.market_data_store import FilesystemHistoricalDataStore
from backtest_engine.infrastructure.data.verification_results import (
    CheckOutcome,
    build_issue,
    issue_based_ratio_check,
    na_check,
)


def check_path_integrity(
    *,
    store: FilesystemHistoricalDataStore,
    provider_id: str,
    canonical_symbol: str,
    timeframe: str,
    source_manifest: SourceSliceManifest,
) -> CheckOutcome:
    canonical_path = store.canonical_bars_path(provider_id, canonical_symbol, timeframe)
    if store.source_path_matches_canonical(
        provider_id=provider_id,
        canonical_symbol=canonical_symbol,
        timeframe=timeframe,
        bars_path=source_manifest.bars_path,
    ):
        return CheckOutcome(check_code="path_integrity", checked_count=1, score_pct=100.0)
    return CheckOutcome(
        check_code="path_integrity",
        issues=(
            build_issue(
                "FAIL",
                "non_canonical_bars_path",
                "source manifest bars path does not match the canonical storage path",
                manifest_path=str(source_manifest.bars_path),
                canonical_path=str(canonical_path),
            ),
        ),
        affected_count=1,
        checked_count=1,
        score_pct=0.0,
    )


def check_supported_timeframe(timeframe: str) -> CheckOutcome:
    if timeframe in TIMEFRAME_TO_MINUTES:
        return CheckOutcome(check_code="timeframe_support", checked_count=1, score_pct=100.0)
    return CheckOutcome(
        check_code="timeframe_support",
        issues=(
            build_issue(
                "FAIL",
                "unsupported_timeframe",
                "source slice timeframe is not supported by the validator",
                timeframe=timeframe,
            ),
        ),
        affected_count=1,
        checked_count=1,
        score_pct=0.0,
    )


def resolve_calendar_check(
    calendar_id: str,
    *,
    timezone_name: str,
) -> tuple[TradingCalendarSpec | None, CheckOutcome]:
    try:
        calendar = resolve_trading_calendar(calendar_id, timezone_name=timezone_name)
    except (ValueError, ZoneInfoNotFoundError):
        return None, CheckOutcome(
            check_code="calendar_policy",
            issues=(
                build_issue(
                    "FAIL",
                    "invalid_calendar_policy",
                    "source slice references an invalid calendar or timezone policy",
                    calendar_id=calendar_id,
                    timezone_name=timezone_name,
                ),
            ),
            affected_count=1,
            checked_count=1,
            score_pct=0.0,
        )
    return calendar, CheckOutcome(check_code="calendar_policy", checked_count=1, score_pct=100.0)


def check_required_columns(missing: tuple[str, ...]) -> CheckOutcome:
    if not missing:
        return CheckOutcome(check_code="required_columns", checked_count=5, score_pct=100.0)
    return CheckOutcome(
        check_code="required_columns",
        issues=(
            build_issue(
                "FAIL",
                "missing_required_columns",
                "source slice is missing required OHLCV columns",
                missing_columns=",".join(missing),
            ),
        ),
        affected_count=len(missing),
        checked_count=5,
        score_pct=max(0.0, (1.0 - (len(missing) / 5.0)) * 100.0),
    )


def check_finite_ohlcv(frame: pd.DataFrame) -> CheckOutcome:
    column_by_lower = {str(column).lower(): column for column in frame.columns}
    invalid_counts: dict[str, int] = {}
    checked_count = 0
    for column_name in ("open", "high", "low", "close", "volume"):
        column = column_by_lower[column_name]
        numeric = pd.to_numeric(frame[column], errors="coerce")
        invalid = numeric.isna() | numeric.isin([float("inf"), float("-inf")])
        invalid_count = int(invalid.sum())
        checked_count += int(len(numeric))
        if invalid_count:
            invalid_counts[column_name] = invalid_count
    affected_count = sum(invalid_counts.values())
    if affected_count == 0:
        return CheckOutcome(
            check_code="finite_ohlcv", checked_count=max(checked_count, 1), score_pct=100.0
        )
    return CheckOutcome(
        check_code="finite_ohlcv",
        issues=(
            build_issue(
                "FAIL",
                "non_finite_ohlcv",
                "source slice contains null, NaN, infinite, or non-numeric OHLCV values",
                count=affected_count,
                columns=",".join(invalid_counts),
            ),
        ),
        affected_count=affected_count,
        checked_count=max(checked_count, 1),
        score_pct=max(0.0, (1.0 - (affected_count / max(checked_count, 1))) * 100.0),
    )


def check_index(frame: pd.DataFrame) -> tuple[CheckOutcome, CheckOutcome, CheckOutcome]:
    if not isinstance(frame.index, pd.DatetimeIndex):
        issue = build_issue("FAIL", "timestamp_index", "source slice must use a DatetimeIndex")
        return (
            CheckOutcome(
                check_code="timestamp_index",
                issues=(issue,),
                affected_count=1,
                checked_count=1,
                score_pct=0.0,
            ),
            na_check("duplicate_timestamps"),
            na_check("timestamp_ordering"),
        )

    duplicate_count = int(frame.index.duplicated().sum())
    ordering_count = timestamp_ordering_violations(frame.index)
    return (
        CheckOutcome(check_code="timestamp_index", checked_count=1, score_pct=100.0),
        issue_based_ratio_check(
            check_code="duplicate_timestamps",
            issue_code="duplicate_timestamps",
            message="source slice contains duplicate timestamps",
            affected_count=duplicate_count,
            checked_count=max(len(frame.index), 1),
            severity="FAIL",
        ),
        issue_based_ratio_check(
            check_code="timestamp_ordering",
            issue_code="timestamp_ordering",
            message="source slice timestamps are not ordered",
            affected_count=ordering_count,
            checked_count=max(len(frame.index) - 1, 1),
            severity="FAIL",
        ),
    )


def check_ohlc(frame: pd.DataFrame) -> CheckOutcome:
    working = frame.copy()
    working.columns = [str(column).lower() for column in working.columns]
    issues = []
    high_low = int((working["high"] < working["low"]).sum())
    if high_low:
        issues.append(
            build_issue("FAIL", "high_below_low", "found high < low violations", count=high_low)
        )
    high_open_close = int(
        ((working["high"] < working["open"]) | (working["high"] < working["close"])).sum()
    )
    if high_open_close:
        issues.append(
            build_issue(
                "FAIL",
                "high_below_open_close",
                "found high < open/close violations",
                count=high_open_close,
            )
        )
    low_open_close = int(
        ((working["low"] > working["open"]) | (working["low"] > working["close"])).sum()
    )
    if low_open_close:
        issues.append(
            build_issue(
                "FAIL",
                "low_above_open_close",
                "found low > open/close violations",
                count=low_open_close,
            )
        )
    denominator = len(working) * 4
    outside = 0
    average_column = next(
        (column for column in working.columns if column in {"average", "vwap"}), None
    )
    if average_column is not None:
        denominator += len(working)
        outside = int(
            (
                (working[average_column] < working["low"])
                | (working[average_column] > working["high"])
            ).sum()
        )
        if outside:
            issues.append(
                build_issue(
                    "WARN",
                    "average_outside_candle",
                    "found average/vwap values outside candle range",
                    count=outside,
                )
            )
    affected_count = high_low + high_open_close + low_open_close + outside
    score_pct = (
        100.0
        if affected_count == 0
        else max(0.0, (1.0 - (affected_count / max(denominator, 1))) * 100.0)
    )
    return CheckOutcome(
        check_code="ohlc_integrity",
        issues=tuple(issues),
        affected_count=affected_count,
        checked_count=max(denominator, 1),
        score_pct=score_pct,
    )


def check_requested_window(
    *,
    requested_start_utc: datetime,
    requested_end_utc: datetime,
    actual_start_utc: datetime,
    actual_end_utc: datetime,
    timeframe: str,
    calendar: TradingCalendarSpec | None,
) -> tuple[CheckOutcome, ValidationWindowSummary]:
    assessment = assess_requested_coverage(
        actual_start_utc=actual_start_utc,
        actual_end_utc=actual_end_utc,
        requested_start_utc=requested_start_utc,
        requested_end_utc=requested_end_utc,
        timeframe=timeframe,
        calendar_id=calendar.calendar_id if calendar is not None else None,
        timezone_name=calendar.timezone_name if calendar is not None else None,
    )
    issues = []
    if assessment.start_status == "missing":
        issues.append(
            build_issue(
                "FAIL",
                "requested_start_not_covered",
                "source slice does not cover the requested start timestamp",
                requested_start_utc=requested_start_utc.isoformat(),
                actual_start_utc=actual_start_utc.isoformat(),
            )
        )
    if assessment.end_status == "missing":
        issues.append(
            build_issue(
                "FAIL",
                "requested_end_not_covered",
                "source slice does not cover the requested end timestamp",
                requested_end_utc=requested_end_utc.isoformat(),
                actual_end_utc=actual_end_utc.isoformat(),
            )
        )
    affected_count = int(assessment.start_status == "missing") + int(
        assessment.end_status == "missing"
    )
    return (
        CheckOutcome(
            check_code="requested_window_coverage",
            issues=tuple(issues),
            affected_count=affected_count,
            checked_count=2,
            score_pct=max(0.0, (1.0 - (affected_count / 2.0)) * 100.0),
        ),
        ValidationWindowSummary(
            requested_start_utc=requested_start_utc,
            requested_end_utc=requested_end_utc,
            actual_start_utc=actual_start_utc,
            actual_end_utc=actual_end_utc,
            start_status=assessment.start_status,
            end_status=assessment.end_status,
        ),
    )


def check_gap_profile(
    frame: pd.DataFrame,
    timeframe: str,
    *,
    calendar: TradingCalendarSpec | None,
) -> CheckOutcome:
    step_minutes = TIMEFRAME_TO_MINUTES.get(timeframe)
    if step_minutes is None or len(frame) < 2 or calendar is None:
        return na_check("suspicious_gaps")
    threshold = timedelta(minutes=step_minutes * 3)
    suspicious = 0
    for previous_ts, current_ts in zip(frame.index[:-1], frame.index[1:]):
        gap = current_ts - previous_ts
        if gap <= threshold:
            continue
        if gap_is_expected(
            previous_ts.to_pydatetime(),
            current_ts.to_pydatetime(),
            timeframe_minutes=step_minutes,
            calendar=calendar,
        ):
            continue
        suspicious += 1
    return issue_based_ratio_check(
        check_code="suspicious_gaps",
        issue_code="suspicious_gaps",
        message="found suspicious non-session gaps in the source slice",
        affected_count=suspicious,
        checked_count=max(len(frame.index) - 1, 1),
        severity="WARN",
    )


def check_volume_anomalies(frame: pd.DataFrame) -> CheckOutcome:
    if "volume" not in {str(column).lower() for column in frame.columns}:
        return na_check("volume_anomalies")
    volume_column = next(column for column in frame.columns if str(column).lower() == "volume")
    volume = [float(value) for value in frame[volume_column] if pd.notna(value)]
    if len(volume) < 3:
        return na_check("volume_anomalies")
    std_value = pstdev(volume)
    if std_value == 0:
        return CheckOutcome(
            check_code="volume_anomalies", checked_count=len(volume), score_pct=100.0
        )
    mean_value = mean(volume)
    anomalies = sum(abs((value - mean_value) / std_value) > 5.0 for value in volume)
    return issue_based_ratio_check(
        check_code="volume_anomalies",
        issue_code="volume_anomalies",
        message="found extreme volume anomalies using a z-score threshold",
        affected_count=anomalies,
        checked_count=len(volume),
        severity="WARN",
    )


def check_return_anomalies(frame: pd.DataFrame) -> CheckOutcome:
    close_column = next(
        (column for column in frame.columns if str(column).lower() == "close"), None
    )
    if close_column is None or len(frame) < 3:
        return na_check("return_anomalies")
    returns = frame[close_column].pct_change(fill_method=None).dropna()
    if returns.empty:
        return na_check("return_anomalies")
    std_value = float(returns.std())
    if std_value == 0.0 or pd.isna(std_value):
        return CheckOutcome(
            check_code="return_anomalies", checked_count=len(returns), score_pct=100.0
        )
    mean_value = float(returns.mean())
    anomalies = int((((returns - mean_value).abs() / std_value) > 6.0).sum())
    return issue_based_ratio_check(
        check_code="return_anomalies",
        issue_code="return_anomalies",
        message="found suspicious return outliers using a z-score threshold",
        affected_count=anomalies,
        checked_count=len(returns),
        severity="WARN",
    )


def check_tick_alignment(
    frame: pd.DataFrame,
    source_manifest: SourceSliceManifest,
) -> CheckOutcome:
    tick_size = source_manifest.instrument_metadata.get("tick_size")
    instrument_type = str(source_manifest.instrument_metadata.get("instrument_type") or "")
    if tick_size in {None, 0, 0.0}:
        return na_check("tick_alignment")
    if isinstance(tick_size, bool) or not isinstance(tick_size, str | int | float):
        return na_check("tick_alignment")
    tick = float(tick_size)
    issues = 0
    checked_count = 0
    for column_name in ("open", "high", "low", "close"):
        if column_name not in {str(column).lower() for column in frame.columns}:
            continue
        column = next(column for column in frame.columns if str(column).lower() == column_name)
        series = frame[column].dropna().astype(float)
        checked_count += len(series)
        misaligned = (((series / tick).round() - (series / tick)).abs() > 1e-6).sum()
        issues += int(misaligned)
    if issues == 0:
        return CheckOutcome(
            check_code="tick_alignment", checked_count=max(checked_count, 1), score_pct=100.0
        )
    return CheckOutcome(
        check_code="tick_alignment",
        issues=(
            build_issue(
                "FAIL" if instrument_type == "FUTURES" else "WARN",
                "futures_tick_alignment" if instrument_type == "FUTURES" else "tick_alignment",
                (
                    "found futures price values that do not align with the configured tick size"
                    if instrument_type == "FUTURES"
                    else "found price values that do not align with the configured tick size"
                ),
                count=issues,
            ),
        ),
        affected_count=issues,
        checked_count=max(checked_count, 1),
        score_pct=max(0.0, (1.0 - (issues / max(checked_count, 1))) * 100.0),
    )


def check_roll_audit(
    *,
    store: FilesystemHistoricalDataStore,
    provider_id: str,
    canonical_symbol: str,
    timeframe: str,
    frame: pd.DataFrame,
    source_manifest: SourceSliceManifest,
) -> CheckOutcome:
    roll_manifest = store.load_roll_manifest(provider_id, canonical_symbol, timeframe)
    if roll_manifest is None:
        return na_check("ib_roll_audit")
    issues = []
    checked_count = max(len(roll_manifest.contract_windows) + len(roll_manifest.events), 1)
    tick_size = source_manifest.instrument_metadata.get("tick_size")
    if tick_size in {None, 0, 0.0} or isinstance(tick_size, bool):
        futures_tick = None
    elif isinstance(tick_size, str | int | float):
        futures_tick = float(tick_size)
    else:
        futures_tick = None

    adjusted_contracts: set[str] | None = None
    if "contract" not in frame.columns:
        issues.append(
            build_issue(
                "FAIL",
                "missing_contract_column",
                "adjusted futures slice is missing the contract column required for roll audit",
            )
        )
    else:
        adjusted_contracts = set(frame["contract"].dropna().astype(str))

    previous_end = None
    for contract_window in roll_manifest.contract_windows:
        if previous_end is not None and contract_window.start_utc < previous_end:
            issues.append(
                build_issue(
                    "FAIL",
                    "roll_chronology_overlap",
                    "contract windows overlap in the roll audit manifest",
                    contract_code=contract_window.contract_code,
                )
            )
        previous_end = contract_window.end_utc

    for event in roll_manifest.events:
        try:
            outgoing = store.load_raw_contract_frame(
                provider_id,
                canonical_symbol,
                timeframe,
                event.outgoing_contract,
            )
            incoming = store.load_raw_contract_frame(
                provider_id,
                canonical_symbol,
                timeframe,
                event.incoming_contract,
            )
        except FileNotFoundError:
            issues.append(
                build_issue(
                    "FAIL",
                    "missing_raw_contract",
                    "roll audit requires saved raw contract files",
                    outgoing_contract=event.outgoing_contract,
                    incoming_contract=event.incoming_contract,
                )
            )
            continue
        if outgoing.empty or incoming.empty:
            issues.append(
                build_issue(
                    "FAIL",
                    "empty_raw_contract",
                    "roll audit requires non-empty raw contract files",
                    outgoing_contract=event.outgoing_contract,
                    incoming_contract=event.incoming_contract,
                )
            )
            continue
        outgoing_close = float(outgoing["close"].iloc[-1])
        incoming_open = float(incoming["open"].iloc[0])
        expected_gap = incoming_open - outgoing_close
        if abs(expected_gap - event.additive_adjustment) > 1e-9:
            issues.append(
                build_issue(
                    "FAIL",
                    "roll_adjustment_mismatch",
                    "roll adjustment does not match saved raw contract prices",
                    outgoing_contract=event.outgoing_contract,
                    incoming_contract=event.incoming_contract,
                )
            )
        if futures_tick is not None and not values_align_to_tick(
            (event.additive_adjustment, event.cumulative_adjustment),
            futures_tick,
        ):
            issues.append(
                build_issue(
                    "FAIL",
                    "roll_adjustment_tick_alignment",
                    "roll adjustments are not aligned to the configured futures tick size",
                    outgoing_contract=event.outgoing_contract,
                    incoming_contract=event.incoming_contract,
                    tick_size=futures_tick,
                )
            )
        if adjusted_contracts is None:
            continue
        if event.incoming_contract not in adjusted_contracts:
            issues.append(
                build_issue(
                    "FAIL",
                    "incoming_contract_missing_from_adjusted_series",
                    "roll manifest references a contract that is absent from the adjusted series",
                    incoming_contract=event.incoming_contract,
                )
            )
    affected_count = len(issues)
    score_pct = (
        100.0 if affected_count == 0 else max(0.0, (1.0 - (affected_count / checked_count)) * 100.0)
    )
    return CheckOutcome(
        check_code="ib_roll_audit",
        issues=tuple(issues),
        affected_count=affected_count,
        checked_count=checked_count,
        score_pct=score_pct,
    )


def check_source_fingerprint_integrity(
    *,
    current_fingerprint: str,
    expected_fingerprint: str,
) -> CheckOutcome:
    if current_fingerprint == expected_fingerprint:
        return CheckOutcome(
            check_code="source_fingerprint_integrity", checked_count=1, score_pct=100.0
        )
    return CheckOutcome(
        check_code="source_fingerprint_integrity",
        issues=(
            build_issue(
                "FAIL",
                "stale_source_fingerprint",
                "source fingerprint changed since the last source manifest write",
            ),
        ),
        affected_count=1,
        checked_count=1,
        score_pct=0.0,
    )


def missing_required_columns(frame: pd.DataFrame) -> tuple[str, ...]:
    required = {"open", "high", "low", "close", "volume"}
    present = {str(column).lower() for column in frame.columns}
    return tuple(sorted(required.difference(present)))


def timestamp_ordering_violations(index: pd.DatetimeIndex) -> int:
    return sum(current_ts < previous_ts for previous_ts, current_ts in zip(index[:-1], index[1:]))


def values_align_to_tick(values: tuple[float, ...], tick_size: float) -> bool:
    return all(abs(round(value / tick_size) - (value / tick_size)) <= 1e-6 for value in values)


__all__ = [
    "CheckOutcome",
    "check_gap_profile",
    "check_finite_ohlcv",
    "check_index",
    "check_ohlc",
    "check_path_integrity",
    "check_requested_window",
    "check_required_columns",
    "check_return_anomalies",
    "check_roll_audit",
    "check_source_fingerprint_integrity",
    "check_supported_timeframe",
    "check_tick_alignment",
    "check_volume_anomalies",
    "missing_required_columns",
    "resolve_calendar_check",
]
