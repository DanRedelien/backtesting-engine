"""Output rendering helpers for the market-data CLI."""

from __future__ import annotations

from typing import Mapping

from backtest_engine.application.market_data import (
    HistoricalMarketDataBatchResult,
    HistoricalMarketDataSliceResult,
    MarketDataVerificationSliceResult,
    MarketDataValidationReport,
    MarketDataValidationWindowSummary,
)
from backtest_engine.core.errors import BacktestEngineError


def print_verification_results(
    slice_results: tuple[MarketDataVerificationSliceResult, ...],
    *,
    detailed: bool,
) -> None:
    for index, slice_result in enumerate(slice_results):
        manifest = slice_result.validation_manifest
        if not detailed or manifest is None:
            print(format_verification_summary(slice_result))
        else:
            print_verification_slice(slice_result, manifest)
        if index != len(slice_results) - 1:
            print()


def print_verification_slice(
    slice_result: MarketDataVerificationSliceResult,
    manifest: MarketDataValidationReport,
) -> None:
    header = f"{slice_result.provider_id} {slice_result.canonical_symbol} {slice_result.timeframe}"
    header_window = format_window_header(manifest.window_summary)
    if header_window:
        header = f"{header} {header_window}"
    print(f"{header}: {manifest.verification_verdict}")
    if manifest.window_summary is not None:
        print(
            "Observed window: "
            f"{manifest.window_summary.actual_start_utc.isoformat()} .. "
            f"{manifest.window_summary.actual_end_utc.isoformat()} "
            f"(start={manifest.window_summary.start_status}, "
            f"end={manifest.window_summary.end_status})"
        )
    if slice_result.error is not None:
        print(f"Verification error: [{slice_result.error.code}] {slice_result.error.message}")
    for check_result in manifest.check_results:
        print(
            f"{check_result.check_label or check_result.check_code}: "
            f"{format_score_pct(check_result.score_pct)} {check_result.check_status}"
        )
        if check_result.check_status in {"WARN", "BAD"}:
            if check_result.affected_count is not None and check_result.checked_count is not None:
                print(f"  affected: {check_result.affected_count}/{check_result.checked_count}")
            if check_result.issue_codes:
                print(f"  issue_codes: {', '.join(check_result.issue_codes)}")
            for sample in check_result.sample_details:
                if sample:
                    print(f"  details: {format_detail_pairs(sample)}")
    if manifest.score_summary is not None:
        summary = manifest.score_summary
        print(
            "Overall score: "
            f"{format_score_pct(summary.overall_score_pct)} "
            f"(applicable={summary.applicable_check_count}/{summary.total_check_count}, "
            f"warn={summary.warning_check_count}, bad={summary.failed_check_count})"
        )
    if slice_result.validation_manifest_path is not None:
        print(f"Manifest: {slice_result.validation_manifest_path}")


def format_verification_summary(slice_result: MarketDataVerificationSliceResult) -> str:
    manifest = slice_result.validation_manifest
    if manifest is None:
        if slice_result.error is None:
            return (
                f"{slice_result.status.upper()} "
                f"{slice_result.provider_id} {slice_result.canonical_symbol} {slice_result.timeframe}"
            )
        return (
            f"{slice_result.status.upper()} "
            f"{slice_result.provider_id} {slice_result.canonical_symbol} {slice_result.timeframe} "
            f"error={slice_result.error.code} message={slice_result.error.message}"
        )
    summary = manifest.score_summary
    warning_count = summary.warning_check_count if summary is not None else manifest.warning_count
    failed_count = summary.failed_check_count if summary is not None else manifest.failure_count
    parts = [
        manifest.verification_verdict,
        slice_result.provider_id,
        slice_result.canonical_symbol,
        slice_result.timeframe,
        f"score={format_score_pct(summary.overall_score_pct if summary is not None else None)}",
        f"warn={warning_count}",
        f"bad={failed_count}",
    ]
    interesting = interesting_check_codes(manifest)
    if interesting:
        parts.append(f"checks={','.join(interesting)}")
    if slice_result.error is not None:
        parts.append(f"error={slice_result.error.code}")
    return " ".join(parts)


def print_batch_slices(
    slice_results: tuple[HistoricalMarketDataSliceResult | MarketDataVerificationSliceResult, ...],
) -> None:
    ok_results: list[HistoricalMarketDataSliceResult | MarketDataVerificationSliceResult] = []
    error_groups: dict[str, list[HistoricalMarketDataSliceResult | MarketDataVerificationSliceResult]] = {}
    for slice_result in slice_results:
        if slice_result.error is None:
            ok_results.append(slice_result)
        else:
            key = f"{slice_result.error.code}: {slice_result.error.message}"
            error_groups.setdefault(key, []).append(slice_result)
    for result in ok_results:
        print(f"{result.provider_id} {result.canonical_symbol} {result.timeframe}: {result.status}")
    for error_key, results in error_groups.items():
        slices_desc = ", ".join(f"{r.canonical_symbol}/{r.timeframe}" for r in results)
        print(f"FAILED [{len(results)}x] {error_key}")
        print(f"  slices: {slices_desc}")
        representative = results[0]
        if representative.error is not None and representative.error.details:
            for detail_key, detail_val in representative.error.details.items():
                print(f"  {detail_key}: {detail_val}")


def print_dry_run_details(result: HistoricalMarketDataBatchResult) -> None:
    for item in result.slice_results:
        if item.dry_run_metadata is None:
            continue
        meta = item.dry_run_metadata
        print(f"  provider_symbol: {meta.provider_symbol}")
        print(f"  supported_timeframes: {', '.join(meta.supported_timeframes)}")
        print(f"  window_mode: {meta.window_mode}")
        if meta.window_mode == "max_available":
            print(f"  requested_window: max_available .. {meta.requested_end_utc.isoformat()}")
        else:
            print(f"  requested_window: {meta.requested_start_utc.isoformat()} .. {meta.requested_end_utc.isoformat()}")
        if meta.calendar_id:
            print(f"  calendar_id: {meta.calendar_id}")
        print(f"  bars_path: {item.bars_path}")
        print(f"  source_manifest_path: {item.source_manifest_path}")


def print_cli_error(error: BacktestEngineError) -> None:
    usage = error.context.get("usage")
    if usage is not None:
        print(str(usage))
    argparse_message = error.context.get("argparse_message")
    if argparse_message is None:
        print(f"[{type(error).__name__}] {error.message}")
        return
    print(f"[{type(error).__name__}] {error.message}: {argparse_message}")


def format_window_header(window_summary: MarketDataValidationWindowSummary | None) -> str:
    if window_summary is None:
        return ""
    return (
        f"{window_summary.requested_start_utc.isoformat()} .. "
        f"{window_summary.requested_end_utc.isoformat()}"
    )


def format_score_pct(score_pct: float | None) -> str:
    if score_pct is None:
        return "N/A"
    return f"{score_pct:0.2f}%"


def format_detail_pairs(details: Mapping[str, object]) -> str:
    return ", ".join(f"{key}={value}" for key, value in details.items())


def interesting_check_codes(manifest: MarketDataValidationReport) -> tuple[str, ...]:
    failing = [result.check_code for result in manifest.check_results if result.check_status == "BAD"]
    warning = [result.check_code for result in manifest.check_results if result.check_status == "WARN"]
    ordered = failing + warning
    return tuple(ordered[:3])


__all__ = [
    "print_batch_slices",
    "print_cli_error",
    "print_dry_run_details",
    "print_verification_results",
]
