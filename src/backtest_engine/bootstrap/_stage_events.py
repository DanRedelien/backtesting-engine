"""Private stage-emission helpers for bootstrap orchestration."""

from __future__ import annotations

from backtest_engine.config.runtime import BacktestRunSpec
from backtest_engine.core.types import JsonObject
from backtest_engine.infrastructure.observability import DiagnosticsSink, StageDiagnosticEvent
from backtest_engine.infrastructure.observability.diagnostics import DiagnosticStatus


def emit_stage(
    diagnostics: DiagnosticsSink,
    *,
    stage: str,
    status: DiagnosticStatus,
    message: str,
    requested_by: str,
    run_id: str | None = None,
    correlation_id: str | None = None,
    run_kind: str | None = None,
    details: JsonObject | None = None,
) -> None:
    diagnostics.emit(
        StageDiagnosticEvent(
            stage=stage,
            status=status,
            message=message,
            requested_by=requested_by,
            run_id=run_id,
            correlation_id=correlation_id,
            run_kind=run_kind,
            details=details or {},
        )
    )


def run_details(run_spec: BacktestRunSpec) -> JsonObject:
    first_strategy = run_spec.strategies[0]
    return {
        "strategy_id": first_strategy.strategy.strategy_id,
        "symbol": first_strategy.legs[0].symbol,
        "leg_symbols": ",".join(leg.symbol for leg in first_strategy.legs),
    }


__all__ = ["emit_stage", "run_details"]
