"""Canonical portfolio-run use-case."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from backtest_engine.application.portfolio.build_portfolio_plan import (
    build_portfolio_plan,
)
from backtest_engine.application.portfolio.export_portfolio_bundle import export_portfolio_bundle
from backtest_engine.config.runtime import BacktestRunSpec
from backtest_engine.core.enums import RunKind
from backtest_engine.core.errors import ApplicationError
from backtest_engine.core.protocols import Clock
from backtest_engine.core.types import NonEmptyStr
from backtest_engine.infrastructure.artifacts.artifact_store import ArtifactStore
from backtest_engine.infrastructure.nautilus.portfolio_projection import PortfolioProjector
from backtest_engine.infrastructure.nautilus.runner import NautilusRunner


class PortfolioRunCommand(BaseModel):
    """A request wrapper for the portfolio use-case."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    requested_by: NonEmptyStr = "operator"
    correlation_id: NonEmptyStr | None = None


class PortfolioRunResult(BaseModel):
    """The outcome of a portfolio backtest request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: NonEmptyStr
    bundle_id: NonEmptyStr
    bundle_uri: NonEmptyStr
    runtime_root: NonEmptyStr
    allocation_count: int
    position_count: int
    metric_values: dict[str, float]


@dataclass(frozen=True)
class PortfolioRunDependencies:
    """Explicit dependencies for the portfolio use-case."""

    runner: NautilusRunner
    projector: PortfolioProjector
    artifact_store: ArtifactStore
    clock: Clock


def run_portfolio_backtest(
    command: PortfolioRunCommand,
    run_spec: BacktestRunSpec,
    dependencies: PortfolioRunDependencies,
) -> PortfolioRunResult:
    """Execute one portfolio backtest through the canonical Nautilus boundary."""

    if run_spec.run_kind is not RunKind.PORTFOLIO:
        raise ApplicationError(
            "run_portfolio_backtest requires a portfolio BacktestRunSpec",
            run_kind=run_spec.run_kind,
        )
    if run_spec.portfolio_policy is None:
        raise ApplicationError("run_portfolio_backtest requires portfolio_policy")

    plan = build_portfolio_plan(
        strategy_specs=run_spec.strategies,
        policy=run_spec.portfolio_policy,
    )
    artifacts = dependencies.runner.run(run_spec)
    projection = dependencies.projector.project(run_spec=run_spec, artifacts=artifacts)
    bundle = export_portfolio_bundle(
        command=command,
        run_spec=run_spec,
        artifacts=artifacts,
        projection=projection,
        plan=plan,
        created_at_utc=dependencies.clock.now_utc(),
    )
    saved_bundle = dependencies.artifact_store.save_bundle(bundle)
    return PortfolioRunResult(
        run_id=run_spec.run_id,
        bundle_id=saved_bundle.bundle_id,
        bundle_uri=saved_bundle.bundle_uri,
        runtime_root=artifacts.runtime_root,
        allocation_count=len(plan.allocation_plan.targets),
        position_count=projection.position_count,
        metric_values=bundle.metric_values,
    )


__all__ = [
    "PortfolioRunCommand",
    "PortfolioRunDependencies",
    "PortfolioRunResult",
    "run_portfolio_backtest",
]
