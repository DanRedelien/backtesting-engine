"""Canonical single-run use-case."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from backtest_engine.application.single.export_single_bundle import export_single_bundle
from backtest_engine.config.runtime import BacktestRunSpec
from backtest_engine.core.enums import RunKind
from backtest_engine.core.errors import ApplicationError
from backtest_engine.core.protocols import Clock
from backtest_engine.core.types import NonEmptyStr
from backtest_engine.infrastructure.artifacts.artifact_store import ArtifactStore
from backtest_engine.infrastructure.nautilus.runner import NautilusRunner


class SingleRunCommand(BaseModel):
    """A request wrapper for the single backtest use-case."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    requested_by: NonEmptyStr = "operator"
    correlation_id: NonEmptyStr | None = None
    bundle_label: NonEmptyStr | None = None


class SingleRunResult(BaseModel):
    """The outcome of a single backtest request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: NonEmptyStr
    bundle_id: NonEmptyStr
    bundle_uri: NonEmptyStr
    runtime_root: NonEmptyStr
    metric_values: dict[str, float]


@dataclass(frozen=True)
class SingleRunDependencies:
    """Explicit dependencies for the single-run use-case."""

    runner: NautilusRunner
    artifact_store: ArtifactStore
    clock: Clock


def run_single_backtest(
    command: SingleRunCommand,
    run_spec: BacktestRunSpec,
    dependencies: SingleRunDependencies,
) -> SingleRunResult:
    """Execute one single backtest through the canonical Nautilus boundary."""

    if run_spec.run_kind is not RunKind.SINGLE:
        raise ApplicationError(
            "run_single_backtest requires a single BacktestRunSpec",
            run_kind=run_spec.run_kind,
        )

    artifacts = dependencies.runner.run(run_spec)
    bundle = export_single_bundle(
        command=command,
        run_spec=run_spec,
        artifacts=artifacts,
        created_at_utc=dependencies.clock.now_utc(),
    )
    saved_bundle = dependencies.artifact_store.save_bundle(bundle)
    return SingleRunResult(
        run_id=run_spec.run_id,
        bundle_id=saved_bundle.bundle_id,
        bundle_uri=saved_bundle.bundle_uri,
        runtime_root=artifacts.runtime_root,
        metric_values=bundle.metric_values,
    )


__all__ = [
    "SingleRunCommand",
    "SingleRunDependencies",
    "SingleRunResult",
    "run_single_backtest",
]
