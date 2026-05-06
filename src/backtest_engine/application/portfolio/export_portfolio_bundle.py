"""Export a portfolio-run result bundle from runtime truth."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from backtest_engine.application._bundle_header import build_bundle_header_from_run_spec
from backtest_engine.application.portfolio.build_portfolio_plan import PortfolioBacktestPlan
from backtest_engine.config.runtime import BacktestRunSpec
from backtest_engine.domain.artifacts.bundles import ResultBundle
from backtest_engine.infrastructure.nautilus.portfolio_projection import PortfolioProjection
from backtest_engine.infrastructure.nautilus.runner import NautilusRunArtifacts

if TYPE_CHECKING:
    from backtest_engine.application.portfolio.run_portfolio_backtest import PortfolioRunCommand


def export_portfolio_bundle(
    command: PortfolioRunCommand,
    run_spec: BacktestRunSpec,
    artifacts: NautilusRunArtifacts,
    projection: PortfolioProjection,
    plan: PortfolioBacktestPlan,
    created_at_utc: datetime,
) -> ResultBundle:
    """Build a persisted portfolio bundle from runtime truth and projections."""

    header = build_bundle_header_from_run_spec(run_spec=run_spec, created_at_utc=created_at_utc)
    summary = {
        "requested_by": command.requested_by,
        "position_count": projection.position_count,
        "portfolio_scalar": plan.compiled_sizing.portfolio_scalar,
        "effective_weight_sum": plan.compiled_sizing.effective_weight_sum,
        **artifacts.metrics,
        **projection.summary,
    }
    artifact_locations = {
        "runtime_root": artifacts.runtime_root,
        **artifacts.report_locations,
        **projection.artifact_locations,
    }
    return ResultBundle(
        manifest=header.manifest,
        provenance=header.provenance,
        run_spec=run_spec,
        artifact_locations=artifact_locations,
        summary=summary,
    )


__all__ = ["export_portfolio_bundle"]
