"""Structured logging adapters for run-stage diagnostics."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from backtest_engine.infrastructure.observability.diagnostics import (
    DiagnosticStatus,
    DiagnosticsSink,
    StageDiagnosticEvent,
)


@dataclass(frozen=True)
class StructuredDiagnosticsLogger:
    """Emit structured diagnostics through Python's logging system."""

    logger: logging.Logger = field(default_factory=lambda: logging.getLogger("backtest_engine"))

    def emit(self, event: StageDiagnosticEvent) -> None:
        self.logger.log(
            _status_to_level(event.status),
            event.message,
            extra={
                "stage": event.stage,
                "status": event.status,
                "run_id": event.run_id,
                "correlation_id": event.correlation_id,
                "run_kind": event.run_kind,
                "requested_by": event.requested_by,
                "details": event.details,
            },
        )


def build_default_diagnostics_logger() -> DiagnosticsSink:
    """Build the default diagnostics sink used by the rewrite bootstrap."""

    return StructuredDiagnosticsLogger()


def _status_to_level(status: DiagnosticStatus) -> int:
    if status == "failed":
        return logging.ERROR
    return logging.INFO


__all__ = ["StructuredDiagnosticsLogger", "build_default_diagnostics_logger"]
