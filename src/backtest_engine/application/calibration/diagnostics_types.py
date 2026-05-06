"""Internal contracts for spread calibration diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from backtest_engine.application.calibration.publication_helpers import isoformat_utc


ClipStatus = Literal["none", "min", "max"]
PredictionKind = Literal["raw_model_prediction", "effective_runtime_prediction"]
SampleRole = Literal["train", "holdout", "purged"]
RowId = tuple[str, str, SampleRole]

RAW_MODEL_PREDICTION: PredictionKind = "raw_model_prediction"
EFFECTIVE_RUNTIME_PREDICTION: PredictionKind = "effective_runtime_prediction"
PREDICTION_KINDS: tuple[PredictionKind, ...] = (
    RAW_MODEL_PREDICTION,
    EFFECTIVE_RUNTIME_PREDICTION,
)


@dataclass(frozen=True)
class ClippedPrediction:
    """One raw model prediction after publication bound enforcement."""

    raw_price: float
    effective_price: float
    clip_status: ClipStatus


@dataclass(frozen=True)
class CalibrationDiagnosticRow:
    """Per-row snapshot used by diagnostics metrics, baselines, plots, and JSON."""

    symbol: str
    sample_role: SampleRole
    timestamp: datetime
    observed_raw: float
    observed_effective: float
    raw_predicted: float
    effective_predicted: float
    clip_status: ClipStatus
    session_bucket_id: str
    volatility_signal: float
    liquidity_signal: float
    target_floored: bool

    @property
    def row_id(self) -> RowId:
        """Return a deterministic row identity for baseline joins."""

        return (self.symbol, isoformat_utc(self.timestamp), self.sample_role)

    def predicted(self, prediction_kind: PredictionKind) -> float:
        """Return raw or effective prediction according to the requested diagnostic view."""

        if prediction_kind == RAW_MODEL_PREDICTION:
            return self.raw_predicted
        return self.effective_predicted

    def to_report(self) -> dict[str, object]:
        """Return a JSON-serializable row snapshot."""

        return {
            "symbol": self.symbol,
            "sample_role": self.sample_role,
            "timestamp": isoformat_utc(self.timestamp),
            "observed_raw": self.observed_raw,
            "observed_effective": self.observed_effective,
            "raw_predicted": self.raw_predicted,
            "effective_predicted": self.effective_predicted,
            "clip_status": self.clip_status,
            "session_bucket_id": self.session_bucket_id,
            "volatility_signal": self.volatility_signal,
            "liquidity_signal": self.liquidity_signal,
            "target_floored": self.target_floored,
        }


@dataclass(frozen=True)
class BaselinePredictions:
    """Named holdout baseline predictions keyed by diagnostic row identity."""

    predictions_by_name: dict[str, dict[RowId, float]]
    fallback_counts_by_name: dict[str, dict[str, int]]


@dataclass(frozen=True)
class DiagnosticsArtifacts:
    """Diagnostics PNG paths written next to the calibration report."""

    summary_png_path: Path
    symbol_png_paths_by_symbol: dict[str, Path]

    @property
    def symbol_png_paths(self) -> tuple[Path, ...]:
        """Return symbol PNG paths in deterministic symbol order."""

        return tuple(
            path for _symbol, path in sorted(self.symbol_png_paths_by_symbol.items())
        )

    @property
    def all_paths(self) -> tuple[Path, ...]:
        """Return all diagnostic artifact paths in deterministic order."""

        return (self.summary_png_path, *self.symbol_png_paths)


__all__ = [
    "BaselinePredictions",
    "CalibrationDiagnosticRow",
    "ClipStatus",
    "ClippedPrediction",
    "DiagnosticsArtifacts",
    "EFFECTIVE_RUNTIME_PREDICTION",
    "PREDICTION_KINDS",
    "PredictionKind",
    "RAW_MODEL_PREDICTION",
    "RowId",
    "SampleRole",
]
