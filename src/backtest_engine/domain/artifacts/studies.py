"""Persisted study and recommendation artifact contracts."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from backtest_engine.core.enums import RecommendationStatus, StudyVerdict
from backtest_engine.core.ids import (
    RecommendationId,
    StudyId,
    build_recommendation_id,
    stable_hash,
)
from backtest_engine.core.time import ensure_utc
from backtest_engine.core.types import JsonValue, NonEmptyStr


class PortfolioWeightStudyArtifact(BaseModel):
    """Persisted study summary artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = Field(ge=1, default=1)
    study_id: StudyId
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


class StudyChampionArtifact(BaseModel):
    """Persisted champion payload extracted from the study result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = Field(ge=1, default=1)
    study_id: StudyId
    created_at_utc: datetime
    verdict: StudyVerdict
    champion_weights: dict[NonEmptyStr, float] = Field(default_factory=dict)
    source_fold_id: NonEmptyStr | None = None
    source_candidate_id: NonEmptyStr | None = None
    summary: dict[str, JsonValue] = Field(default_factory=dict)


class LiveAllocationRecommendationArtifact(BaseModel):
    """Persisted live-handoff recommendation artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = Field(ge=1, default=1)
    recommendation_id: RecommendationId
    study_id: StudyId
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


class PortfolioWeightStudyFoldResult(BaseModel):
    """Compact confirmed fold outcome written into fold artifacts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = Field(ge=1, default=1)
    study_id: StudyId
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


class ConfirmedFoldCollectionArtifact(BaseModel):
    """Persisted collection of confirmed fold payloads."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = Field(ge=1, default=1)
    study_id: StudyId
    folds: tuple[PortfolioWeightStudyFoldResult, ...] = Field(default_factory=tuple)


class SavedStudyArtifacts(BaseModel):
    """Durable locations for one persisted study."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    study_id: StudyId
    study_uri: NonEmptyStr
    folds_uri: NonEmptyStr
    trials_uri: NonEmptyStr
    champion_uri: NonEmptyStr


class SavedRecommendationArtifact(BaseModel):
    """Durable locations for one persisted recommendation surface."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    recommendation_id: RecommendationId
    recommendation_uri: NonEmptyStr
    latest_recommendation_uri: NonEmptyStr


def build_recommendation_artifact_id(
    *,
    study_id: str,
    created_at_utc: datetime,
    source_window_start_utc: datetime,
    source_window_end_utc: datetime,
    status: RecommendationStatus,
    target_portfolio_vol_frac: float,
    weight_step_frac: float,
    max_sleeve_weight_frac: float,
    top_k_confirm: int,
    champion_weights: dict[str, float],
) -> RecommendationId:
    """Build a deterministic recommendation identifier."""

    payload = {
        "study_id": study_id,
        "as_of_utc": ensure_utc(created_at_utc).isoformat(),
        "source_window_start_utc": ensure_utc(source_window_start_utc).isoformat(),
        "source_window_end_utc": ensure_utc(source_window_end_utc).isoformat(),
        "status": status.value,
        "target_portfolio_vol_frac": target_portfolio_vol_frac,
        "weight_step_frac": weight_step_frac,
        "max_sleeve_weight_frac": max_sleeve_weight_frac,
        "top_k_confirm": top_k_confirm,
        "champion_weights": champion_weights,
    }
    return build_recommendation_id(stable_hash(payload))


__all__ = [
    "ConfirmedFoldCollectionArtifact",
    "LiveAllocationRecommendationArtifact",
    "PortfolioWeightStudyArtifact",
    "PortfolioWeightStudyFoldResult",
    "SavedRecommendationArtifact",
    "SavedStudyArtifacts",
    "StudyChampionArtifact",
    "build_recommendation_artifact_id",
]
