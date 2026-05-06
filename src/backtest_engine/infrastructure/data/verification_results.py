"""Verification result assembly helpers for market-data validation."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean

from backtest_engine.infrastructure.data.errors import InvalidSourceDataError
from backtest_engine.infrastructure.data.market_data_contracts import (
    MarketDataIssue,
    ValidationCheckResult,
    ValidationCheckStatus,
    ValidationScoreSummary,
    ValidationSeverity,
)


CHECK_SAMPLE_LIMIT = 3
WARN_DEFAULT_SCORE_PCT = 75.0
CHECK_LABELS: dict[str, str] = {
    "path_integrity": "Canonical path integrity",
    "frame_presence": "Frame presence",
    "calendar_policy": "Calendar policy",
    "timeframe_support": "Timeframe support",
    "required_columns": "Required columns",
    "timestamp_index": "Timestamp index",
    "duplicate_timestamps": "Duplicate timestamps",
    "timestamp_ordering": "Timestamp ordering",
    "finite_ohlcv": "Finite OHLCV values",
    "ohlc_integrity": "OHLC integrity",
    "requested_window_coverage": "Requested window coverage",
    "suspicious_gaps": "Suspicious gaps",
    "volume_anomalies": "Volume anomalies",
    "return_anomalies": "Return anomalies",
    "tick_alignment": "Tick alignment",
    "ib_roll_audit": "IB roll audit",
    "source_fingerprint_integrity": "Source fingerprint integrity",
}
IssueDetailValue = str | int | float | bool | None


@dataclass(frozen=True)
class CheckOutcome:
    check_code: str
    issues: tuple[MarketDataIssue, ...] = ()
    applicable: bool = True
    affected_count: int | None = None
    checked_count: int | None = None
    score_pct: float | None = None

    def to_result(self) -> ValidationCheckResult:
        if not self.applicable:
            status = ValidationCheckStatus.NA
            score_pct = None
        elif any(issue.severity == ValidationSeverity.FAIL for issue in self.issues):
            status = ValidationCheckStatus.BAD
            score_pct = self.score_pct if self.score_pct is not None else 0.0
        elif any(issue.severity == ValidationSeverity.WARN for issue in self.issues):
            status = ValidationCheckStatus.WARN
            score_pct = self.score_pct if self.score_pct is not None else WARN_DEFAULT_SCORE_PCT
        else:
            status = ValidationCheckStatus.OK
            score_pct = self.score_pct if self.score_pct is not None else 100.0
        return ValidationCheckResult(
            check_code=self.check_code,
            check_label=CHECK_LABELS.get(self.check_code),
            check_status=status,
            score_pct=score_pct,
            affected_count=self.affected_count,
            checked_count=self.checked_count,
            issue_codes=tuple(issue.code for issue in self.issues),
            sample_details=tuple(issue.details for issue in self.issues if issue.details)[
                :CHECK_SAMPLE_LIMIT
            ],
        )


def build_score_summary(check_results: tuple[ValidationCheckResult, ...]) -> ValidationScoreSummary:
    applicable = tuple(
        item for item in check_results if item.check_status != ValidationCheckStatus.NA
    )
    score_values = tuple(item.score_pct for item in applicable if item.score_pct is not None)
    overall_score_pct = mean(score_values) if score_values else None
    return ValidationScoreSummary(
        overall_score_pct=overall_score_pct,
        applicable_check_count=len(applicable),
        total_check_count=len(check_results),
        warning_check_count=sum(
            item.check_status == ValidationCheckStatus.WARN for item in applicable
        ),
        failed_check_count=sum(
            item.check_status == ValidationCheckStatus.BAD for item in applicable
        ),
    )


def na_check(check_code: str) -> CheckOutcome:
    return CheckOutcome(check_code=check_code, applicable=False)


def issue_based_ratio_check(
    *,
    check_code: str,
    issue_code: str,
    message: str,
    affected_count: int,
    checked_count: int,
    severity: str,
) -> CheckOutcome:
    if affected_count <= 0:
        return CheckOutcome(
            check_code=check_code, checked_count=max(checked_count, 1), score_pct=100.0
        )
    return CheckOutcome(
        check_code=check_code,
        issues=(
            build_issue(
                severity,
                issue_code,
                message,
                count=affected_count,
            ),
        ),
        affected_count=affected_count,
        checked_count=max(checked_count, 1),
        score_pct=max(0.0, (1.0 - (affected_count / max(checked_count, 1))) * 100.0),
    )


def build_issue(
    severity: str,
    code: str,
    message: str,
    **details: IssueDetailValue,
) -> MarketDataIssue:
    if severity not in {ValidationSeverity.WARN, ValidationSeverity.FAIL}:
        raise InvalidSourceDataError("unknown validation issue severity", severity=severity)
    return MarketDataIssue(
        severity=severity,
        code=code,
        message=message,
        details={
            key: validate_issue_detail(value=value, key=key) for key, value in details.items()
        },
    )


def validate_issue_detail(*, value: IssueDetailValue, key: str) -> IssueDetailValue:
    if value is None or isinstance(value, bool | str | int | float):
        return value
    raise InvalidSourceDataError("unsupported validation issue detail type", detail_key=key)


__all__ = [
    "CheckOutcome",
    "CHECK_LABELS",
    "IssueDetailValue",
    "build_issue",
    "build_score_summary",
    "issue_based_ratio_check",
    "na_check",
]
