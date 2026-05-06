"""Pure scenario mutation helpers."""

from __future__ import annotations

from backtest_engine.config.runtime import BacktestRunSpec
from backtest_engine.core.enums import RunKind
from backtest_engine.core.errors import ApplicationError
from backtest_engine.core.types import NonEmptyStr


def mutate_portfolio_config(run_spec: BacktestRunSpec, scenario_name: NonEmptyStr) -> BacktestRunSpec:
    """Tag a run spec with one scenario identifier."""

    if run_spec.run_kind is not RunKind.PORTFOLIO:
        raise ApplicationError(
            "scenario mutation requires a portfolio BacktestRunSpec",
            run_kind=run_spec.run_kind,
        )

    return run_spec.model_copy(update={"tags": run_spec.tags + (scenario_name,)})


__all__ = ["mutate_portfolio_config"]
