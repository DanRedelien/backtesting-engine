# mypy: disable-error-code=no-untyped-def
from __future__ import annotations

import logging

from backtest_engine.infrastructure.observability import (
    StageDiagnosticEvent,
    StructuredDiagnosticsLogger,
)


def test_structured_diagnostics_logger_emits_stage_fields(caplog) -> None:
    logger = logging.getLogger("backtest_engine.tests.observability")
    sink = StructuredDiagnosticsLogger(logger=logger)

    with caplog.at_level(logging.INFO, logger=logger.name):
        sink.emit(
            StageDiagnosticEvent(
                stage="walk_forward.run",
                status="started",
                message="starting canonical walk-forward job",
                requested_by="cli",
                run_id="run-123",
                correlation_id="corr-123",
                run_kind="single",
                details={"fold_count": 2},
            )
        )

    record = caplog.records[0]
    assert record.stage == "walk_forward.run"
    assert record.status == "started"
    assert record.run_id == "run-123"
    assert record.correlation_id == "corr-123"
    assert record.run_kind == "single"
    assert record.requested_by == "cli"
    assert record.details == {"fold_count": 2}
