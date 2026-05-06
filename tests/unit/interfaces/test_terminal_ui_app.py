# mypy: disable-error-code=no-untyped-def
from __future__ import annotations

from decimal import Decimal
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from backtest_engine.config.runtime import BacktestRunSpec, ExecutionWindow
from backtest_engine.config.settings import PlatformSettings
from backtest_engine.core.enums import DatasetSource, RunKind, RuntimeBoundary
from backtest_engine.core.money import Money
from backtest_engine.domain.artifacts.bundles import ResultBundle
from backtest_engine.domain.artifacts.manifests import ArtifactManifest
from backtest_engine.domain.artifacts.provenance import ProvenanceRecord
from backtest_engine.domain.market.datasets import DatasetSpec
from backtest_engine.domain.strategy.specifications import (
    PortfolioStrategySpec,
    StrategyLegSpec,
    StrategySpec,
)
from backtest_engine.interfaces.terminal_ui.app import create_terminal_ui_app


def _build_run_spec(run_kind: RunKind, strategy_id: str) -> BacktestRunSpec:
    return BacktestRunSpec(
        run_kind=run_kind,
        execution_window=ExecutionWindow(
            start_utc=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end_utc=datetime(2024, 2, 1, tzinfo=timezone.utc),
        ),
        dataset=DatasetSpec(
            source_system=DatasetSource.PARQUET,
            normalization_policy="nautilus_v1",
            schema_version="1",
            symbol_universe=("ES",),
            timeframe="30m",
            dataset_version="2026-04-03",
        ),
        strategies=(
            PortfolioStrategySpec(
                slot_id="slot-1",
                weight_frac=1.0,
                strategy=StrategySpec(
                    strategy_id=strategy_id,
                    implementation_id=strategy_id,
                    policy_version="v1",
                ),
                legs=(StrategyLegSpec(symbol="ES"),),
            ),
        ),
        capital_base=Money(amount=Decimal("100000"), currency="USD"),
    )


def _build_bundle(run_kind: RunKind, strategy_id: str, created_at: datetime) -> ResultBundle:
    run_spec = _build_run_spec(run_kind, strategy_id)
    return ResultBundle(
        manifest=ArtifactManifest(
            run_id=run_spec.run_id,
            run_spec_hash=run_spec.content_hash,
            runtime_boundary=RuntimeBoundary.NAUTILUS,
            dataset_id=run_spec.dataset.dataset_id,
            config_hash=run_spec.content_hash,
            symbol_universe=run_spec.dataset.symbol_universe,
            strategy_ids=tuple(spec.strategy.strategy_id for spec in run_spec.strategies),
            capital_base=run_spec.capital_base,
            semantic_policy_version=run_spec.semantic_policy_version,
        ),
        provenance=ProvenanceRecord(
            run_id=run_spec.run_id,
            run_spec_hash=run_spec.content_hash,
            dataset_id=run_spec.dataset.dataset_id,
            created_at_utc=created_at,
        ),
        run_spec=run_spec,
        artifact_locations={"runtime_root": f"var/runtime/nautilus/{run_spec.run_id}"},
        summary={"net_profit": 125.0 if run_kind is RunKind.PORTFOLIO else 50.0},
    )


def _with_artifacts(
    bundle: ResultBundle,
    *,
    artifact_locations: dict[str, str],
    summary: dict[str, object] | None = None,
) -> ResultBundle:
    return bundle.model_copy(
        update={
            "artifact_locations": artifact_locations,
            "summary": summary if summary is not None else bundle.summary,
        }
    )


def _write_bundle(results_root: Path, bundle: ResultBundle) -> Path:
    bundle_path = results_root / bundle.bundle_id / "bundle.json"
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.write_text(
        bundle.model_dump_json(
            indent=2,
            exclude={"bundle_id", "metric_values"},
            exclude_computed_fields=True,
        ),
        encoding="utf-8",
    )
    return bundle_path


def _write_json(path: Path, payload: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _write_parquet(path: Path, frame: pd.DataFrame) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path)
    return path


def _write_returns(path: Path) -> Path:
    return _write_parquet(
        path,
        pd.DataFrame(
            {
                "timestamp_utc": [
                    "2024-01-01T00:00:00Z",
                    "2024-01-02T00:00:00Z",
                    "2024-01-03T00:00:00Z",
                ],
                "return_after_costs": [0.01, -0.02, 0.03],
            }
        ),
    )


def _write_positions(path: Path) -> Path:
    timestamps = pd.date_range("2024-01-01", periods=3, freq="1h", tz="UTC")
    return _write_parquet(
        path,
        pd.DataFrame(
            {
                "strategy_id": ["A", "A", "A", "B", "B", "B"],
                "timestamp_utc": list(timestamps) * 2,
                "ts_closed": list(timestamps) * 2,
                "is_snapshot": [False, False, False, False, False, False],
                "entry": ["BUY", "SELL", "BUY", "SELL", "BUY", "SELL"],
                "realized_return": [0.01, 0.02, -0.01, -0.01, 0.01, 0.02],
            }
        ),
    )


def _write_dashboard_artifacts(tmp_path: Path, name: str) -> dict[str, str]:
    artifact_root = tmp_path / "runtime" / name
    returns_path = _write_returns(artifact_root / "returns_report.parquet")
    positions_path = _write_positions(artifact_root / "positions_report.parquet")
    fills_path = _write_parquet(
        artifact_root / "fills_report.parquet",
        pd.DataFrame({"side": ["BUY", "SELL"]}),
    )
    orders_path = _write_parquet(
        artifact_root / "orders_report.parquet",
        pd.DataFrame({"id": [1, 2]}),
    )
    account_path = _write_parquet(
        artifact_root / "account_report.parquet",
        pd.DataFrame({"equity": [100000.0, 101500.0]}),
    )
    return {
        "returns_report": returns_path.as_posix(),
        "positions_report": positions_path.as_posix(),
        "fills_report": fills_path.as_posix(),
        "orders_report": orders_path.as_posix(),
        "account_report": account_path.as_posix(),
    }


def test_terminal_ui_dashboard_lists_bundles_and_prefers_newest_selection(tmp_path: Path) -> None:
    results_root = tmp_path / "results"
    older_bundle = _with_artifacts(
        _build_bundle(
            RunKind.SINGLE,
            "sma_pullback",
            created_at=datetime(2026, 4, 3, 10, tzinfo=timezone.utc),
        ),
        artifact_locations=_write_dashboard_artifacts(tmp_path, "older"),
    )
    newer_bundle = _with_artifacts(
        _build_bundle(
            RunKind.PORTFOLIO,
            "channel_breakout_long",
            created_at=datetime(2026, 4, 4, 11, tzinfo=timezone.utc),
        ),
        artifact_locations=_write_dashboard_artifacts(tmp_path, "newer"),
    )
    _write_bundle(results_root, older_bundle)
    _write_bundle(results_root, newer_bundle)

    client = TestClient(create_terminal_ui_app(results_root=results_root))

    response = client.get("/")

    assert response.status_code == 200
    assert "Saved Bundle Dashboard" in response.text
    assert newer_bundle.bundle_id in response.text
    assert older_bundle.bundle_id in response.text
    assert f"/bundles/{newer_bundle.bundle_id}" in response.text
    assert 'data-panel="stats"' in response.text
    assert 'data-panel="strategy-correlation"' in response.text
    assert 'data-panel="equity"' in response.text
    assert 'data-panel="drawdown"' in response.text
    assert "Core metrics" in response.text
    assert "Run facts" not in response.text
    assert "Total PnL" not in response.text
    assert "BUY fill count" not in response.text
    assert "Ending account" not in response.text


def test_terminal_ui_bundle_json_includes_multi_series_equity(tmp_path: Path) -> None:
    results_root = tmp_path / "results"
    bundle = _with_artifacts(
        _build_bundle(
            RunKind.SINGLE,
            "sma_pullback",
            created_at=datetime(2026, 4, 4, 11, tzinfo=timezone.utc),
        ),
        artifact_locations=_write_dashboard_artifacts(tmp_path, "json-detail"),
    )
    _write_bundle(results_root, bundle)
    client = TestClient(create_terminal_ui_app(results_root=results_root))

    response = client.get(f"/api/bundles/{bundle.bundle_id}")

    assert response.status_code == 200
    equity = response.json()["dashboard"]["equity"]
    assert [series["key"] for series in equity["series"]] == ["combined", "long", "short"]
    assert equity["points"] == equity["series"][0]["points"]


def test_terminal_ui_bundle_route_renders_explicit_bundle_without_scenario_controls(
    tmp_path: Path,
) -> None:
    results_root = tmp_path / "results"
    older_bundle = _with_artifacts(
        _build_bundle(
            RunKind.SINGLE,
            "sma_pullback",
            created_at=datetime(2026, 4, 3, 10, tzinfo=timezone.utc),
        ),
        artifact_locations=_write_dashboard_artifacts(tmp_path, "older-explicit"),
    )
    newer_bundle = _with_artifacts(
        _build_bundle(
            RunKind.PORTFOLIO,
            "channel_breakout_long",
            created_at=datetime(2026, 4, 4, 11, tzinfo=timezone.utc),
        ),
        artifact_locations=_write_dashboard_artifacts(tmp_path, "newer-explicit"),
    )
    _write_bundle(results_root, older_bundle)
    _write_bundle(results_root, newer_bundle)
    client = TestClient(create_terminal_ui_app(results_root=results_root))

    response = client.get(
        f"/bundles/{older_bundle.bundle_id}",
        params={"scenario_name": "execution_shock"},
    )

    assert response.status_code == 200
    assert older_bundle.bundle_id in response.text
    assert "Worker Request Ready" not in response.text
    assert "Build Plan" not in response.text


def test_terminal_ui_dashboard_missing_parquet_artifacts_returns_empty_panels(
    tmp_path: Path,
) -> None:
    results_root = tmp_path / "results"
    missing_returns_path = tmp_path / "runtime" / "missing" / "returns_report.parquet"
    bundle = _with_artifacts(
        _build_bundle(
            RunKind.SINGLE,
            "sma_pullback",
            created_at=datetime(2026, 4, 4, 11, tzinfo=timezone.utc),
        ),
        artifact_locations={"returns_report": missing_returns_path.as_posix()},
    )
    _write_bundle(results_root, bundle)
    client = TestClient(create_terminal_ui_app(results_root=results_root))

    response = client.get(f"/bundles/{bundle.bundle_id}")

    assert response.status_code == 200
    assert "No equity curve" in response.text
    assert "No drawdown curve" in response.text
    assert "positions_report artifact location is not present" in response.text


def test_terminal_ui_api_returns_catalog_and_rejects_single_bundle_scenario_plan(
    tmp_path: Path,
) -> None:
    results_root = tmp_path / "results"
    bundle = _build_bundle(
        RunKind.SINGLE,
        "sma_pullback",
        created_at=datetime(2026, 4, 4, 11, tzinfo=timezone.utc),
    )
    _write_bundle(results_root, bundle)
    client = TestClient(create_terminal_ui_app(results_root=results_root))

    catalog_response = client.get("/api/bundles")
    plan_response = client.get(
        f"/api/bundles/{bundle.bundle_id}/scenario-plan",
        params={"scenario_name": "execution_shock"},
    )

    assert catalog_response.status_code == 200
    payload = catalog_response.json()
    assert payload["bundles"][0]["bundle_id"] == bundle.bundle_id
    assert plan_response.status_code == 400
    assert plan_response.json()["error"] == "scenario reruns are only available for portfolio bundles"


def test_terminal_ui_api_returns_portfolio_scenario_plan(tmp_path: Path) -> None:
    results_root = tmp_path / "results"
    bundle = _build_bundle(
        RunKind.PORTFOLIO,
        "channel_breakout_long",
        created_at=datetime(2026, 4, 4, 11, tzinfo=timezone.utc),
    )
    _write_bundle(results_root, bundle)
    client = TestClient(create_terminal_ui_app(results_root=results_root))

    response = client.get(
        f"/api/bundles/{bundle.bundle_id}/scenario-plan",
        params={"scenario_name": "execution_shock"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_bundle_id"] == bundle.bundle_id
    assert payload["source_run_id"] == bundle.run_spec.run_id
    assert payload["job_command"]["scenario_name"] == "execution_shock"


def test_terminal_ui_app_builds_default_container_via_bootstrap(tmp_path: Path, monkeypatch) -> None:
    import importlib

    terminal_app_module = importlib.import_module("backtest_engine.interfaces.terminal_ui.app")
    captured_settings: list[PlatformSettings | None] = []

    class _BootstrapContainer:
        def __init__(self, settings: PlatformSettings) -> None:
            self.settings = settings

    def _fake_build_http_container(*, settings: PlatformSettings | None = None) -> _BootstrapContainer:
        captured_settings.append(settings)
        return _BootstrapContainer(settings or PlatformSettings())

    monkeypatch.setattr(terminal_app_module, "build_http_container", _fake_build_http_container)

    app = terminal_app_module.create_terminal_ui_app(results_root=tmp_path / "results")

    assert app.title == "Backtesting Engine V2 Terminal UI"
    assert captured_settings == [None]


def test_static_asset_version_changes_when_terminal_js_changes(tmp_path: Path, monkeypatch) -> None:
    import importlib

    terminal_app_module = importlib.import_module("backtest_engine.interfaces.terminal_ui.app")

    static_dir = tmp_path / "static"
    static_dir.mkdir()
    for relative_path in ("terminal.css", "terminal.js"):
        (static_dir / relative_path).write_text("initial", encoding="utf-8")

    monkeypatch.setattr(terminal_app_module, "_STATIC_DIR", static_dir)

    version_before = terminal_app_module._build_static_asset_version()

    (static_dir / "terminal.js").write_text("updated", encoding="utf-8")
    version_after = terminal_app_module._build_static_asset_version()

    assert version_after != version_before


def test_terminal_ui_api_returns_study_summary_and_recommendation(tmp_path: Path) -> None:
    results_root = tmp_path / "results"
    study_artifact = results_root / "studies" / "study-001" / "study.json"
    folds_artifact = results_root / "studies" / "study-001" / "folds.json"
    champion_artifact = results_root / "studies" / "study-001" / "champion.json"
    recommendation_artifact = (
        results_root / "recommendations" / "recommendation-001" / "recommendation.json"
    )
    _write_json(
        study_artifact,
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
    _write_json(
        recommendation_artifact,
        {
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
            "champion_weights": {"slot-1": 0.6, "slot-2": 0.4},
            "summary": {"note": "recommendation"},
        },
    )
    _write_json(
        folds_artifact,
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
    _write_json(
        champion_artifact,
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
        results_root / "recommendations" / "latest.json",
        {
            "schema_version": 1,
            "recommendation_id": "recommendation-latest",
            "study_id": "study-001",
            "as_of_utc": "2026-04-11T11:30:00Z",
            "source_window_start_utc": "2026-04-01T00:00:00Z",
            "source_window_end_utc": "2026-04-10T00:00:00Z",
            "status": "BLOCKED",
            "target_portfolio_vol_frac": 0.15,
            "weight_step_frac": 0.01,
            "max_sleeve_weight_frac": 1.0,
            "top_k_confirm": 5,
            "champion_weights": {"slot-1": 0.6, "slot-2": 0.4},
            "summary": {"publication_blockers": ["runtime_policy_parity_pending"]},
        },
    )
    client = TestClient(create_terminal_ui_app(results_root=results_root))

    study_response = client.get(
        "/api/studies/summary",
        params={"artifact_path": study_artifact.as_posix()},
    )
    recommendation_response = client.get(
        "/api/recommendations",
        params={"artifact_path": recommendation_artifact.as_posix()},
    )
    folds_response = client.get(
        "/api/studies/folds",
        params={"artifact_path": folds_artifact.as_posix()},
    )
    champion_response = client.get(
        "/api/studies/champion",
        params={"artifact_path": champion_artifact.as_posix()},
    )
    latest_recommendation_response = client.get("/api/recommendations/latest")

    assert study_response.status_code == 200
    assert study_response.json()["study_id"] == "study-001"
    assert study_response.json()["verdict"] == "PASS"
    assert recommendation_response.status_code == 200
    assert recommendation_response.json()["recommendation_id"] == "recommendation-001"
    assert recommendation_response.json()["status"] == "PUBLISHED"
    assert folds_response.status_code == 200
    assert folds_response.json()["folds"][0]["fold_id"] == "fold-001"
    assert champion_response.status_code == 200
    assert champion_response.json()["source_candidate_id"] == "candidate-001"
    assert latest_recommendation_response.status_code == 200
    assert latest_recommendation_response.json()["recommendation_id"] == "recommendation-latest"
