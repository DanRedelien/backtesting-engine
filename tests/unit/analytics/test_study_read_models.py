from __future__ import annotations

import json
from pathlib import Path

import pytest

from backtest_engine.analytics.read_models import (
    ConfirmedFoldCollectionReadModel,
    LiveAllocationRecommendationReadModel,
    RecommendationStatus,
    StudyChampionReadModel,
    StudySummaryReadModel,
    StudyVerdict,
    load_confirmed_fold_collection_read_model,
    load_latest_live_allocation_recommendation_read_model,
    load_live_allocation_recommendation_read_model,
    load_study_champion_read_model,
    load_study_summary_read_model,
)
from backtest_engine.core.errors import InfrastructureError


def _write_json(path: Path, payload: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def test_load_study_summary_read_model_reads_directory_or_file(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "results" / "studies" / "study-001"
    payload = {
        "schema_version": 1,
        "study_id": "study-001",
        "created_at_utc": "2026-04-11T10:00:00Z",
        "objective_metric": "sharpe",
        "verdict": "PASS",
        "fold_count": 5,
        "trial_count": 120,
        "median_oos_score": 0.24,
        "median_oos_sharpe": 0.36,
        "pass_folds": 3,
        "warning_folds": 1,
        "fail_folds": 1,
        "champion_weights": {"slot-1": 0.6, "slot-2": 0.4},
        "source_bundle_uris": ["results/bundle-1", "results/bundle-2"],
        "summary": {"note": "bootstrap default"},
    }
    _write_json(artifact_dir / "study.json", payload)

    summary = load_study_summary_read_model(artifact_dir)

    assert isinstance(summary, StudySummaryReadModel)
    assert summary.artifact_path == artifact_dir / "study.json"
    assert summary.verdict is StudyVerdict.PASS
    assert summary.champion_weights == {"slot-1": 0.6, "slot-2": 0.4}
    assert summary.source_bundle_uris == ("results/bundle-1", "results/bundle-2")


def test_load_live_allocation_recommendation_read_model_reads_directory_or_file(
    tmp_path: Path,
) -> None:
    artifact_dir = tmp_path / "results" / "recommendations" / "recommendation-001"
    payload = {
        "schema_version": 1,
        "recommendation_id": "recommendation-001",
        "study_id": "study-001",
        "as_of_utc": "2026-04-11T10:30:00Z",
        "source_window_start_utc": "2026-04-01T00:00:00Z",
        "source_window_end_utc": "2026-04-10T00:00:00Z",
        "status": "PUBLISHED",
        "target_portfolio_vol_frac": 0.15,
        "weight_step_frac": 0.01,
        "max_sleeve_weight_frac": 1.0,
        "top_k_confirm": 5,
        "champion_weights": {"slot-1": 0.55, "slot-2": 0.45},
        "summary": {"turnover": 0.24},
    }
    _write_json(artifact_dir / "recommendation.json", payload)

    recommendation = load_live_allocation_recommendation_read_model(artifact_dir)

    assert isinstance(recommendation, LiveAllocationRecommendationReadModel)
    assert recommendation.artifact_path == artifact_dir / "recommendation.json"
    assert recommendation.status is RecommendationStatus.PUBLISHED
    assert recommendation.champion_weights == {"slot-1": 0.55, "slot-2": 0.45}


def test_study_summary_loader_rejects_invalid_payload(tmp_path: Path) -> None:
    artifact_path = _write_json(
        tmp_path / "study.json",
        {
            "schema_version": 1,
            "study_id": "study-001",
            "created_at_utc": "2026-04-11T10:00:00Z",
            "objective_metric": "sharpe",
            "verdict": "PASS",
            "fold_count": 1,
            "trial_count": 1,
            "median_oos_score": 0.24,
            "median_oos_sharpe": 0.36,
            "pass_folds": 2,
            "warning_folds": 0,
            "fail_folds": 0,
        },
    )

    with pytest.raises(InfrastructureError, match="failed validation"):
        load_study_summary_read_model(artifact_path)


def test_load_confirmed_fold_collection_and_champion_read_models(tmp_path: Path) -> None:
    study_dir = tmp_path / "results" / "studies" / "study-001"
    folds_payload = {
        "schema_version": 1,
        "study_id": "study-001",
        "folds": [
            {
                "schema_version": 1,
                "study_id": "study-001",
                "fold_id": "fold-001",
                "selected_candidate_id": "candidate-001",
                "selected_candidate_rank": 1,
                "selected_run_id": "run-001",
                "selected_bundle_uri": "results/bundle-001",
                "champion_weights": {"slot-1": 0.6, "slot-2": 0.4},
                "eligible_slots": ["slot-1", "slot-2"],
                "execution_failed": False,
                "trade_insufficient": False,
                "quality_profitable": True,
                "effective_bar_count": 10,
                "effective_start_utc": "2026-04-01T00:00:00Z",
                "effective_end_utc": "2026-04-10T00:00:00Z",
                "net_return": 0.12,
                "sharpe_after_costs": 0.55,
                "max_drawdown": 0.08,
                "trade_count": 9,
                "summary": {"confirm_rank": 1},
            }
        ],
    }
    champion_payload = {
        "schema_version": 1,
        "study_id": "study-001",
        "created_at_utc": "2026-04-11T10:00:00Z",
        "verdict": "PASS",
        "champion_weights": {"slot-1": 0.6, "slot-2": 0.4},
        "source_fold_id": "fold-001",
        "source_candidate_id": "candidate-001",
        "summary": {"effective_end_utc": "2026-04-10T00:00:00Z"},
    }
    _write_json(study_dir / "folds.json", folds_payload)
    _write_json(study_dir / "champion.json", champion_payload)

    folds = load_confirmed_fold_collection_read_model(study_dir)
    champion = load_study_champion_read_model(study_dir)

    assert isinstance(folds, ConfirmedFoldCollectionReadModel)
    assert folds.folds[0].fold_id == "fold-001"
    assert folds.folds[0].selected_candidate_rank == 1
    assert isinstance(champion, StudyChampionReadModel)
    assert champion.source_fold_id == "fold-001"
    assert champion.champion_weights == {"slot-1": 0.6, "slot-2": 0.4}


def test_load_latest_recommendation_read_model(tmp_path: Path) -> None:
    results_root = tmp_path / "results"
    payload = {
        "schema_version": 1,
        "recommendation_id": "recommendation-001",
        "study_id": "study-001",
        "as_of_utc": "2026-04-11T10:30:00Z",
        "source_window_start_utc": "2026-04-01T00:00:00Z",
        "source_window_end_utc": "2026-04-10T00:00:00Z",
        "status": "BLOCKED",
        "target_portfolio_vol_frac": 0.15,
        "weight_step_frac": 0.01,
        "max_sleeve_weight_frac": 1.0,
        "top_k_confirm": 5,
        "champion_weights": {"slot-1": 0.55, "slot-2": 0.45},
        "summary": {"publication_blockers": ["runtime_policy_parity_pending"]},
    }
    _write_json(results_root / "recommendations" / "latest.json", payload)

    recommendation = load_latest_live_allocation_recommendation_read_model(results_root)

    assert recommendation.status is RecommendationStatus.BLOCKED
    assert recommendation.recommendation_id == "recommendation-001"
