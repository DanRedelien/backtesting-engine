from __future__ import annotations

import io
from datetime import datetime, timezone
from pathlib import Path

from backtest_engine.application.market_data import (
    HistoricalMarketDataBatchResult,
    HistoricalMarketDataRequest,
    HistoricalMarketDataSliceResult,
    MarketDataDryRunMetadata,
    MarketDataErrorDetail,
    MarketDataValidationCheckDetail,
    MarketDataValidationReport,
    MarketDataValidationScoreSummary,
    MarketDataValidationWindowSummary,
    MarketDataVerificationBatchResult,
    MarketDataVerificationRequest,
    MarketDataVerificationSliceResult,
)
from backtest_engine.core.enums import DatasetSource
from backtest_engine.application.market_data import PartialBatchFailureError
from backtest_engine.infrastructure.observability import StageDiagnosticEvent


class TtyStringIO(io.StringIO):
    def isatty(self) -> bool:
        return True


def build_validation_report(
    *,
    source_fingerprint: str,
    verification_verdict: str,
    check_results: tuple[MarketDataValidationCheckDetail, ...],
    overall_score_pct: float | None,
    applicable_check_count: int,
    total_check_count: int,
    warning_check_count: int,
    failed_check_count: int,
    window_summary: MarketDataValidationWindowSummary | None = None,
) -> MarketDataValidationReport:
    return MarketDataValidationReport(
        source_fingerprint=source_fingerprint,
        validator_ruleset_version="market_data_rules_v5",
        verification_verdict=verification_verdict,
        check_results=check_results,
        score_summary=MarketDataValidationScoreSummary(
            overall_score_pct=overall_score_pct,
            applicable_check_count=applicable_check_count,
            total_check_count=total_check_count,
            warning_check_count=warning_check_count,
            failed_check_count=failed_check_count,
        ),
        window_summary=window_summary,
        warning_count=warning_check_count,
        failure_count=failed_check_count,
        verified_at_utc=datetime(2026, 4, 11, tzinfo=timezone.utc),
    )


def progress_event(
    *,
    provider_id: str = "mt5",
    canonical_symbol: str = "EURUSD",
    timeframe: str = "5m",
    progress_pct: float = 50.0,
    row_count: int = 1200,
    elapsed_sec: float = 30.0,
    eta_sec: float | None = 30.0,
    requested_start_utc: str | None = "2020-06-01T00:00:00+00:00",
    requested_end_utc: str | None = "2020-06-20T00:00:00+00:00",
    actual_start_utc: str | None = "2020-06-10T00:00:00+00:00",
    actual_end_utc: str | None = "2020-06-20T00:00:00+00:00",
) -> StageDiagnosticEvent:
    return StageDiagnosticEvent(
        stage="market_data.slice.download.progress",
        status="started",
        message="progress",
        requested_by="cli",
        details={
            "provider_id": provider_id,
            "canonical_symbol": canonical_symbol,
            "timeframe": timeframe,
            "progress_pct": progress_pct,
            "row_count": row_count,
            "elapsed_sec": elapsed_sec,
            "eta_sec": eta_sec,
            "requested_start_utc": requested_start_utc,
            "requested_end_utc": requested_end_utc,
            "actual_start_utc": actual_start_utc,
            "actual_end_utc": actual_end_utc,
        },
    )


class FakeService:
    def __init__(self) -> None:
        self.download_requests: list[HistoricalMarketDataRequest] = []
        self.verify_requests: list[MarketDataVerificationRequest] = []

    def download(self, request: HistoricalMarketDataRequest) -> HistoricalMarketDataBatchResult:
        self.download_requests.append(request)
        dry_run_metadata = None
        if request.dry_run:
            dry_run_metadata = MarketDataDryRunMetadata(
                provider_symbol="EURUSD",
                supported_timeframes=("5m",),
                window_mode="explicit" if request.start_utc is not None else "max_available",
                requested_start_utc=(
                    request.start_utc
                    if request.start_utc is not None
                    else datetime(1970, 1, 1, tzinfo=timezone.utc)
                ),
                requested_end_utc=(
                    request.end_utc
                    if request.end_utc is not None
                    else datetime(2026, 4, 15, 12, 0, tzinfo=timezone.utc)
                ),
                calendar_id="FX_24_5",
            )
        return HistoricalMarketDataBatchResult(
            request=request,
            slice_results=(
                HistoricalMarketDataSliceResult(
                    provider_id=request.provider_id,
                    source_system=DatasetSource.MT5,
                    canonical_symbol="EURUSD",
                    timeframe="5m",
                    status="downloaded",
                    bars_path=Path("data/cache/mt5/EURUSD/5m/bars.parquet"),
                    source_manifest_path=Path("data/cache/mt5/EURUSD/5m/source_manifest.json"),
                    dry_run_metadata=dry_run_metadata,
                ),
            ),
        )

    def verify(self, request: MarketDataVerificationRequest) -> MarketDataVerificationBatchResult:
        self.verify_requests.append(request)
        return MarketDataVerificationBatchResult(
            request=request,
            slice_results=(
                MarketDataVerificationSliceResult(
                    provider_id=request.provider_id,
                    canonical_symbol="EURUSD",
                    timeframe="5m",
                    status="verified",
                    validation_manifest_path=Path("data/cache/mt5/EURUSD/5m/validation_manifest.json"),
                    validation_manifest=build_validation_report(
                        source_fingerprint="a" * 64,
                        verification_verdict="PASS",
                        check_results=(
                            MarketDataValidationCheckDetail(
                                check_code="required_columns",
                                check_label="Required columns",
                                check_status="OK",
                                score_pct=100.0,
                            ),
                            MarketDataValidationCheckDetail(
                                check_code="tick_alignment",
                                check_label="Tick alignment",
                                check_status="WARN",
                                score_pct=75.0,
                                affected_count=1,
                                checked_count=8,
                                issue_codes=("tick_alignment",),
                                sample_details=({"count": "1"},),
                            ),
                        ),
                        overall_score_pct=87.5,
                        applicable_check_count=2,
                        total_check_count=3,
                        warning_check_count=1,
                        failed_check_count=0,
                        window_summary=MarketDataValidationWindowSummary(
                            requested_start_utc=datetime(2024, 1, 1, tzinfo=timezone.utc),
                            requested_end_utc=datetime(2024, 1, 2, tzinfo=timezone.utc),
                            actual_start_utc=datetime(2024, 1, 1, tzinfo=timezone.utc),
                            actual_end_utc=datetime(2024, 1, 2, tzinfo=timezone.utc),
                            start_status="covered",
                            end_status="covered",
                        ),
                    ),
                ),
            ),
        )


class VerifyPartialFailureService:
    def verify(self, request: MarketDataVerificationRequest) -> MarketDataVerificationBatchResult:
        result = MarketDataVerificationBatchResult(
            request=request,
            slice_results=(
                MarketDataVerificationSliceResult(
                    provider_id=request.provider_id,
                    canonical_symbol="EURUSD",
                    timeframe="5m",
                    status="verified",
                    validation_manifest_path=Path("data/cache/mt5/EURUSD/5m/validation_manifest.json"),
                    validation_manifest=FakeService().verify(request).slice_results[0].validation_manifest,
                ),
                MarketDataVerificationSliceResult(
                    provider_id=request.provider_id,
                    canonical_symbol="GBPUSD",
                    timeframe="5m",
                    status="failed",
                    validation_manifest_path=Path("data/cache/mt5/GBPUSD/5m/validation_manifest.json"),
                    validation_manifest=build_validation_report(
                        source_fingerprint="b" * 64,
                        verification_verdict="FAIL",
                        check_results=(
                            MarketDataValidationCheckDetail(
                                check_code="required_columns",
                                check_label="Required columns",
                                check_status="BAD",
                                score_pct=80.0,
                                affected_count=1,
                                checked_count=5,
                                issue_codes=("missing_required_columns",),
                                sample_details=({"missing_columns": "high"},),
                            ),
                        ),
                        overall_score_pct=80.0,
                        applicable_check_count=1,
                        total_check_count=1,
                        warning_check_count=0,
                        failed_check_count=1,
                    ),
                    error=MarketDataErrorDetail(
                        code="VerificationFailedError",
                        message="market-data verification failed",
                    ),
                ),
            ),
        )
        raise PartialBatchFailureError(
            "one or more market-data slices failed during verification",
            batch_result=result,
            failed_count=1,
        )


class PartialFailureService:
    """Service that raises PartialBatchFailureError for mixed-outcome batches."""

    def __init__(self) -> None:
        self.download_requests: list[HistoricalMarketDataRequest] = []

    def download(self, request: HistoricalMarketDataRequest) -> HistoricalMarketDataBatchResult:
        self.download_requests.append(request)
        result = HistoricalMarketDataBatchResult(
            request=request,
            slice_results=(
                HistoricalMarketDataSliceResult(
                    provider_id=request.provider_id,
                    source_system=DatasetSource.MT5,
                    canonical_symbol="EURUSD",
                    timeframe="5m",
                    status="downloaded",
                    bars_path=Path("data/cache/mt5/EURUSD/5m/bars.parquet"),
                    source_manifest_path=Path("data/cache/mt5/EURUSD/5m/source_manifest.json"),
                ),
                HistoricalMarketDataSliceResult(
                    provider_id=request.provider_id,
                    source_system=DatasetSource.MT5,
                    canonical_symbol="BAD",
                    timeframe="5m",
                    status="failed",
                    error=MarketDataErrorDetail(
                        code="SymbolMappingError",
                        message="unknown MT5 symbol mapping",
                    ),
                ),
            ),
        )
        raise PartialBatchFailureError(
            "one or more slices failed",
            batch_result=result,
            failed_count=1,
        )
