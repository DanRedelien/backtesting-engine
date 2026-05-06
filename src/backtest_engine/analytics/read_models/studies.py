"""Read models for study summaries and live allocation recommendations."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from backtest_engine.core.enums import RecommendationStatus, StudyVerdict
from backtest_engine.core.errors import InfrastructureError
from backtest_engine.core.types import JsonValue, NonEmptyStr


_STUDY_FILENAME = "study.json"
_FOLDS_FILENAME = "folds.json"
_CHAMPION_FILENAME = "champion.json"
_RECOMMENDATION_FILENAME = "recommendation.json"
_LATEST_RECOMMENDATION_FILENAME = "latest.json"
TReadModel = TypeVar("TReadModel", bound=BaseModel)


class StudySummaryReadModel(BaseModel):
    """A typed read model for one persisted study summary artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = Field(ge=1)
    study_id: NonEmptyStr
    artifact_path: Path = Field(default_factory=Path)
    created_at_utc: datetime
    objective_metric: NonEmptyStr
    verdict: StudyVerdict
    fold_count: int = Field(ge=0)
    trial_count: int = Field(ge=0)
    median_oos_score: float
    median_oos_sharpe: float
    pass_folds: int = Field(ge=0)
    warning_folds: int = Field(ge=0)
    fail_folds: int = Field(ge=0)
    champion_weights: dict[NonEmptyStr, float] = Field(default_factory=dict)
    source_bundle_uris: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)
    summary: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_fold_counts(self) -> "StudySummaryReadModel":
        if self.pass_folds + self.warning_folds + self.fail_folds > self.fold_count:
            raise ValueError("study fold counts cannot exceed fold_count")
        return self


class LiveAllocationRecommendationReadModel(BaseModel):
    """A typed read model for one persisted live allocation recommendation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = Field(ge=1)
    recommendation_id: NonEmptyStr
    study_id: NonEmptyStr
    artifact_path: Path = Field(default_factory=Path)
    as_of_utc: datetime
    source_window_start_utc: datetime
    source_window_end_utc: datetime
    status: RecommendationStatus
    target_portfolio_vol_frac: float = Field(gt=0.0)
    weight_step_frac: float = Field(gt=0.0)
    max_sleeve_weight_frac: float = Field(gt=0.0)
    top_k_confirm: int = Field(ge=1)
    champion_weights: dict[NonEmptyStr, float] = Field(default_factory=dict)
    summary: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_window(self) -> "LiveAllocationRecommendationReadModel":
        if self.source_window_start_utc >= self.source_window_end_utc:
            raise ValueError("recommendation source window start must be earlier than end")
        return self


class ConfirmedFoldReadModel(BaseModel):
    """A typed read model for one confirmed fold payload."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = Field(ge=1)
    study_id: NonEmptyStr
    fold_id: NonEmptyStr
    selected_candidate_id: NonEmptyStr | None = None
    selected_candidate_rank: int | None = Field(default=None, ge=1)
    selected_run_id: NonEmptyStr | None = None
    selected_bundle_uri: NonEmptyStr | None = None
    champion_weights: dict[NonEmptyStr, float] = Field(default_factory=dict)
    eligible_slots: tuple[NonEmptyStr, ...] = Field(default_factory=tuple)
    execution_failed: bool = False
    trade_insufficient: bool = False
    quality_profitable: bool = False
    effective_bar_count: int = Field(ge=0, default=0)
    effective_start_utc: datetime | None = None
    effective_end_utc: datetime | None = None
    net_return: float = 0.0
    sharpe_after_costs: float = 0.0
    max_drawdown: float = 0.0
    trade_count: int = 0
    summary: dict[str, JsonValue] = Field(default_factory=dict)


class ConfirmedFoldCollectionReadModel(BaseModel):
    """A typed read model for one persisted fold collection artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = Field(ge=1)
    study_id: NonEmptyStr
    artifact_path: Path = Field(default_factory=Path)
    folds: tuple[ConfirmedFoldReadModel, ...] = Field(default_factory=tuple)


class StudyChampionReadModel(BaseModel):
    """A typed read model for one persisted champion artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = Field(ge=1)
    study_id: NonEmptyStr
    artifact_path: Path = Field(default_factory=Path)
    created_at_utc: datetime
    verdict: StudyVerdict
    champion_weights: dict[NonEmptyStr, float] = Field(default_factory=dict)
    source_fold_id: NonEmptyStr | None = None
    source_candidate_id: NonEmptyStr | None = None
    summary: dict[str, JsonValue] = Field(default_factory=dict)


def load_study_summary_read_model(artifact_path: Path) -> StudySummaryReadModel:
    """Load one typed study summary artifact from disk."""

    resolved_path = _resolve_artifact_path(artifact_path, filename=_STUDY_FILENAME)
    return _load_json_read_model(
        resolved_path,
        model=StudySummaryReadModel,
    )


def load_live_allocation_recommendation_read_model(
    artifact_path: Path,
) -> LiveAllocationRecommendationReadModel:
    """Load one typed live allocation recommendation artifact from disk."""

    resolved_path = _resolve_artifact_path(artifact_path, filename=_RECOMMENDATION_FILENAME)
    return _load_json_read_model(
        resolved_path,
        model=LiveAllocationRecommendationReadModel,
    )


def load_confirmed_fold_collection_read_model(
    artifact_path: Path,
) -> ConfirmedFoldCollectionReadModel:
    """Load one typed fold collection artifact from disk."""

    resolved_path = _resolve_artifact_path(artifact_path, filename=_FOLDS_FILENAME)
    return _load_json_read_model(
        resolved_path,
        model=ConfirmedFoldCollectionReadModel,
    )


def load_study_champion_read_model(artifact_path: Path) -> StudyChampionReadModel:
    """Load one typed champion artifact from disk."""

    resolved_path = _resolve_artifact_path(artifact_path, filename=_CHAMPION_FILENAME)
    return _load_json_read_model(
        resolved_path,
        model=StudyChampionReadModel,
    )


def load_latest_live_allocation_recommendation_read_model(
    results_root: Path,
) -> LiveAllocationRecommendationReadModel:
    """Load the explicit latest recommendation surface from disk."""

    return _load_json_read_model(
        results_root / "recommendations" / _LATEST_RECOMMENDATION_FILENAME,
        model=LiveAllocationRecommendationReadModel,
    )


def _resolve_artifact_path(path: Path, *, filename: str) -> Path:
    if path.suffix:
        return path
    return path / filename


def _load_json_read_model(model_path: Path, *, model: type[TReadModel]) -> TReadModel:
    try:
        payload = model_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise InfrastructureError(
            "failed to load artifact file",
            artifact_path=str(model_path),
        ) from exc

    try:
        read_model = model.model_validate_json(payload)
    except ValidationError as exc:
        raise InfrastructureError(
            "artifact file failed validation",
            artifact_path=str(model_path),
        ) from exc

    return read_model.model_copy(update={"artifact_path": model_path})


__all__ = [
    "LiveAllocationRecommendationReadModel",
    "ConfirmedFoldCollectionReadModel",
    "ConfirmedFoldReadModel",
    "RecommendationStatus",
    "StudyChampionReadModel",
    "StudySummaryReadModel",
    "StudyVerdict",
    "load_confirmed_fold_collection_read_model",
    "load_latest_live_allocation_recommendation_read_model",
    "load_live_allocation_recommendation_read_model",
    "load_study_champion_read_model",
    "load_study_summary_read_model",
]
