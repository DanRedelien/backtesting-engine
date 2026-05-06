"""Application orchestration for provider-driven historical market data."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from backtest_engine.application.market_data.contracts import (
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
from backtest_engine.application.market_data.errors import PartialBatchFailureError
from backtest_engine.application.market_data.ports import HistoricalDataStore
from backtest_engine.core.enums import DatasetSource
from backtest_engine.core.errors import ApplicationError, BacktestEngineError
from backtest_engine.core.types import JsonObject
from backtest_engine.infrastructure.data.errors import VerificationFailedError
from backtest_engine.infrastructure.data.market_data_contracts import (
    DownloadedSourceSlice,
    DryRunMetadata,
    ValidationManifest,
)
from backtest_engine.infrastructure.observability import (
    DiagnosticStatus,
    DiagnosticsSink,
    NullDiagnosticsSink,
    StageDiagnosticEvent,
)


class HistoricalDataProvider(Protocol):
    """Provider adapter for one historical-data source."""

    @property
    def store(self) -> HistoricalDataStore:
        """Return the shared historical-data store used by this provider."""
        ...

    @property
    def provider_id(self) -> str:
        """Return the stable provider identifier."""
        ...

    @property
    def source_system(self) -> DatasetSource:
        """Return the provider-backed dataset source."""
        ...

    def supported_timeframes(self) -> tuple[str, ...]:
        """Return native provider timeframes."""
        ...

    def canonical_symbol_for(self, requested_symbol: str) -> str:
        """Resolve one requested provider symbol into the canonical storage symbol."""
        ...

    def download_slice(
        self,
        *,
        requested_symbol: str,
        timeframe: str,
        start_utc: datetime | None,
        end_utc: datetime | None,
        force: bool,
        dry_run: bool,
        requested_by: str,
    ) -> DownloadedSourceSlice:
        """Download one provider slice or describe it in dry-run mode."""
        ...


class HistoricalDataVerifier(Protocol):
    """Verification adapter over saved source slices."""

    @property
    def store(self) -> HistoricalDataStore:
        """Return the shared historical-data store used by this verifier."""
        ...

    @property
    def ruleset_version(self) -> str:
        """Return the validator ruleset version."""
        ...

    def validate_slice(
        self,
        *,
        provider_id: str,
        canonical_symbol: str,
        timeframe: str,
    ) -> ValidationManifest:
        """Validate one previously saved source slice."""
        ...


@dataclass(frozen=True)
class HistoricalMarketDataService:
    """Coordinate provider downloads and verification over source storage."""

    store: HistoricalDataStore
    providers: dict[str, HistoricalDataProvider]
    verifier: HistoricalDataVerifier
    diagnostics: DiagnosticsSink = NullDiagnosticsSink()

    def __post_init__(self) -> None:
        self._assert_shared_store(self.verifier.store, collaborator="verifier")
        for provider_id, provider in self.providers.items():
            self._assert_shared_store(provider.store, collaborator=f"provider:{provider_id}")

    def download(self, request: HistoricalMarketDataRequest) -> HistoricalMarketDataBatchResult:
        provider = self._resolve_provider(request.provider_id)
        slice_results: list[HistoricalMarketDataSliceResult] = []
        total_slices = len(request.symbol_universe) * len(request.timeframes)
        completed_slices = 0
        failed_slices = 0

        self._emit(
            stage="market_data.batch.download",
            status="started",
            message="starting historical market-data download batch",
            requested_by=request.requested_by,
            details={
                "provider_id": request.provider_id,
                "symbol_count": len(request.symbol_universe),
                "timeframe_count": len(request.timeframes),
                "total_slices": total_slices,
                "dry_run": request.dry_run,
                "force": request.force,
            },
        )

        for symbol in request.symbol_universe:
            try:
                canonical_symbol = provider.canonical_symbol_for(symbol)
            except BacktestEngineError as exc:
                slice_results.extend(
                    HistoricalMarketDataSliceResult(
                        provider_id=request.provider_id,
                        source_system=provider.source_system,
                        canonical_symbol=symbol,
                        timeframe=timeframe,
                        status="failed",
                        error=_error_detail(exc),
                    )
                    for timeframe in request.timeframes
                )
                for timeframe in request.timeframes:
                    completed_slices += 1
                    failed_slices += 1
                    self._emit_slice_terminal_status(
                        request=request,
                        provider_id=request.provider_id,
                        canonical_symbol=symbol,
                        timeframe=timeframe,
                        status="failed",
                        completed_slices=completed_slices,
                        total_slices=total_slices,
                        error=exc,
                    )
                continue
            for timeframe in request.timeframes:
                self._emit(
                    stage="market_data.slice.download",
                    status="started",
                    message="starting historical market-data slice download",
                    requested_by=request.requested_by,
                    details={
                        "provider_id": request.provider_id,
                        "requested_symbol": symbol,
                        "canonical_symbol": canonical_symbol,
                        "timeframe": timeframe,
                        "completed_slices": completed_slices,
                        "total_slices": total_slices,
                        "dry_run": request.dry_run,
                        "force": request.force,
                    },
                )
                try:
                    if (
                        request.start_utc is not None
                        and request.end_utc is not None
                        and not request.force
                        and not request.dry_run
                        and self.store.has_complete_verified_slice(
                            provider_id=request.provider_id,
                            canonical_symbol=canonical_symbol,
                            timeframe=timeframe,
                            requested_start_utc=request.start_utc,
                            requested_end_utc=request.end_utc,
                            validator_ruleset_version=self.verifier.ruleset_version,
                        )
                    ):
                        slice_results.append(
                            HistoricalMarketDataSliceResult(
                                provider_id=request.provider_id,
                                source_system=provider.source_system,
                                canonical_symbol=canonical_symbol,
                                timeframe=timeframe,
                                status="skipped_verified",
                                bars_path=self.store.bars_path(
                                    request.provider_id,
                                    canonical_symbol,
                                    timeframe,
                                ),
                                source_manifest_path=self.store.source_manifest_path(
                                    request.provider_id,
                                    canonical_symbol,
                                    timeframe,
                                ),
                            )
                        )
                        completed_slices += 1
                        self._emit_slice_terminal_status(
                            request=request,
                            provider_id=request.provider_id,
                            canonical_symbol=canonical_symbol,
                            timeframe=timeframe,
                            status="skipped_verified",
                            completed_slices=completed_slices,
                            total_slices=total_slices,
                        )
                        continue

                    downloaded = provider.download_slice(
                        requested_symbol=symbol,
                        timeframe=timeframe,
                        start_utc=request.start_utc,
                        end_utc=request.end_utc,
                        force=request.force,
                        dry_run=request.dry_run,
                        requested_by=request.requested_by,
                    )
                except BacktestEngineError as exc:
                    slice_results.append(
                        HistoricalMarketDataSliceResult(
                            provider_id=request.provider_id,
                            source_system=provider.source_system,
                            canonical_symbol=canonical_symbol,
                            timeframe=timeframe,
                            status="failed",
                            error=_error_detail(exc),
                        )
                    )
                    completed_slices += 1
                    failed_slices += 1
                    self._emit_slice_terminal_status(
                        request=request,
                        provider_id=request.provider_id,
                        canonical_symbol=canonical_symbol,
                        timeframe=timeframe,
                        status="failed",
                        completed_slices=completed_slices,
                        total_slices=total_slices,
                        error=exc,
                    )
                    continue

                final_status = "dry_run" if downloaded.dry_run else ("skipped" if downloaded.skipped else "downloaded")
                slice_results.append(
                    HistoricalMarketDataSliceResult(
                        provider_id=downloaded.provider_id,
                        source_system=provider.source_system,
                        canonical_symbol=downloaded.canonical_symbol,
                        timeframe=downloaded.timeframe,
                        status=final_status,
                        bars_path=downloaded.bars_path,
                        source_manifest_path=downloaded.source_manifest_path,
                        dry_run_metadata=_dry_run_metadata(downloaded.dry_run_metadata),
                    )
                )
                completed_slices += 1
                self._emit_slice_terminal_status(
                    request=request,
                    provider_id=downloaded.provider_id,
                    canonical_symbol=downloaded.canonical_symbol,
                    timeframe=downloaded.timeframe,
                    status=final_status,
                    completed_slices=completed_slices,
                    total_slices=total_slices,
                )

        result = HistoricalMarketDataBatchResult(
            request=request,
            slice_results=tuple(slice_results),
        )
        self._emit(
            stage="market_data.batch.download",
            status="failed" if not result.succeeded else "succeeded",
            message=(
                "historical market-data download batch failed"
                if not result.succeeded
                else "historical market-data download batch finished"
            ),
            requested_by=request.requested_by,
            details={
                "provider_id": request.provider_id,
                "completed_slices": completed_slices,
                "failed_slices": failed_slices,
                "total_slices": total_slices,
            },
        )
        if not result.succeeded:
            raise PartialBatchFailureError(
                "one or more market-data slices failed during download",
                batch_result=result,
                failed_count=sum(1 for r in result.slice_results if r.error is not None),
            )
        return result

    def verify(self, request: MarketDataVerificationRequest) -> MarketDataVerificationBatchResult:
        self._resolve_provider(request.provider_id)
        slice_results: list[MarketDataVerificationSliceResult] = []
        for symbol in request.symbol_universe:
            provider = self.providers[request.provider_id]
            try:
                canonical_symbol = provider.canonical_symbol_for(symbol)
            except BacktestEngineError as exc:
                slice_results.extend(
                    MarketDataVerificationSliceResult(
                        provider_id=request.provider_id,
                        canonical_symbol=symbol,
                        timeframe=timeframe,
                        status="failed",
                        error=_error_detail(exc),
                    )
                    for timeframe in request.timeframes
                )
                continue
            for timeframe in request.timeframes:
                try:
                    manifest = self.verifier.validate_slice(
                        provider_id=request.provider_id,
                        canonical_symbol=canonical_symbol,
                        timeframe=timeframe,
                    )
                except VerificationFailedError as exc:
                    slice_results.append(
                        MarketDataVerificationSliceResult(
                            provider_id=request.provider_id,
                            canonical_symbol=canonical_symbol,
                            timeframe=timeframe,
                            status="failed",
                            validation_manifest_path=exc.validation_manifest_path,
                            validation_manifest=_validation_report(exc.validation_manifest),
                            error=_error_detail(exc),
                        )
                    )
                    continue
                except BacktestEngineError as exc:
                    slice_results.append(
                        MarketDataVerificationSliceResult(
                            provider_id=request.provider_id,
                            canonical_symbol=canonical_symbol,
                            timeframe=timeframe,
                            status="failed",
                            error=_error_detail(exc),
                        )
                    )
                    continue
                slice_results.append(
                    MarketDataVerificationSliceResult(
                        provider_id=request.provider_id,
                        canonical_symbol=canonical_symbol,
                        timeframe=timeframe,
                        status="verified",
                        validation_manifest_path=self.store.validation_manifest_path(
                            request.provider_id,
                            canonical_symbol,
                            timeframe,
                        ),
                        validation_manifest=_validation_report(manifest),
                    )
                )
        result = MarketDataVerificationBatchResult(
            request=request,
            slice_results=tuple(slice_results),
        )
        if not result.succeeded:
            raise PartialBatchFailureError(
                "one or more market-data slices failed during verification",
                batch_result=result,
                failed_count=sum(1 for r in result.slice_results if r.error is not None),
            )
        return result

    def _resolve_provider(self, provider_id: str) -> HistoricalDataProvider:
        try:
            return self.providers[provider_id]
        except KeyError as exc:
            raise ApplicationError("unknown market-data provider", provider_id=provider_id) from exc

    def _assert_shared_store(
        self,
        collaborator_store: HistoricalDataStore,
        *,
        collaborator: str,
    ) -> None:
        if collaborator_store is self.store:
            return
        raise ApplicationError(
            "historical market-data service collaborators must share one store",
            collaborator=collaborator,
        )

    def _emit_slice_terminal_status(
        self,
        *,
        request: HistoricalMarketDataRequest,
        provider_id: str,
        canonical_symbol: str,
        timeframe: str,
        status: str,
        completed_slices: int,
        total_slices: int,
        error: BacktestEngineError | None = None,
    ) -> None:
        details: JsonObject = {
            "provider_id": provider_id,
            "canonical_symbol": canonical_symbol,
            "timeframe": timeframe,
            "slice_status": status,
            "completed_slices": completed_slices,
            "total_slices": total_slices,
        }
        if error is not None:
            details["error_type"] = type(error).__name__
            details["error_message"] = error.message
            details["error_context"] = json.dumps({k: str(v) for k, v in error.context.items()})
        self._emit(
            stage="market_data.slice.download",
            status="failed" if error is not None else "succeeded",
            message=(
                "historical market-data slice download failed"
                if error is not None
                else "historical market-data slice download finished"
            ),
            requested_by=request.requested_by,
            details=details,
        )

    def _emit(
        self,
        *,
        stage: str,
        status: DiagnosticStatus,
        message: str,
        requested_by: str,
        details: JsonObject,
    ) -> None:
        self.diagnostics.emit(
            StageDiagnosticEvent(
                stage=stage,
                status=status,
                message=message,
                requested_by=requested_by,
                details=details,
            )
        )


def _error_detail(error: BacktestEngineError) -> MarketDataErrorDetail:
    return MarketDataErrorDetail(
        code=type(error).__name__,
        message=error.message,
        details={key: str(value) for key, value in error.context.items()},
    )


def _dry_run_metadata(metadata: DryRunMetadata | None) -> MarketDataDryRunMetadata | None:
    if metadata is None:
        return None
    return MarketDataDryRunMetadata(
        provider_symbol=metadata.provider_symbol,
        supported_timeframes=metadata.supported_timeframes,
        window_mode=metadata.window_mode,
        requested_start_utc=metadata.requested_start_utc,
        requested_end_utc=metadata.requested_end_utc,
        calendar_id=metadata.calendar_id,
    )


def _validation_report(manifest: ValidationManifest | None) -> MarketDataValidationReport | None:
    if manifest is None:
        return None
    return MarketDataValidationReport(
        source_fingerprint=manifest.source_fingerprint,
        validator_ruleset_version=manifest.validator_ruleset_version,
        verification_verdict=manifest.verification_verdict,
        check_results=tuple(
            MarketDataValidationCheckDetail(
                check_code=item.check_code,
                check_label=item.check_label,
                check_status=item.check_status,
                score_pct=item.score_pct,
                affected_count=item.affected_count,
                checked_count=item.checked_count,
                issue_codes=item.issue_codes,
                sample_details=item.sample_details,
            )
            for item in manifest.check_results
        ),
        score_summary=(
            None
            if manifest.score_summary is None
            else MarketDataValidationScoreSummary(
                overall_score_pct=manifest.score_summary.overall_score_pct,
                applicable_check_count=manifest.score_summary.applicable_check_count,
                total_check_count=manifest.score_summary.total_check_count,
                warning_check_count=manifest.score_summary.warning_check_count,
                failed_check_count=manifest.score_summary.failed_check_count,
            )
        ),
        window_summary=(
            None
            if manifest.window_summary is None
            else MarketDataValidationWindowSummary(
                requested_start_utc=manifest.window_summary.requested_start_utc,
                requested_end_utc=manifest.window_summary.requested_end_utc,
                actual_start_utc=manifest.window_summary.actual_start_utc,
                actual_end_utc=manifest.window_summary.actual_end_utc,
                start_status=manifest.window_summary.start_status,
                end_status=manifest.window_summary.end_status,
            )
        ),
        warning_count=manifest.warning_count,
        failure_count=manifest.failure_count,
        verified_at_utc=manifest.verified_at_utc,
    )


__all__ = ["HistoricalDataProvider", "HistoricalDataVerifier", "HistoricalMarketDataService"]
