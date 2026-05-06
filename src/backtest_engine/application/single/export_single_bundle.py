"""Export a single-run result bundle from runtime truth."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from backtest_engine.application._bundle_header import build_bundle_header_from_run_spec
from backtest_engine.config.runtime import BacktestRunSpec
from backtest_engine.domain.artifacts.bundles import ResultBundle
from backtest_engine.infrastructure.nautilus.runner import NautilusRunArtifacts

if TYPE_CHECKING:
    from backtest_engine.application.single.run_single_backtest import SingleRunCommand


def export_single_bundle(
    command: SingleRunCommand,
    run_spec: BacktestRunSpec,
    artifacts: NautilusRunArtifacts,
    created_at_utc: datetime,
) -> ResultBundle:
    """Build a persisted result bundle for a single backtest."""

    header = build_bundle_header_from_run_spec(run_spec=run_spec, created_at_utc=created_at_utc)
    summary = {"requested_by": command.requested_by, **artifacts.metrics}
    artifact_locations = {"runtime_root": artifacts.runtime_root, **artifacts.report_locations}
    return ResultBundle(
        manifest=header.manifest,
        provenance=header.provenance,
        run_spec=run_spec,
        artifact_locations=artifact_locations,
        summary=summary,
    )


__all__ = ["export_single_bundle"]
