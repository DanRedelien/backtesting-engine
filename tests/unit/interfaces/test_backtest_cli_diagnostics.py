from __future__ import annotations

from io import StringIO

from backtest_engine.infrastructure.observability import StageDiagnosticEvent
from backtest_engine.interfaces.cli.backtest.diagnostics import TerminalBacktestDiagnosticsSink


def test_backtest_diagnostics_sink_renders_dry_run_started_succeeded_and_failed() -> None:
    stream = StringIO()
    sink = TerminalBacktestDiagnosticsSink(stream=stream)

    sink.emit(
        StageDiagnosticEvent(
            stage="backtest.dry_run",
            status="started",
            message="starting dry-run",
            requested_by="cli",
            run_id="run-001",
            run_kind="single",
        )
    )
    sink.emit(
        StageDiagnosticEvent(
            stage="backtest.dry_run",
            status="succeeded",
            message="finished dry-run",
            requested_by="cli",
            run_id="run-001",
            run_kind="single",
            details={"data_count": 2},
        )
    )
    sink.emit(
        StageDiagnosticEvent(
            stage="backtest.dry_run",
            status="failed",
            message="dry-run failed",
            requested_by="cli",
            run_id="run-001",
            run_kind="single",
            details={"error_type": "InfrastructureError"},
        )
    )

    assert stream.getvalue().splitlines() == [
        "STARTED backtest.dry_run",
        "run_kind: single",
        "run_id: run-001",
        "diagnostic: starting dry-run",
        "DONE backtest.dry_run",
        "run_kind: single",
        "run_id: run-001",
        "diagnostic: finished dry-run",
        "data_count: 2",
        "FAILED backtest.dry_run",
        "run_kind: single",
        "run_id: run-001",
        "diagnostic: dry-run failed",
        "error_type: InfrastructureError",
    ]
