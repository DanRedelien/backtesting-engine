"""Structured verification for provider-managed historical market data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from backtest_engine.core.enums import DatasetSource
from backtest_engine.core.market_data_validation import MARKET_DATA_VALIDATOR_RULESET_VERSION
from backtest_engine.infrastructure.data.errors import (
    InvalidSourceDataError,
    VerificationFailedError,
)
from backtest_engine.infrastructure.data.market_data_contracts import (
    ValidationManifest,
    ValidationSeverity,
)
from backtest_engine.infrastructure.data.market_data_store import FilesystemHistoricalDataStore
from backtest_engine.infrastructure.data.verification_checks import (
    CheckOutcome,
    check_gap_profile,
    check_finite_ohlcv,
    check_index,
    check_ohlc,
    check_path_integrity,
    check_requested_window,
    check_required_columns,
    check_return_anomalies,
    check_roll_audit,
    check_source_fingerprint_integrity,
    check_supported_timeframe,
    check_tick_alignment,
    check_volume_anomalies,
    missing_required_columns,
    resolve_calendar_check,
)
from backtest_engine.infrastructure.data.verification_results import (
    build_issue,
    build_score_summary,
    na_check,
)


@dataclass(frozen=True)
class MarketDataValidator:
    """Validate one saved source slice and persist a structured verdict."""

    store: FilesystemHistoricalDataStore
    ruleset_version: str = MARKET_DATA_VALIDATOR_RULESET_VERSION

    def validate_slice(
        self,
        *,
        provider_id: str,
        canonical_symbol: str,
        timeframe: str,
    ) -> ValidationManifest:
        try:
            source_manifest = self.store.load_source_manifest(
                provider_id, canonical_symbol, timeframe
            )
            frame = self.store.load_source_frame(provider_id, canonical_symbol, timeframe)
        except FileNotFoundError as exc:
            raise InvalidSourceDataError(
                "source slice artifacts are missing",
                provider_id=provider_id,
                symbol=canonical_symbol,
                timeframe=timeframe,
            ) from exc

        check_outcomes: list[CheckOutcome] = []
        check_outcomes.append(
            check_path_integrity(
                store=self.store,
                provider_id=provider_id,
                canonical_symbol=canonical_symbol,
                timeframe=timeframe,
                source_manifest=source_manifest,
            )
        )
        check_outcomes.append(check_supported_timeframe(timeframe))
        calendar, calendar_outcome = resolve_calendar_check(
            source_manifest.calendar_id,
            timezone_name=source_manifest.timezone_name,
        )
        check_outcomes.append(calendar_outcome)

        if frame.empty:
            check_outcomes.append(
                CheckOutcome(
                    check_code="frame_presence",
                    issues=(build_issue("FAIL", "empty_frame", "source slice is empty"),),
                    affected_count=1,
                    checked_count=1,
                    score_pct=0.0,
                )
            )
            check_outcomes.extend(
                (
                    na_check("required_columns"),
                    na_check("timestamp_index"),
                    na_check("duplicate_timestamps"),
                    na_check("timestamp_ordering"),
                    na_check("finite_ohlcv"),
                    na_check("ohlc_integrity"),
                    na_check("requested_window_coverage"),
                    na_check("suspicious_gaps"),
                    na_check("volume_anomalies"),
                    na_check("return_anomalies"),
                    na_check("tick_alignment"),
                    na_check("ib_roll_audit"),
                )
            )
            window_summary = None
        else:
            check_outcomes.append(
                CheckOutcome(check_code="frame_presence", checked_count=1, score_pct=100.0)
            )

            missing_columns = missing_required_columns(frame)
            check_outcomes.append(check_required_columns(missing_columns))
            check_outcomes.extend(check_index(frame))

            if missing_columns:
                check_outcomes.append(na_check("finite_ohlcv"))
                check_outcomes.append(na_check("ohlc_integrity"))
            else:
                check_outcomes.append(check_finite_ohlcv(frame))
                check_outcomes.append(check_ohlc(frame))

            window_outcome, window_summary = check_requested_window(
                requested_start_utc=source_manifest.requested_start_utc,
                requested_end_utc=source_manifest.requested_end_utc,
                actual_start_utc=source_manifest.actual_start_utc,
                actual_end_utc=source_manifest.actual_end_utc,
                timeframe=timeframe,
                calendar=calendar,
            )
            check_outcomes.append(window_outcome)
            check_outcomes.append(check_gap_profile(frame, timeframe, calendar=calendar))
            check_outcomes.append(check_volume_anomalies(frame))
            check_outcomes.append(check_return_anomalies(frame))
            check_outcomes.append(check_tick_alignment(frame, source_manifest))
            if source_manifest.source_system is DatasetSource.IB:
                check_outcomes.append(
                    check_roll_audit(
                        store=self.store,
                        provider_id=provider_id,
                        canonical_symbol=canonical_symbol,
                        timeframe=timeframe,
                        frame=frame,
                        source_manifest=source_manifest,
                    )
                )
            else:
                check_outcomes.append(na_check("ib_roll_audit"))

        try:
            current_fingerprint = self.store.compute_bars_hash(
                self.store.canonical_bars_path(provider_id, canonical_symbol, timeframe),
            )
        except OSError as exc:
            raise InvalidSourceDataError(
                "source parquet is inaccessible during fingerprint verification",
                provider_id=provider_id,
                symbol=canonical_symbol,
                timeframe=timeframe,
            ) from exc

        check_outcomes.append(
            check_source_fingerprint_integrity(
                current_fingerprint=current_fingerprint,
                expected_fingerprint=source_manifest.source_fingerprint,
            )
        )

        issues = tuple(issue for outcome in check_outcomes for issue in outcome.issues)
        check_results = tuple(outcome.to_result() for outcome in check_outcomes)
        failure_count = sum(issue.severity == ValidationSeverity.FAIL for issue in issues)
        warning_count = sum(issue.severity == ValidationSeverity.WARN for issue in issues)
        verification_verdict = "FAIL" if failure_count else "PASS"
        score_summary = build_score_summary(check_results)

        manifest = ValidationManifest(
            provider_id=provider_id,
            canonical_symbol=canonical_symbol,
            timeframe=timeframe,
            source_fingerprint=current_fingerprint,
            validator_ruleset_version=self.ruleset_version,
            verification_verdict=verification_verdict,
            issues=issues,
            check_results=check_results,
            score_summary=score_summary,
            window_summary=window_summary,
            warning_count=warning_count,
            failure_count=failure_count,
            verified_at_utc=datetime.now(timezone.utc),
        )
        self.store.save_validation_manifest(manifest)
        if failure_count:
            raise VerificationFailedError(
                "market-data verification failed",
                validation_manifest=manifest,
                validation_manifest_path=self.store.validation_manifest_path(
                    provider_id,
                    canonical_symbol,
                    timeframe,
                ),
                provider_id=provider_id,
                symbol=canonical_symbol,
                timeframe=timeframe,
                failure_count=failure_count,
            )
        return manifest


__all__ = ["MARKET_DATA_VALIDATOR_RULESET_VERSION", "MarketDataValidator"]
