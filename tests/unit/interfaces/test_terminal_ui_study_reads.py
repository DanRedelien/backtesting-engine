from __future__ import annotations

import json
from pathlib import Path

from backtest_engine.analytics.read_models import RecommendationStatus, StudyVerdict
from backtest_engine.interfaces.terminal_ui.query_service import TerminalUiQueryService


def _write_json(path: Path, payload: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def test_terminal_ui_query_service_loads_study_summary_and_recommendation(
    tmp_path: Path,
) -> None:
    study_artifact = _write_json(
        tmp_path / "results" / "studies" / "study-001" / "study.json",
        {
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
            "source_bundle_uris": ["results/bundle-1"],
            "summary": {"note": "study"},
        },
    )
    recommendation_artifact = _write_json(
        tmp_path / "results" / "recommendations" / "recommendation-001" / "recommendation.json",
        {
            "schema_version": 1,
            "recommendation_id": "recommendation-001",
            "study_id": "study-001",
            "as_of_utc": "2026-04-11T10:30:00Z",
            "source_window_start_utc": "2026-04-01T00:00:00Z",
            "source_window_end_utc": "2026-04-10T00:00:00Z",
            "status": "ADVISORY",
            "target_portfolio_vol_frac": 0.15,
            "weight_step_frac": 0.01,
            "max_sleeve_weight_frac": 1.0,
            "top_k_confirm": 5,
            "champion_weights": {"slot-1": 0.6, "slot-2": 0.4},
            "summary": {"note": "recommendation"},
        },
    )
    folds_artifact = _write_json(
        tmp_path / "results" / "studies" / "study-001" / "folds.json",
        {
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
        },
    )
    champion_artifact = _write_json(
        tmp_path / "results" / "studies" / "study-001" / "champion.json",
        {
            "schema_version": 1,
            "study_id": "study-001",
            "created_at_utc": "2026-04-11T10:00:00Z",
            "verdict": "PASS",
            "champion_weights": {"slot-1": 0.6, "slot-2": 0.4},
            "source_fold_id": "fold-001",
            "source_candidate_id": "candidate-001",
            "summary": {"effective_end_utc": "2026-04-10T00:00:00Z"},
        },
    )
    _write_json(
        tmp_path / "results" / "recommendations" / "latest.json",
        {
            "schema_version": 1,
            "recommendation_id": "recommendation-001",
            "study_id": "study-001",
            "as_of_utc": "2026-04-11T10:30:00Z",
            "source_window_start_utc": "2026-04-01T00:00:00Z",
            "source_window_end_utc": "2026-04-10T00:00:00Z",
            "status": "ADVISORY",
            "target_portfolio_vol_frac": 0.15,
            "weight_step_frac": 0.01,
            "max_sleeve_weight_frac": 1.0,
            "top_k_confirm": 5,
            "champion_weights": {"slot-1": 0.6, "slot-2": 0.4},
            "summary": {"note": "latest"},
        },
    )

    query_service = TerminalUiQueryService(container=object(), results_root=tmp_path / "results")
    study = query_service.load_study_summary(study_artifact)
    recommendation = query_service.load_recommendation(recommendation_artifact)
    folds = query_service.load_confirmed_folds(folds_artifact)
    champion = query_service.load_study_champion(champion_artifact)
    latest = query_service.load_latest_recommendation(tmp_path / "results")

    assert study.verdict is StudyVerdict.PASS
    assert study.artifact_path == study_artifact
    assert recommendation.status is RecommendationStatus.ADVISORY
    assert recommendation.artifact_path == recommendation_artifact
    assert folds.folds[0].fold_id == "fold-001"
    assert champion.source_candidate_id == "candidate-001"
    assert latest.recommendation_id == "recommendation-001"
