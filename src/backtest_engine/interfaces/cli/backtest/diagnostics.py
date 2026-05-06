"""Terminal diagnostics sink for the runnable backtest CLI."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import TextIO

from backtest_engine.infrastructure.observability import StageDiagnosticEvent


@dataclass
class TerminalBacktestDiagnosticsSink:
    """Render backtest dry-run and failed execution diagnostics to a terminal stream."""

    stream: TextIO = field(default_factory=lambda: sys.stdout)

    def emit(self, event: StageDiagnosticEvent) -> None:
        if event.stage == "backtest.dry_run":
            self._render_dry_run_event(event)
            return
        if event.stage not in {"single.run", "portfolio.run"} or event.status != "failed":
            return

        self._write_status_block("FAILED", event)

    def _render_dry_run_event(self, event: StageDiagnosticEvent) -> None:
        status_label = {
            "started": "STARTED",
            "succeeded": "DONE",
            "failed": "FAILED",
        }[event.status]
        self._write_status_block(status_label, event)
        if event.status == "succeeded" and "data_count" in event.details:
            print(f"data_count: {event.details['data_count']}", file=self.stream, flush=True)
        if event.status == "failed" and "error_type" in event.details:
            print(f"error_type: {event.details['error_type']}", file=self.stream, flush=True)

    def _write_status_block(self, status_label: str, event: StageDiagnosticEvent) -> None:
        run_kind = event.run_kind or "backtest"
        run_id = event.run_id or "unknown"
        print(f"{status_label} {event.stage}", file=self.stream, flush=True)
        print(f"run_kind: {run_kind}", file=self.stream, flush=True)
        print(f"run_id: {run_id}", file=self.stream, flush=True)
        print(f"diagnostic: {event.message}", file=self.stream, flush=True)


__all__ = ["TerminalBacktestDiagnosticsSink"]
