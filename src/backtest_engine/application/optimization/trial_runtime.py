"""Explicit trial runtime for ordered walk-forward fold execution."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import cast

from backtest_engine.application.optimization.trial_executor import TrialExecution, TrialExecutor
from backtest_engine.config.runtime import BacktestRunSpec
from backtest_engine.core.types import JsonObject, NonEmptyStr
from backtest_engine.infrastructure.observability import DiagnosticsSink, NullDiagnosticsSink
from backtest_engine.infrastructure.observability.diagnostics import DiagnosticStatus, StageDiagnosticEvent


@dataclass(frozen=True)
class CanonicalTrialRuntime:
    """Execute ordered fold sequences through the canonical trial executor."""

    executor: TrialExecutor
    max_parallel_trials: int = 1
    diagnostics: DiagnosticsSink = NullDiagnosticsSink()

    def execute_many(
        self,
        run_specs: tuple[BacktestRunSpec, ...],
        *,
        requested_by: NonEmptyStr,
        correlation_id: NonEmptyStr | None = None,
    ) -> tuple[TrialExecution, ...]:
        if not run_specs:
            return tuple()

        self._emit(
            stage="optimization.execute_many",
            status="started",
            message="starting canonical optimization trial runtime",
            requested_by=requested_by,
            correlation_id=correlation_id,
            details={
                "fold_count": len(run_specs),
                "max_parallel_trials": min(len(run_specs), self.max_parallel_trials),
            },
        )
        try:
            if self.max_parallel_trials == 1 or len(run_specs) == 1:
                executions = tuple(
                    self._execute_one(
                        index=index,
                        run_spec=run_spec,
                        requested_by=requested_by,
                        correlation_id=correlation_id,
                    )[1]
                    for index, run_spec in enumerate(run_specs)
                )
            else:
                executions = self._execute_parallel(
                    run_specs=run_specs,
                    requested_by=requested_by,
                    correlation_id=correlation_id,
                )
        except Exception as exc:
            self._emit(
                stage="optimization.execute_many",
                status="failed",
                message="optimization trial runtime failed",
                requested_by=requested_by,
                correlation_id=correlation_id,
                details={"error_type": type(exc).__name__},
            )
            raise

        self._emit(
            stage="optimization.execute_many",
            status="succeeded",
            message="finished canonical optimization trial runtime",
            requested_by=requested_by,
            correlation_id=correlation_id,
            details={"fold_count": len(executions)},
        )
        return executions

    def _execute_parallel(
        self,
        *,
        run_specs: tuple[BacktestRunSpec, ...],
        requested_by: NonEmptyStr,
        correlation_id: NonEmptyStr | None,
    ) -> tuple[TrialExecution, ...]:
        results: list[TrialExecution | None] = [None] * len(run_specs)
        with ThreadPoolExecutor(
            max_workers=min(self.max_parallel_trials, len(run_specs)),
            thread_name_prefix="bte-trial",
        ) as pool:
            futures = [
                pool.submit(
                    self._execute_one,
                    index,
                    run_spec,
                    requested_by,
                    correlation_id,
                )
                for index, run_spec in enumerate(run_specs)
            ]
            for future in futures:
                index, execution = future.result()
                results[index] = execution
        return tuple(cast(list[TrialExecution], results))

    def _execute_one(
        self,
        index: int,
        run_spec: BacktestRunSpec,
        requested_by: NonEmptyStr,
        correlation_id: NonEmptyStr | None,
    ) -> tuple[int, TrialExecution]:
        self._emit(
            stage="optimization.fold.execute",
            status="started",
            message="starting canonical optimization fold",
            requested_by=requested_by,
            run_id=run_spec.run_id,
            correlation_id=correlation_id,
            run_kind=run_spec.run_kind.value,
            details=self._fold_details(index=index, run_spec=run_spec),
        )
        try:
            execution = self.executor.execute(
                run_spec,
                requested_by=requested_by,
                correlation_id=correlation_id,
            )
        except Exception as exc:
            self._emit(
                stage="optimization.fold.execute",
                status="failed",
                message="canonical optimization fold failed",
                requested_by=requested_by,
                run_id=run_spec.run_id,
                correlation_id=correlation_id,
                run_kind=run_spec.run_kind.value,
                details={
                    **self._fold_details(index=index, run_spec=run_spec),
                    "error_type": type(exc).__name__,
                },
            )
            raise

        self._emit(
            stage="optimization.fold.execute",
            status="succeeded",
            message="finished canonical optimization fold",
            requested_by=requested_by,
            run_id=run_spec.run_id,
            correlation_id=correlation_id,
            run_kind=run_spec.run_kind.value,
            details={
                **self._fold_details(index=index, run_spec=run_spec),
                "bundle_uri": execution.bundle_uri,
            },
        )
        return index, execution

    def _emit(
        self,
        *,
        stage: NonEmptyStr,
        status: DiagnosticStatus,
        message: NonEmptyStr,
        requested_by: NonEmptyStr,
        run_id: NonEmptyStr | None = None,
        correlation_id: NonEmptyStr | None = None,
        run_kind: NonEmptyStr | None = None,
        details: JsonObject | None = None,
    ) -> None:
        self.diagnostics.emit(
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

    def _fold_details(self, index: int, run_spec: BacktestRunSpec) -> JsonObject:
        first_strategy = run_spec.strategies[0]
        return {
            "fold_index": index,
            "strategy_id": first_strategy.strategy.strategy_id,
            "symbol": first_strategy.legs[0].symbol,
            "leg_symbols": ",".join(leg.symbol for leg in first_strategy.legs),
        }


__all__ = ["CanonicalTrialRuntime"]
