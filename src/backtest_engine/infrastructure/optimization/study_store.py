"""Filesystem persistence for study and recommendation artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from backtest_engine.core.errors import InfrastructureError
from backtest_engine.core.types import JsonValue
from backtest_engine.domain.artifacts.studies import (
    ConfirmedFoldCollectionArtifact,
    LiveAllocationRecommendationArtifact,
    PortfolioWeightStudyArtifact,
    PortfolioWeightStudyFoldResult,
    SavedRecommendationArtifact,
    SavedStudyArtifacts,
    StudyChampionArtifact,
)


@dataclass(frozen=True)
class FilesystemStudyArtifactStore:
    """Persist study and recommendation artifacts under the shared results root."""

    results_root: Path

    def save_study(
        self,
        study: PortfolioWeightStudyArtifact,
        *,
        folds: tuple[PortfolioWeightStudyFoldResult, ...],
        champion: StudyChampionArtifact,
        trial_rows: tuple[dict[str, JsonValue], ...],
    ) -> SavedStudyArtifacts:
        study_root = self.results_root / "studies" / study.study_id
        study_path = study_root / "study.json"
        folds_path = study_root / "folds.json"
        trials_path = study_root / "trials.parquet"
        champion_path = study_root / "champion.json"
        try:
            study_root.mkdir(parents=True, exist_ok=True)
            study_path.write_text(study.model_dump_json(indent=2), encoding="utf-8")
            champion_path.write_text(champion.model_dump_json(indent=2), encoding="utf-8")
            fold_collection = ConfirmedFoldCollectionArtifact(
                study_id=study.study_id,
                folds=folds,
            )
            folds_path.write_text(
                fold_collection.model_dump_json(indent=2),
                encoding="utf-8",
            )
            for fold in folds:
                fold_dir = study_root / "folds" / fold.fold_id
                fold_dir.mkdir(parents=True, exist_ok=True)
                (fold_dir / "confirmed.json").write_text(
                    fold.model_dump_json(indent=2),
                    encoding="utf-8",
                )
            pd.DataFrame(list(trial_rows)).to_parquet(trials_path)
        except Exception as exc:
            raise InfrastructureError(
                "failed to persist study artifacts",
                study_id=study.study_id,
                study_path=str(study_path),
            ) from exc

        return SavedStudyArtifacts(
            study_id=study.study_id,
            study_uri=study_path.as_posix(),
            folds_uri=folds_path.as_posix(),
            trials_uri=trials_path.as_posix(),
            champion_uri=champion_path.as_posix(),
        )

    def save_recommendation(
        self,
        recommendation: LiveAllocationRecommendationArtifact,
    ) -> SavedRecommendationArtifact:
        recommendation_root = self.results_root / "recommendations" / recommendation.recommendation_id
        recommendation_path = recommendation_root / "recommendation.json"
        latest_recommendation_path = self.results_root / "recommendations" / "latest.json"
        try:
            recommendation_root.mkdir(parents=True, exist_ok=True)
            latest_recommendation_path.parent.mkdir(parents=True, exist_ok=True)
            recommendation_path.write_text(
                recommendation.model_dump_json(indent=2),
                encoding="utf-8",
            )
            latest_recommendation_path.write_text(
                recommendation.model_dump_json(indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            raise InfrastructureError(
                "failed to persist recommendation artifact",
                recommendation_id=recommendation.recommendation_id,
                recommendation_path=str(recommendation_path),
            ) from exc
        return SavedRecommendationArtifact(
            recommendation_id=recommendation.recommendation_id,
            recommendation_uri=recommendation_path.as_posix(),
            latest_recommendation_uri=latest_recommendation_path.as_posix(),
        )


__all__ = ["FilesystemStudyArtifactStore"]
