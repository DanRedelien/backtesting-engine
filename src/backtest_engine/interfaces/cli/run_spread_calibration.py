"""CLI adapter for offline spread calibration publication."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, field_validator

from backtest_engine.application.calibration import (
    SpreadCalibrationCommand,
    SpreadCalibrationPublicationCommand,
    SpreadCalibrationPublicationResult,
    build_spread_calibration_panel,
    publish_spread_calibration,
)
from backtest_engine.config.runtime import BacktestRunSpec
from backtest_engine.core.timeframes import normalize_timeframe
from backtest_engine.core.types import NonEmptyStr
from backtest_engine.domain.market.datasets import DatasetSpec


class SpreadCalibrationCliCommand(BaseModel):
    """A CLI request to build and publish one offline spread calibration bundle."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_spec: BacktestRunSpec
    spec_path: Path
    estimator_timeframe: NonEmptyStr = "1m"
    output_root: Path = Path("var/runtime/calibration")
    requested_by: NonEmptyStr = "cli"
    correlation_id: NonEmptyStr | None = None

    @field_validator("estimator_timeframe")
    @classmethod
    def _normalize_estimator_timeframe(cls, value: str) -> str:
        return normalize_timeframe(value)


class SpreadCalibrationDatasetMaterializer(Protocol):
    """Materialize a normalized dataset for the calibration estimator timeframe."""

    def materialize(self, dataset: DatasetSpec) -> Any:
        """Return normalized bars for one dataset spec."""
        ...


def run_spread_calibration_cli(
    command: SpreadCalibrationCliCommand,
    materializer: SpreadCalibrationDatasetMaterializer,
) -> SpreadCalibrationPublicationResult:
    """Translate a CLI request into Phase 1 panel build and Phase 2 publication."""

    calibration_dataset = _dataset_for_estimator_timeframe(
        command.run_spec.dataset,
        command.estimator_timeframe,
    )
    materialized_dataset = materializer.materialize(calibration_dataset)
    calibration_result = build_spread_calibration_panel(
        SpreadCalibrationCommand(
            materialized_dataset=materialized_dataset,
            estimator_timeframe=command.estimator_timeframe,
            calibration_start_utc=command.run_spec.execution_window.start_utc,
            calibration_end_utc=command.run_spec.execution_window.end_utc,
            requested_by=command.requested_by,
            correlation_id=command.correlation_id,
        )
    )
    return publish_spread_calibration(
        SpreadCalibrationPublicationCommand(
            calibration_result=calibration_result,
            target_timeframe=command.run_spec.dataset.timeframe,
            output_root=command.output_root,
        )
    )


def _dataset_for_estimator_timeframe(
    dataset: DatasetSpec,
    estimator_timeframe: str,
) -> DatasetSpec:
    payload = dataset.model_dump(
        mode="python",
        exclude={"content_hash", "dataset_id"},
    )
    payload["timeframe"] = normalize_timeframe(estimator_timeframe)
    return DatasetSpec.model_validate(payload)


__all__ = [
    "SpreadCalibrationCliCommand",
    "SpreadCalibrationDatasetMaterializer",
    "run_spread_calibration_cli",
]
