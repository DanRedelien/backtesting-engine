"""Typed contracts for portfolio-weight study workflows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from backtest_engine.application.portfolio.run_portfolio_backtest import (
    PortfolioRunCommand,
    PortfolioRunResult,
)
from backtest_engine.application.single.run_single_backtest import SingleRunCommand, SingleRunResult
from backtest_engine.config.runtime import BacktestRunSpec, PortfolioExecutionPolicy
from backtest_engine.core.enums import RecommendationStatus, RunKind, StudyVerdict
from backtest_engine.core.ids import RecommendationId, StudyId, build_study_id, stable_hash
from backtest_engine.core.protocols import Clock
from backtest_engine.core.types import JsonValue, NonEmptyStr
from backtest_engine.domain.artifacts.studies import (
    LiveAllocationRecommendationArtifact,
    PortfolioWeightStudyArtifact,
    PortfolioWeightStudyFoldResult,
    SavedRecommendationArtifact,
    SavedStudyArtifacts,
    StudyChampionArtifact,
)
from backtest_engine.infrastructure.artifacts.bundle_loader import BundleLoader


class PortfolioWeightStudyThresholds(BaseModel):
    """Bootstrap verdict thresholds for portfolio-weight studies."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    quality_sharpe_floor: float = 0.3
    min_quality_profitable_folds: int = Field(ge=1, default=3)
    min_consecutive_quality_profitable_folds: int = Field(ge=1, default=2)
    min_trades_per_fold: int = Field(ge=1, default=7)
    hard_drawdown_frac: float = Field(gt=0.0, default=0.25)
    max_recommendation_age_days: int = Field(ge=1, default=7)


class PortfolioWeightStudyControlSpec(BaseModel):
    """Search-control truth owned by the study rather than run execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    min_effective_oos_bars: int | None = Field(default=None, ge=1)
    weight_step_frac: float = Field(gt=0.0, le=1.0, default=0.01)
    max_sleeve_weight_frac: float = Field(gt=0.0, le=1.0, default=1.0)
    top_k_confirm: int = Field(ge=1, default=5)
    trial_budget: int | None = Field(default=None, ge=1)
    verdict_thresholds: PortfolioWeightStudyThresholds = Field(
        default_factory=PortfolioWeightStudyThresholds
    )

    @model_validator(mode="after")
    def _finalize_defaults(self) -> "PortfolioWeightStudyControlSpec":
        if self.min_effective_oos_bars is None:
            object.__setattr__(self, "min_effective_oos_bars", 20)
        if float(self.max_sleeve_weight_frac) + 1e-12 < float(self.weight_step_frac):
            raise ValueError("max_sleeve_weight_frac must be >= weight_step_frac")
        return self

    def resolve_trial_budget(self, *, eligible_sleeves: int) -> int:
        """Resolve the adaptive trial budget from the current eligible universe."""

        if self.trial_budget is not None:
            return int(self.trial_budget)
        return max(120, min(400, 40 * max(1, int(eligible_sleeves))))


class PortfolioWeightStudyFoldSpec(BaseModel):
    """One fold with explicit in-sample and out-of-sample canonical run specs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fold_id: NonEmptyStr
    in_sample_run_spec: BacktestRunSpec
    out_of_sample_run_spec: BacktestRunSpec

    @model_validator(mode="after")
    def _validate_shape(self) -> "PortfolioWeightStudyFoldSpec":
        if self.in_sample_run_spec.run_kind is not RunKind.PORTFOLIO:
            raise ValueError("in_sample_run_spec must be a portfolio run")
        if self.out_of_sample_run_spec.run_kind is not RunKind.PORTFOLIO:
            raise ValueError("out_of_sample_run_spec must be a portfolio run")
        if self.in_sample_run_spec.portfolio_policy != self.out_of_sample_run_spec.portfolio_policy:
            raise ValueError("in-sample and out-of-sample folds must share one portfolio_policy")
        in_slots = tuple(strategy.slot_id for strategy in self.in_sample_run_spec.strategies)
        out_slots = tuple(strategy.slot_id for strategy in self.out_of_sample_run_spec.strategies)
        if in_slots != out_slots:
            raise ValueError("fold run specs must preserve slot ordering across in-sample and out-of-sample")
        return self


class PortfolioWeightStudySpec(BaseModel):
    """The search-control contract for one portfolio-weight study."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    folds: tuple[PortfolioWeightStudyFoldSpec, ...] = Field(default_factory=tuple)
    control: PortfolioWeightStudyControlSpec = Field(default_factory=PortfolioWeightStudyControlSpec)
    objective_metric: NonEmptyStr = "sharpe_after_costs"
    seed: int = 7

    @model_validator(mode="after")
    def _validate_shape(self) -> "PortfolioWeightStudySpec":
        if not self.folds:
            raise ValueError("PortfolioWeightStudySpec requires at least one fold")
        if self.objective_metric != "sharpe_after_costs":
            raise ValueError("portfolio-weight study objective_metric must be sharpe_after_costs")
        first_slots = tuple(strategy.slot_id for strategy in self.folds[0].in_sample_run_spec.strategies)
        first_policy = self.execution_policy
        fold_ids = [fold.fold_id for fold in self.folds]
        if len(set(fold_ids)) != len(fold_ids):
            raise ValueError("study fold_id values must be unique")
        if len(first_slots) * float(self.control.max_sleeve_weight_frac) + 1e-9 < 1.0:
            raise ValueError("control.max_sleeve_weight_frac is infeasible for the study universe")
        min_effective_oos_bars = self.control.min_effective_oos_bars
        if min_effective_oos_bars is None:
            raise ValueError("control.min_effective_oos_bars must resolve to a concrete value")
        if min_effective_oos_bars < int(first_policy.vol_lookback_bars):
            raise ValueError("control.min_effective_oos_bars must be >= portfolio_policy.vol_lookback_bars")
        for fold in self.folds[1:]:
            fold_slots = tuple(strategy.slot_id for strategy in fold.in_sample_run_spec.strategies)
            if fold_slots != first_slots:
                raise ValueError("all folds must preserve one canonical slot ordering")
            if fold.in_sample_run_spec.portfolio_policy != first_policy:
                raise ValueError("all folds must share one portfolio_policy")
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def execution_policy(self) -> PortfolioExecutionPolicy:
        policy = self.folds[0].in_sample_run_spec.portfolio_policy
        if policy is None:
            raise ValueError("portfolio_weight studies require portfolio_policy")
        return policy

    @computed_field  # type: ignore[prop-decorator]
    @property
    def content_hash(self) -> str:
        payload = {
            "folds": [
                {
                    "fold_id": fold.fold_id,
                    "in_sample_run_spec": fold.in_sample_run_spec.model_dump(mode="json"),
                    "out_of_sample_run_spec": fold.out_of_sample_run_spec.model_dump(mode="json"),
                }
                for fold in self.folds
            ],
            "objective_metric": self.objective_metric,
            "seed": self.seed,
            "control": self.control.model_dump(mode="json"),
        }
        return stable_hash(payload)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def study_id(self) -> str:
        return build_study_id(self.content_hash)


class PortfolioWeightStudyCommand(BaseModel):
    """Operational metadata for one portfolio-weight study run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    study_spec: PortfolioWeightStudySpec
    requested_by: NonEmptyStr = "operator"
    correlation_id: NonEmptyStr | None = None


class PortfolioWeightStudyRunResult(BaseModel):
    """The outcome of one study execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    study_id: StudyId
    study_uri: NonEmptyStr
    champion_uri: NonEmptyStr
    recommendation_id: RecommendationId
    recommendation_uri: NonEmptyStr
    latest_recommendation_uri: NonEmptyStr
    verdict: StudyVerdict
    recommendation_status: RecommendationStatus
    champion_weights: dict[NonEmptyStr, float] = Field(default_factory=dict)


class StudySingleExecutor(Protocol):
    """Execute one canonical single backtest for sleeve analytics."""

    def run(self, command: SingleRunCommand, run_spec: BacktestRunSpec) -> SingleRunResult:
        """Return one canonical single-run outcome."""
        ...


class StudyPortfolioExecutor(Protocol):
    """Execute one canonical portfolio backtest for confirmatory reruns."""

    def run(self, command: PortfolioRunCommand, run_spec: BacktestRunSpec) -> PortfolioRunResult:
        """Return one canonical portfolio-run outcome."""
        ...


class StudyArtifactStore(Protocol):
    """Persist portfolio-weight study artifacts."""

    def save_study(
        self,
        study: PortfolioWeightStudyArtifact,
        *,
        folds: tuple[PortfolioWeightStudyFoldResult, ...],
        champion: StudyChampionArtifact,
        trial_rows: tuple[dict[str, JsonValue], ...],
    ) -> SavedStudyArtifacts:
        """Persist the study, folds, champion, and trial payloads."""
        ...

    def save_recommendation(
        self,
        recommendation: LiveAllocationRecommendationArtifact,
    ) -> SavedRecommendationArtifact:
        """Persist the recommendation payload."""
        ...


@dataclass(frozen=True)
class PortfolioWeightStudyDependencies:
    """Explicit dependencies for one study execution."""

    single_executor: StudySingleExecutor
    portfolio_executor: StudyPortfolioExecutor
    bundle_loader: BundleLoader
    artifact_store: StudyArtifactStore
    clock: Clock


__all__ = [
    "PortfolioWeightStudyCommand",
    "PortfolioWeightStudyControlSpec",
    "PortfolioWeightStudyDependencies",
    "PortfolioWeightStudyFoldSpec",
    "PortfolioWeightStudyRunResult",
    "PortfolioWeightStudySpec",
    "PortfolioWeightStudyThresholds",
    "StudyArtifactStore",
    "StudyPortfolioExecutor",
    "StudySingleExecutor",
]
