"""Terminal diagnostics sink for the market-data CLI."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from time import perf_counter
from typing import Mapping, TextIO

from backtest_engine.core.types import JsonValue
from backtest_engine.infrastructure.observability import StageDiagnosticEvent
from backtest_engine.interfaces.cli.market_data.progress_output import (
    CompletedSliceDurationSample,
    estimate_batch_remaining_sec,
    format_progress_date,
    format_progress_line,
    format_total_duration,
    select_frontier_date_utc,
)


@dataclass
class SliceTelemetryState:
    started_at_monotonic: float | None = None
    last_progress_pct: float = -1.0
    last_progress_emit_monotonic: float = 0.0
    last_row_count: int = -1
    last_frontier_date_label: str = "--"
    completed: bool = False
    duration_sec: float | None = None
    completed_status: str = ""
    progress_seen: bool = False
    duration_eligible_for_eta: bool = False
    last_elapsed_sec: float = 0.0
    last_eta_sec: float | None = None


@dataclass
class BufferedError:
    provider_id: str
    canonical_symbol: str
    timeframe: str
    error_type: str
    error_message: str
    error_context: dict[str, str]


@dataclass
class TerminalMarketDataDiagnosticsSink:
    """Render market-data download progress to one terminal stream."""

    stream: TextIO = field(default_factory=lambda: sys.stdout)
    total_slices: int = 0
    slice_states: dict[str, SliceTelemetryState] = field(default_factory=dict)
    batch_started_at_monotonic: float | None = None
    last_visible_batch_left_sec: float | None = None
    buffered_errors: list[BufferedError] = field(default_factory=list)

    def emit(self, event: StageDiagnosticEvent) -> None:
        if not event.stage.startswith("market_data."):
            return
        if event.stage == "market_data.batch.download":
            self._handle_batch_event(event)
            return
        if event.stage == "market_data.slice.download":
            self._handle_slice_event(event)
            return
        if event.stage == "market_data.slice.download.progress":
            self._handle_progress_event(event)

    def _handle_batch_event(self, event: StageDiagnosticEvent) -> None:
        if event.status == "started":
            self.total_slices = detail_int(event.details, "total_slices")
            self.batch_started_at_monotonic = perf_counter()
            self.last_visible_batch_left_sec = None
            self.slice_states.clear()
            self.buffered_errors.clear()
            return

        self._flush_buffered_errors()
        completed = detail_int(event.details, "completed_slices")
        failed = detail_int(event.details, "failed_slices")
        succeeded = max(completed - failed, 0)
        status = "FAILED" if event.status == "failed" else "DONE"
        total_duration = None
        if self.batch_started_at_monotonic is not None:
            total_duration = max(0.0, perf_counter() - self.batch_started_at_monotonic)
        self._write(
            f"{status} batch {completed}/{self.total_slices or completed} slices "
            f"(ok={succeeded}, failed={failed}) total={format_total_duration(total_duration)}"
        )

    def _handle_slice_event(self, event: StageDiagnosticEvent) -> None:
        key = slice_key(event.details)
        state = self.slice_states.setdefault(key, SliceTelemetryState())
        canonical_symbol = detail_str(event.details, "canonical_symbol")
        timeframe = detail_str(event.details, "timeframe")
        provider_id = detail_str(event.details, "provider_id")
        if event.status == "started":
            state.started_at_monotonic = perf_counter()
            state.completed = False
            state.completed_status = ""
            state.progress_seen = False
            state.duration_eligible_for_eta = False
            state.last_progress_pct = -1.0
            state.last_progress_emit_monotonic = 0.0
            state.last_row_count = -1
            state.last_frontier_date_label = "--"
            state.last_elapsed_sec = 0.0
            state.last_eta_sec = None
            return

        state.completed = True
        if state.started_at_monotonic is not None:
            state.duration_sec = max(0.0, perf_counter() - state.started_at_monotonic)
        slice_status = detail_str(event.details, "slice_status", default=event.status)
        state.completed_status = slice_status
        state.duration_eligible_for_eta = (
            state.progress_seen
            and state.duration_sec is not None
            and state.duration_sec > 0.0
            and slice_status not in {"failed", "dry_run", "skipped", "skipped_verified"}
        )
        completed_slices = detail_int(event.details, "completed_slices")
        total_slices = detail_int(event.details, "total_slices", default=self.total_slices)
        if event.status == "failed":
            error_type = detail_str(event.details, "error_type")
            error_message = detail_str(event.details, "error_message")
            raw_ctx = event.details.get("error_context")
            if isinstance(raw_ctx, str):
                try:
                    parsed = json.loads(raw_ctx)
                except json.JSONDecodeError:
                    error_context = {}
                else:
                    error_context = (
                        {str(k): str(v) for k, v in parsed.items()}
                        if isinstance(parsed, dict)
                        else {}
                    )
            elif isinstance(raw_ctx, dict):
                error_context = {str(k): str(v) for k, v in raw_ctx.items()}
            else:
                error_context = {}
            self.buffered_errors.append(
                BufferedError(
                    provider_id=provider_id,
                    canonical_symbol=canonical_symbol,
                    timeframe=timeframe,
                    error_type=error_type,
                    error_message=error_message,
                    error_context=error_context,
                )
            )
            self._write(
                f"QUEUED-ERROR {provider_id} {canonical_symbol} {timeframe} "
                f"{completed_slices}/{total_slices}"
            )
            return

        duration = "" if state.duration_sec is None else f" {format_total_duration(state.duration_sec)}"
        self._write(
            f"OK {provider_id} {canonical_symbol} {timeframe} {slice_status} "
            f"{completed_slices}/{total_slices}{duration}"
        )

    def _handle_progress_event(self, event: StageDiagnosticEvent) -> None:
        key = slice_key(event.details)
        state = self.slice_states.setdefault(key, SliceTelemetryState())
        progress_pct = detail_float(event.details, "progress_pct")
        row_count = detail_int(event.details, "row_count")
        canonical_symbol = detail_str(event.details, "canonical_symbol")
        timeframe = detail_str(event.details, "timeframe")
        provider_id = detail_str(event.details, "provider_id")
        elapsed_sec = detail_float(event.details, "elapsed_sec")
        raw_eta_sec = detail_optional_float(event.details, "eta_sec")
        display_eta_sec = normalize_eta_for_display(
            progress_pct=progress_pct,
            elapsed_sec=elapsed_sec,
            eta_sec=raw_eta_sec,
        )
        frontier_date_utc = select_frontier_date_utc(
            requested_start_utc=detail_optional_datetime(event.details, "requested_start_utc"),
            requested_end_utc=detail_optional_datetime(event.details, "requested_end_utc"),
            actual_start_utc=detail_optional_datetime(event.details, "actual_start_utc"),
            actual_end_utc=detail_optional_datetime(event.details, "actual_end_utc"),
        )
        frontier_date_label = format_progress_date(frontier_date_utc)
        state.last_elapsed_sec = elapsed_sec
        state.last_eta_sec = display_eta_sec
        state.progress_seen = True
        now = perf_counter()
        should_print = (
            state.last_progress_pct < 0.0
            or progress_pct >= state.last_progress_pct + 1.0
            or now - state.last_progress_emit_monotonic >= 5.0
            or frontier_date_label != state.last_frontier_date_label
        )
        batch_left_sec = self._estimate_batch_left_sec(current_key=key, current_eta_sec=display_eta_sec)
        if batch_left_sec is not None:
            self.last_visible_batch_left_sec = batch_left_sec
        display_left_sec = batch_left_sec if batch_left_sec is not None else self.last_visible_batch_left_sec
        if not should_print:
            return

        state.last_progress_pct = progress_pct
        state.last_row_count = row_count
        state.last_frontier_date_label = frontier_date_label
        state.last_progress_emit_monotonic = now
        progress_line = format_progress_line(
            provider_id=provider_id,
            canonical_symbol=canonical_symbol,
            timeframe=timeframe,
            progress_pct=progress_pct,
            row_count=row_count,
            frontier_date_utc=frontier_date_utc,
            left_sec=display_left_sec,
        )
        self._write(progress_line)

    def _flush_buffered_errors(self) -> None:
        if not self.buffered_errors:
            return
        groups: dict[str, list[BufferedError]] = {}
        for err in self.buffered_errors:
            key = f"{err.error_type}: {err.error_message}"
            groups.setdefault(key, []).append(err)
        for error_key, errors in groups.items():
            slices_desc = ", ".join(f"{e.canonical_symbol}/{e.timeframe}" for e in errors)
            self._write(f"ERR [{len(errors)}x] {error_key}")
            self._write(f"  slices: {slices_desc}")
            representative = errors[0]
            if representative.error_context:
                for ctx_key, ctx_val in representative.error_context.items():
                    self._write(f"  {ctx_key}: {ctx_val}")
        self.buffered_errors.clear()

    def _estimate_batch_left_sec(self, *, current_key: str, current_eta_sec: float | None) -> float | None:
        completed_count = sum(1 for state in self.slice_states.values() if state.completed)
        current_state = self.slice_states.get(current_key)
        current_total_estimate_sec = None
        if current_state is not None and current_eta_sec is not None:
            current_total_estimate_sec = current_state.last_elapsed_sec + current_eta_sec
        completed_slice_samples = [
            CompletedSliceDurationSample(duration_sec=state.duration_sec)
            for key, state in self.slice_states.items()
            if key != current_key
            and state.completed
            and state.duration_sec is not None
            and state.duration_eligible_for_eta
        ]
        return estimate_batch_remaining_sec(
            total_slices=self.total_slices,
            completed_count=completed_count,
            current_eta_sec=current_eta_sec,
            current_total_estimate_sec=current_total_estimate_sec,
            completed_slice_samples=completed_slice_samples,
        )

    def _write(self, line: str) -> None:
        print(line, file=self.stream, flush=True)


def slice_key(details: Mapping[str, JsonValue]) -> str:
    provider_id = detail_str(details, "provider_id")
    canonical_symbol = detail_str(details, "canonical_symbol")
    timeframe = detail_str(details, "timeframe")
    return f"{provider_id}|{canonical_symbol}|{timeframe}"


def normalize_eta_for_display(
    *,
    progress_pct: float,
    elapsed_sec: float,
    eta_sec: float | None,
) -> float | None:
    if eta_sec is None:
        return None
    if elapsed_sec < 5.0:
        return None
    if progress_pct < 8.0:
        return None
    if eta_sec < 1.0 and progress_pct < 99.9:
        return None
    return eta_sec


def detail_str(
    details: Mapping[str, JsonValue],
    key: str,
    *,
    default: str = "?",
) -> str:
    value = details.get(key)
    if isinstance(value, (list, dict)) or value is None:
        return default
    return str(value)


def detail_int(
    details: Mapping[str, JsonValue],
    key: str,
    *,
    default: int = 0,
) -> int:
    value = details.get(key)
    if isinstance(value, (list, dict)) or value is None:
        return default
    return int(value)


def detail_float(
    details: Mapping[str, JsonValue],
    key: str,
    *,
    default: float = 0.0,
) -> float:
    value = details.get(key)
    if isinstance(value, (list, dict)) or value is None:
        return default
    return float(value)


def detail_optional_float(
    details: Mapping[str, JsonValue],
    key: str,
) -> float | None:
    value = details.get(key)
    if isinstance(value, (list, dict)) or value is None:
        return None
    return float(value)


def detail_optional_datetime(
    details: Mapping[str, JsonValue],
    key: str,
) -> datetime | None:
    value = details.get(key)
    if value is None or isinstance(value, (list, dict)):
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


__all__ = [
    "TerminalMarketDataDiagnosticsSink",
    "normalize_eta_for_display",
]
