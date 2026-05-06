"""Private executor wrappers for canonical bootstrap wiring."""

from __future__ import annotations

from backtest_engine.application.portfolio.run_portfolio_backtest import (
    PortfolioRunCommand,
    PortfolioRunDependencies,
    PortfolioRunResult,
    run_portfolio_backtest,
)
from backtest_engine.application.single.run_single_backtest import (
    SingleRunCommand,
    SingleRunDependencies,
    SingleRunResult,
    run_single_backtest,
)
from backtest_engine.bootstrap._stage_events import emit_stage, run_details
from backtest_engine.config.runtime import BacktestRunSpec
from backtest_engine.infrastructure.observability import DiagnosticsSink


class _SingleExecutor:
    def __init__(
        self,
        dependencies: SingleRunDependencies,
        diagnostics: DiagnosticsSink,
    ) -> None:
        self._dependencies = dependencies
        self._diagnostics = diagnostics

    def run(self, command: SingleRunCommand, run_spec: BacktestRunSpec) -> SingleRunResult:
        emit_stage(
            self._diagnostics,
            stage="single.run",
            status="started",
            message="starting canonical single backtest",
            requested_by=command.requested_by,
            run_id=run_spec.run_id,
            correlation_id=command.correlation_id,
            run_kind=run_spec.run_kind.value,
            details=run_details(run_spec),
        )
        try:
            result = run_single_backtest(
                command=command,
                run_spec=run_spec,
                dependencies=self._dependencies,
            )
        except Exception as exc:
            emit_stage(
                self._diagnostics,
                stage="single.run",
                status="failed",
                message="canonical single backtest failed",
                requested_by=command.requested_by,
                run_id=run_spec.run_id,
                correlation_id=command.correlation_id,
                run_kind=run_spec.run_kind.value,
                details={**run_details(run_spec), "error_type": type(exc).__name__},
            )
            raise

        emit_stage(
            self._diagnostics,
            stage="single.run",
            status="succeeded",
            message="finished canonical single backtest",
            requested_by=command.requested_by,
            run_id=run_spec.run_id,
            correlation_id=command.correlation_id,
            run_kind=run_spec.run_kind.value,
            details={**run_details(run_spec), "bundle_uri": result.bundle_uri},
        )
        return result


class _PortfolioExecutor:
    def __init__(
        self,
        dependencies: PortfolioRunDependencies,
        diagnostics: DiagnosticsSink,
    ) -> None:
        self._dependencies = dependencies
        self._diagnostics = diagnostics

    def run(self, command: PortfolioRunCommand, run_spec: BacktestRunSpec) -> PortfolioRunResult:
        rebalance_cadence = (
            run_spec.portfolio_policy.rebalance_cadence if run_spec.portfolio_policy else ""
        )
        emit_stage(
            self._diagnostics,
            stage="portfolio.run",
            status="started",
            message="starting canonical portfolio backtest",
            requested_by=command.requested_by,
            run_id=run_spec.run_id,
            correlation_id=command.correlation_id,
            run_kind=run_spec.run_kind.value,
            details={**run_details(run_spec), "rebalance_cadence": rebalance_cadence},
        )
        try:
            result = run_portfolio_backtest(
                command=command,
                run_spec=run_spec,
                dependencies=self._dependencies,
            )
        except Exception as exc:
            emit_stage(
                self._diagnostics,
                stage="portfolio.run",
                status="failed",
                message="canonical portfolio backtest failed",
                requested_by=command.requested_by,
                run_id=run_spec.run_id,
                correlation_id=command.correlation_id,
                run_kind=run_spec.run_kind.value,
                details={
                    **run_details(run_spec),
                    "rebalance_cadence": rebalance_cadence,
                    "error_type": type(exc).__name__,
                },
            )
            raise

        emit_stage(
            self._diagnostics,
            stage="portfolio.run",
            status="succeeded",
            message="finished canonical portfolio backtest",
            requested_by=command.requested_by,
            run_id=run_spec.run_id,
            correlation_id=command.correlation_id,
            run_kind=run_spec.run_kind.value,
            details={
                **run_details(run_spec),
                "rebalance_cadence": rebalance_cadence,
                "bundle_uri": result.bundle_uri,
            },
        )
        return result


__all__ = ["_PortfolioExecutor", "_SingleExecutor"]
