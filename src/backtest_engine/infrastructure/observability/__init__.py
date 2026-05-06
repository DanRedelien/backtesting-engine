"""Infrastructure-owned observability adapters for the rewrite."""

from backtest_engine.infrastructure.observability.diagnostics import (
    DiagnosticStatus,
    DiagnosticsSink,
    InMemoryDiagnosticsSink,
    NullDiagnosticsSink,
    StageDiagnosticEvent,
)
from backtest_engine.infrastructure.observability.logging import (
    StructuredDiagnosticsLogger,
    build_default_diagnostics_logger,
)

__all__ = [
    "DiagnosticStatus",
    "DiagnosticsSink",
    "InMemoryDiagnosticsSink",
    "NullDiagnosticsSink",
    "StageDiagnosticEvent",
    "StructuredDiagnosticsLogger",
    "build_default_diagnostics_logger",
]
