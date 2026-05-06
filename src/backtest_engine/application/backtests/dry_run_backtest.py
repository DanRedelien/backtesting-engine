"""Dry-run preparation for canonical backtest run specs."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from backtest_engine.config.runtime import BacktestRunSpec
from backtest_engine.core.enums import RunKind
from backtest_engine.core.types import NonEmptyStr
from backtest_engine.infrastructure.nautilus.run_spec_compiler import NautilusRunSpecCompiler


class BacktestDryRunCommand(BaseModel):
    """A request wrapper for preparing one backtest without executing it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    requested_by: NonEmptyStr = "cli"
    correlation_id: NonEmptyStr | None = None


class BacktestDryRunResult(BaseModel):
    """The prepared runtime surface for one backtest dry-run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: NonEmptyStr
    run_kind: RunKind
    dataset_id: NonEmptyStr
    runtime_root: NonEmptyStr
    artifact_root: NonEmptyStr
    catalog_root: NonEmptyStr
    venue_names: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)
    data_count: int
    instrument_ids: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)
    bar_types: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)
    strategy_ids: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)


@dataclass(frozen=True)
class BacktestDryRunDependencies:
    """Dependencies needed to prepare a backtest dry-run."""

    compiler: NautilusRunSpecCompiler


def dry_run_backtest(
    command: BacktestDryRunCommand,
    run_spec: BacktestRunSpec,
    dependencies: BacktestDryRunDependencies,
) -> BacktestDryRunResult:
    """Compile one run spec without creating a Nautilus node or saving bundles."""

    del command
    compiled = dependencies.compiler.compile(run_spec)
    return BacktestDryRunResult(
        run_id=compiled.run_id,
        run_kind=run_spec.run_kind,
        dataset_id=compiled.dataset_id,
        runtime_root=compiled.runtime_root.as_posix(),
        artifact_root=compiled.artifact_root.as_posix(),
        catalog_root=compiled.catalog.catalog_root.as_posix(),
        venue_names=tuple(sorted({venue.name for venue in compiled.venues})),
        data_count=len(compiled.data),
        instrument_ids=tuple(sorted({data.instrument_id for data in compiled.data})),
        bar_types=tuple(sorted({data.bar_type for data in compiled.data})),
        strategy_ids=compiled.strategy_ids,
    )


__all__ = [
    "BacktestDryRunCommand",
    "BacktestDryRunDependencies",
    "BacktestDryRunResult",
    "dry_run_backtest",
]
