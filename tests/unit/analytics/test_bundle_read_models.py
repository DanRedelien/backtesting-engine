from __future__ import annotations

from decimal import Decimal
import math
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from backtest_engine.analytics.read_models import (
    build_bundle_dashboard_read_model,
    build_bundle_read_model,
    load_bundle_dashboard_read_model,
    load_bundle_read_model,
)
from backtest_engine.config.runtime import BacktestRunSpec, ExecutionWindow
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


def _build_run_spec() -> BacktestRunSpec:
    return BacktestRunSpec(
        run_kind=RunKind.PORTFOLIO,
        execution_window=ExecutionWindow(
            start_utc=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end_utc=datetime(2024, 2, 1, tzinfo=timezone.utc),
        ),
        dataset=DatasetSpec(
            source_system=DatasetSource.PARQUET,
            normalization_policy="nautilus_v1",
            schema_version="1",
            symbol_universe=("ES", "NQ"),
            timeframe="30m",
            dataset_version="2026-04-03",
        ),
        strategies=(
            PortfolioStrategySpec(
                slot_id="slot-1",
                weight_frac=0.5,
                strategy=StrategySpec(
                    strategy_id="sma_pullback",
                    implementation_id="sma_pullback",
                    policy_version="v1",
                ),
                legs=(StrategyLegSpec(symbol="ES"),),
            ),
            PortfolioStrategySpec(
                slot_id="slot-2",
                weight_frac=0.5,
                strategy=StrategySpec(
                    strategy_id="breakout",
                    implementation_id="breakout",
                    policy_version="v1",
                ),
                legs=(StrategyLegSpec(symbol="NQ"),),
            ),
        ),
        capital_base=Money(amount=Decimal("250000"), currency="USD"),
    )


def _build_bundle() -> ResultBundle:
    run_spec = _build_run_spec()
    return ResultBundle(
        manifest=ArtifactManifest(
            run_id=run_spec.run_id,
            run_spec_hash=run_spec.content_hash,
            runtime_boundary=RuntimeBoundary.NAUTILUS,
            dataset_id=run_spec.dataset.dataset_id,
            config_hash=run_spec.content_hash,
            symbol_universe=("ES", "NQ"),
            strategy_ids=("sma_pullback", "breakout"),
            capital_base=Money(amount=Decimal("250000"), currency="USD"),
            semantic_policy_version="v1",
        ),
        provenance=ProvenanceRecord(
            run_id=run_spec.run_id,
            run_spec_hash=run_spec.content_hash,
            dataset_id=run_spec.dataset.dataset_id,
            created_at_utc=datetime(2026, 4, 3, tzinfo=timezone.utc),
        ),
        run_spec=run_spec,
        artifact_locations={"runtime_root": f"var/runtime/nautilus/{run_spec.run_id}"},
        summary={"net_profit": 1250.0, "requested_by": "terminal"},
    )


def _build_statarb_bundle() -> ResultBundle:
    run_spec = _build_run_spec().model_copy(
        update={
            "strategies": (
                PortfolioStrategySpec(
                    slot_id="slot-spread",
                    weight_frac=1.0,
                    strategy=StrategySpec(
                        strategy_id="spread",
                        implementation_id="statarb_weighted_spread",
                        policy_version="v1",
                        parameters={"spread_weights": [1.0, -1.0]},
                    ),
                    legs=(StrategyLegSpec(symbol="ES"), StrategyLegSpec(symbol="NQ")),
                ),
            )
        }
    )
    return ResultBundle(
        manifest=ArtifactManifest(
            run_id=run_spec.run_id,
            run_spec_hash=run_spec.content_hash,
            runtime_boundary=RuntimeBoundary.NAUTILUS,
            dataset_id=run_spec.dataset.dataset_id,
            config_hash=run_spec.content_hash,
            symbol_universe=("ES", "NQ"),
            strategy_ids=("spread",),
            capital_base=Money(amount=Decimal("250000"), currency="USD"),
            semantic_policy_version="v1",
        ),
        provenance=ProvenanceRecord(
            run_id=run_spec.run_id,
            run_spec_hash=run_spec.content_hash,
            dataset_id=run_spec.dataset.dataset_id,
            created_at_utc=datetime(2026, 4, 3, tzinfo=timezone.utc),
        ),
        run_spec=run_spec,
        artifact_locations={"runtime_root": f"var/runtime/nautilus/{run_spec.run_id}"},
        summary={},
    )


def _with_artifacts(
    bundle: ResultBundle,
    *,
    artifact_locations: dict[str, str] | None = None,
    summary: dict[str, object] | None = None,
) -> ResultBundle:
    return bundle.model_copy(
        update={
            "artifact_locations": artifact_locations or {},
            "summary": summary or {},
        }
    )


def _write_parquet(path: Path, frame: pd.DataFrame) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path)
    return path


def _write_returns(path: Path, rows: list[dict[str, object]]) -> Path:
    return _write_parquet(path, pd.DataFrame(rows))


def _write_positions(path: Path, rows: list[dict[str, object]]) -> Path:
    return _write_parquet(path, pd.DataFrame(rows))


def _stat_keys(bundle: ResultBundle) -> list[str]:
    dashboard = build_bundle_dashboard_read_model(bundle)
    return [item.key for item in dashboard.stats.items]


class FakeBundleLoader:
    def __init__(self, bundle: ResultBundle) -> None:
        self.bundle = bundle
        self.paths: list[Path] = []

    def load_bundle(self, path: Path) -> ResultBundle:
        self.paths.append(path)
        return self.bundle


def test_build_bundle_read_model_projects_bundle_metadata() -> None:
    bundle = _build_bundle()
    read_model = build_bundle_read_model(bundle)

    assert read_model.dataset_id == bundle.manifest.dataset_id
    assert read_model.run_kind is RunKind.PORTFOLIO
    assert read_model.runtime_boundary is RuntimeBoundary.NAUTILUS
    assert read_model.strategy_ids == ("sma_pullback", "breakout")
    assert read_model.metric_values == {"net_profit": 1250.0}


def test_load_bundle_read_model_uses_the_loader_contract() -> None:
    bundle = _build_bundle()
    loader = FakeBundleLoader(bundle)
    bundle_path = Path("results/bundle.json")

    read_model = load_bundle_read_model(bundle_path=bundle_path, loader=loader)

    assert loader.paths == [bundle_path]
    assert read_model.bundle_id == bundle.bundle_id
    assert read_model.artifact_locations["runtime_root"] == f"var/runtime/nautilus/{bundle.run_spec.run_id}"


def test_load_bundle_dashboard_read_model_uses_the_loader_contract(tmp_path: Path) -> None:
    positions_path = _write_positions(
        tmp_path / "positions_report.parquet",
        [
            {
                "is_snapshot": False,
                "ts_closed": "2024-01-01T00:00:00Z",
                "realized_return": 0.01,
                "entry": "BUY",
            },
        ],
    )
    bundle = _with_artifacts(
        _build_bundle(),
        artifact_locations={"positions_report": positions_path.as_posix()},
    )
    loader = FakeBundleLoader(bundle)
    bundle_path = Path("results/bundle.json")

    read_model = load_bundle_dashboard_read_model(bundle_path=bundle_path, loader=loader)

    assert loader.paths == [bundle_path]
    assert read_model.bundle_id == bundle.bundle_id
    assert read_model.equity.status == "available"


def test_dashboard_equity_compounds_closed_position_returns(tmp_path: Path) -> None:
    positions_path = _write_positions(
        tmp_path / "positions_report.parquet",
        [
            {
                "is_snapshot": False,
                "ts_closed": "2024-01-01T00:00:00Z",
                "realized_return": 0.10,
                "entry": "BUY",
            },
            {
                "is_snapshot": False,
                "ts_closed": "2024-01-02T00:00:00Z",
                "realized_return": -0.05,
                "entry": "SELL",
            },
        ],
    )
    bundle = _with_artifacts(
        _build_bundle(),
        artifact_locations={"positions_report": positions_path.as_posix()},
    )

    dashboard = build_bundle_dashboard_read_model(bundle)

    assert dashboard.equity.status == "available"
    assert [point.value for point in dashboard.equity.points] == pytest.approx(
        [275000.0, 261250.0]
    )
    assert dashboard.equity.full_point_count == 2
    assert [series.key for series in dashboard.equity.series] == ["combined", "long", "short"]


def test_dashboard_sums_duplicate_position_close_timestamps_deterministically(tmp_path: Path) -> None:
    positions_path = _write_positions(
        tmp_path / "positions_report.parquet",
        [
            {
                "is_snapshot": False,
                "ts_closed": "2024-01-01T00:00:00Z",
                "realized_return": 0.10,
                "entry": "BUY",
            },
            {
                "is_snapshot": False,
                "ts_closed": "2024-01-01T00:00:00Z",
                "realized_return": 0.10,
                "entry": "SELL",
            },
            {
                "is_snapshot": False,
                "ts_closed": "2024-01-02T00:00:00Z",
                "realized_return": 0.00,
                "entry": "BUY",
            },
        ],
    )
    bundle = _with_artifacts(
        _build_bundle(),
        artifact_locations={"positions_report": positions_path.as_posix()},
    )

    dashboard = build_bundle_dashboard_read_model(bundle)

    assert dashboard.equity.full_point_count == 2
    assert dashboard.equity.points[0].value == pytest.approx(300000.0)
    trade_count = next(item for item in dashboard.stats.items if item.key == "trade_count")
    assert trade_count.display_value == "3"


def test_dashboard_skips_non_finite_equity_without_poisoning_subsequent_points(
    tmp_path: Path,
) -> None:
    positions_path = _write_positions(
        tmp_path / "positions_report.parquet",
        [
            {
                "is_snapshot": False,
                "ts_closed": "2024-01-01T00:00:00Z",
                "realized_return": 0.10,
                "entry": "BUY",
            },
            {
                "is_snapshot": False,
                "ts_closed": "2024-01-02T00:00:00Z",
                "realized_return": 1e308,
                "entry": "BUY",
            },
            {
                "is_snapshot": False,
                "ts_closed": "2024-01-03T00:00:00Z",
                "realized_return": 0.10,
                "entry": "BUY",
            },
        ],
    )
    bundle = _with_artifacts(
        _build_bundle(),
        artifact_locations={"positions_report": positions_path.as_posix()},
    )

    dashboard = build_bundle_dashboard_read_model(bundle)

    assert dashboard.equity.status == "available"
    assert [point.timestamp_utc for point in dashboard.equity.points] == [
        "2024-01-01T00:00:00Z",
        "2024-01-03T00:00:00Z",
    ]
    assert [point.value for point in dashboard.equity.points] == pytest.approx(
        [275000.0, 302500.0]
    )


def test_dashboard_drawdown_is_relative_to_running_peak_seeded_by_capital_base(
    tmp_path: Path,
) -> None:
    positions_path = _write_positions(
        tmp_path / "positions_report.parquet",
        [
            {
                "is_snapshot": False,
                "ts_closed": "2024-01-01T00:00:00Z",
                "realized_return": 0.10,
                "entry": "BUY",
            },
            {
                "is_snapshot": False,
                "ts_closed": "2024-01-02T00:00:00Z",
                "realized_return": -0.20,
                "entry": "SELL",
            },
            {
                "is_snapshot": False,
                "ts_closed": "2024-01-03T00:00:00Z",
                "realized_return": 0.10,
                "entry": "BUY",
            },
        ],
    )
    bundle = _with_artifacts(
        _build_bundle(),
        artifact_locations={"positions_report": positions_path.as_posix()},
    )

    dashboard = build_bundle_dashboard_read_model(bundle)

    assert [point.value for point in dashboard.drawdown.points] == pytest.approx(
        [0.0, -0.20, -0.12]
    )


def test_dashboard_positions_artifact_empty_and_error_states(tmp_path: Path) -> None:
    missing_bundle = _with_artifacts(_build_bundle())
    unreadable_path = tmp_path / "not_a_parquet.parquet"
    unreadable_path.write_text("not parquet", encoding="utf-8")
    unreadable_bundle = _with_artifacts(
        _build_bundle(),
        artifact_locations={"positions_report": unreadable_path.as_posix()},
    )
    malformed_path = _write_parquet(
        tmp_path / "malformed_positions.parquet",
        pd.DataFrame({"ts_closed": ["2024-01-01T00:00:00Z"]}),
    )
    malformed_bundle = _with_artifacts(
        _build_bundle(),
        artifact_locations={"positions_report": malformed_path.as_posix()},
    )

    missing_dashboard = build_bundle_dashboard_read_model(missing_bundle)
    unreadable_dashboard = build_bundle_dashboard_read_model(unreadable_bundle)
    malformed_dashboard = build_bundle_dashboard_read_model(malformed_bundle)

    assert missing_dashboard.equity.status == "empty"
    assert "location is not present" in missing_dashboard.equity.reason
    assert unreadable_dashboard.equity.status == "error"
    assert "failed to read positions_report" in unreadable_dashboard.equity.reason
    assert malformed_dashboard.equity.status == "error"
    assert "missing required columns" in malformed_dashboard.equity.reason


def test_dashboard_sanitizes_non_finite_values_for_json(tmp_path: Path) -> None:
    positions_path = _write_positions(
        tmp_path / "positions_report.parquet",
        [
            {
                "is_snapshot": False,
                "ts_closed": "bad timestamp",
                "realized_return": 0.10,
                "entry": "BUY",
            },
            {
                "is_snapshot": False,
                "ts_closed": "2024-01-01T00:00:00Z",
                "realized_return": math.inf,
                "entry": "BUY",
            },
        ],
    )
    bundle = _with_artifacts(
        _build_bundle(),
        artifact_locations={"positions_report": positions_path.as_posix()},
        summary={
            "net_return": math.nan,
            "max_drawdown": math.inf,
            "sharpe_after_costs": -math.inf,
            "total_pnl": 125.0,
        },
    )

    dashboard = build_bundle_dashboard_read_model(bundle)
    payload = dashboard.model_dump_json()

    assert "NaN" not in payload
    assert "Infinity" not in payload
    assert dashboard.equity.status == "empty"
    assert next(item for item in dashboard.stats.items if item.key == "net_return").value is None
    assert next(item for item in dashboard.stats.items if item.key == "trade_count").value == 0.0


def test_dashboard_stats_use_core_metric_order_and_closed_positions(tmp_path: Path) -> None:
    positions_path = _write_positions(
        tmp_path / "positions_report.parquet",
        [
            {
                "is_snapshot": False,
                "ts_closed": "2024-01-01T00:00:00Z",
                "realized_return": 0.10,
                "entry": "BUY",
            },
            {
                "is_snapshot": False,
                "ts_closed": "2024-01-02T00:00:00Z",
                "realized_return": -0.05,
                "entry": "SELL",
            },
            {
                "is_snapshot": False,
                "ts_closed": "2024-01-03T00:00:00Z",
                "realized_return": 0.00,
                "entry": "BUY",
            },
            {
                "is_snapshot": True,
                "ts_closed": "2024-01-04T00:00:00Z",
                "realized_return": 0.50,
                "entry": "BUY",
            },
            {
                "is_snapshot": False,
                "ts_closed": pd.NaT,
                "realized_return": 0.50,
                "entry": "BUY",
            },
        ],
    )
    fills_path = _write_parquet(
        tmp_path / "fills_report.parquet",
        pd.DataFrame({"side": ["BUY", "SELL", "BUY", "SELL", "BUY"]}),
    )
    orders_path = _write_parquet(
        tmp_path / "orders_report.parquet",
        pd.DataFrame({"id": [1, 2]}),
    )
    account_path = _write_parquet(
        tmp_path / "account_report.parquet",
        pd.DataFrame({"equity": [250000.0, 251500.0]}),
    )
    bundle = _with_artifacts(
        _build_bundle(),
        artifact_locations={
            "positions_report": positions_path.as_posix(),
            "fills_report": fills_path.as_posix(),
            "orders_report": orders_path.as_posix(),
            "account_report": account_path.as_posix(),
        },
        summary={"sharpe_after_costs": 1.25, "total_pnl": 1500.0},
    )

    keys = _stat_keys(bundle)

    assert keys == [
        "net_return",
        "max_drawdown",
        "sharpe",
        "trade_count",
        "win_rate",
        "profit_factor",
        "avg_win_avg_loss",
        "expectancy",
    ]
    dashboard = build_bundle_dashboard_read_model(bundle)
    stats = {item.key: item for item in dashboard.stats.items}
    assert stats["trade_count"].display_value == "3"
    assert stats["win_rate"].value == pytest.approx(0.5)
    assert stats["profit_factor"].value == pytest.approx(2.0)
    assert stats["avg_win_avg_loss"].display_value == "10.00% / 5.00%"
    assert stats["expectancy"].value == pytest.approx(0.025)


def test_dashboard_breakeven_trades_do_not_distort_win_loss_stats(tmp_path: Path) -> None:
    positions_path = _write_positions(
        tmp_path / "positions_report.parquet",
        [
            {
                "is_snapshot": False,
                "ts_closed": "2024-01-01T00:00:00Z",
                "realized_return": 0.00,
                "entry": "BUY",
            },
            {
                "is_snapshot": False,
                "ts_closed": "2024-01-02T00:00:00Z",
                "realized_return": 0.03,
                "entry": "BUY",
            },
            {
                "is_snapshot": False,
                "ts_closed": "2024-01-03T00:00:00Z",
                "realized_return": -0.01,
                "entry": "SELL",
            },
        ],
    )
    dashboard = build_bundle_dashboard_read_model(
        _with_artifacts(
            _build_bundle(),
            artifact_locations={"positions_report": positions_path.as_posix()},
        )
    )

    stats = {item.key: item for item in dashboard.stats.items}
    assert stats["trade_count"].display_value == "3"
    assert stats["win_rate"].value == pytest.approx(0.5)
    assert stats["profit_factor"].value == pytest.approx(3.0)
    assert stats["avg_win_avg_loss"].display_value == "3.00% / 1.00%"


def test_dashboard_profit_factor_unbounded_is_json_safe(tmp_path: Path) -> None:
    positions_path = _write_positions(
        tmp_path / "positions_report.parquet",
        [
            {
                "is_snapshot": False,
                "ts_closed": "2024-01-01T00:00:00Z",
                "realized_return": 0.02,
                "entry": "BUY",
            },
            {
                "is_snapshot": False,
                "ts_closed": "2024-01-02T00:00:00Z",
                "realized_return": 0.03,
                "entry": "BUY",
            },
        ],
    )
    dashboard = build_bundle_dashboard_read_model(
        _with_artifacts(
            _build_bundle(),
            artifact_locations={"positions_report": positions_path.as_posix()},
        )
    )

    profit_factor = next(item for item in dashboard.stats.items if item.key == "profit_factor")
    assert profit_factor.value is None
    assert profit_factor.display_value == "unbounded"
    assert "Infinity" not in dashboard.model_dump_json()


def test_dashboard_expectancy_keeps_small_negative_precision(tmp_path: Path) -> None:
    positions_path = _write_positions(
        tmp_path / "positions_report.parquet",
        [
            {
                "is_snapshot": False,
                "ts_closed": "2024-01-01T00:00:00Z",
                "realized_return": 0.00010,
                "entry": "BUY",
            },
            {
                "is_snapshot": False,
                "ts_closed": "2024-01-02T00:00:00Z",
                "realized_return": -0.00021,
                "entry": "SELL",
            },
        ],
    )
    dashboard = build_bundle_dashboard_read_model(
        _with_artifacts(
            _build_bundle(),
            artifact_locations={"positions_report": positions_path.as_posix()},
        )
    )

    expectancy = next(item for item in dashboard.stats.items if item.key == "expectancy")
    assert expectancy.value == pytest.approx(-0.000055)
    assert expectancy.display_value == "-0.0055%"


def test_dashboard_side_equity_uses_single_leg_entry_direction(tmp_path: Path) -> None:
    positions_path = _write_positions(
        tmp_path / "positions_report.parquet",
        [
            {
                "is_snapshot": False,
                "ts_closed": "2024-01-01T00:00:00Z",
                "realized_return": 0.10,
                "entry": "BUY",
            },
            {
                "is_snapshot": False,
                "ts_closed": "2024-01-02T00:00:00Z",
                "realized_return": -0.05,
                "entry": "SELL",
            },
        ],
    )
    dashboard = build_bundle_dashboard_read_model(
        _with_artifacts(
            _build_bundle(),
            artifact_locations={"positions_report": positions_path.as_posix()},
        )
    )

    series_by_key = {series.key: series for series in dashboard.equity.series}
    assert [point.value for point in series_by_key["combined"].points] == pytest.approx(
        [275000.0, 261250.0]
    )
    assert [point.value for point in series_by_key["long"].points] == pytest.approx(
        [275000.0, 275000.0]
    )
    assert [point.value for point in series_by_key["short"].points] == pytest.approx(
        [250000.0, 237500.0]
    )


def test_dashboard_statarb_side_equity_uses_spread_weights(tmp_path: Path) -> None:
    positions_path = _write_positions(
        tmp_path / "positions_report.parquet",
        [
            {
                "strategy_id": "spread",
                "instrument_id": "ES.CME",
                "is_snapshot": False,
                "ts_closed": "2024-01-01T00:00:00Z",
                "realized_return": 0.01,
                "entry": "BUY",
            },
            {
                "strategy_id": "spread",
                "instrument_id": "NQ.CME",
                "is_snapshot": False,
                "ts_closed": "2024-01-01T00:00:00Z",
                "realized_return": 0.02,
                "entry": "SELL",
            },
            {
                "strategy_id": "spread",
                "instrument_id": "ES.CME",
                "is_snapshot": False,
                "ts_closed": "2024-01-02T00:00:00Z",
                "realized_return": -0.04,
                "entry": "SELL",
            },
            {
                "strategy_id": "spread",
                "instrument_id": "NQ.CME",
                "is_snapshot": False,
                "ts_closed": "2024-01-02T00:00:00Z",
                "realized_return": 0.01,
                "entry": "BUY",
            },
        ],
    )
    dashboard = build_bundle_dashboard_read_model(
        _with_artifacts(
            _build_statarb_bundle(),
            artifact_locations={"positions_report": positions_path.as_posix()},
        )
    )

    series_by_key = {series.key: series for series in dashboard.equity.series}
    assert [point.value for point in series_by_key["long"].points] == pytest.approx(
        [257500.0, 257500.0]
    )
    assert [point.value for point in series_by_key["short"].points] == pytest.approx(
        [250000.0, 242500.0]
    )


def test_dashboard_heatmap_is_unavailable_without_stable_strategy_series() -> None:
    dashboard = build_bundle_dashboard_read_model(_with_artifacts(_build_bundle()))

    assert dashboard.heatmap.status == "empty"
    assert dashboard.heatmap.metric_kind == "unavailable"
    assert dashboard.heatmap.metric_label == "Unavailable"


def test_dashboard_heatmap_labels_realized_return_and_pnl_proxy_correlation(
    tmp_path: Path,
) -> None:
    timestamps = pd.date_range("2024-01-01", periods=3, freq="1h", tz="UTC")
    return_positions = pd.DataFrame(
        {
            "strategy_id": ["A", "A", "A", "B", "B", "B"],
            "timestamp_utc": list(timestamps) * 2,
            "realized_return": [0.01, 0.02, -0.01, -0.01, 0.01, 0.02],
        }
    )
    pnl_positions = pd.DataFrame(
        {
            "strategy_id": ["A", "A", "A", "B", "B", "B"],
            "timestamp_utc": list(timestamps) * 2,
            "realized_pnl": ["10 USD", "20 USD", "-5 USD", "-7 USD", "11 USD", "18 USD"],
        }
    )
    return_positions_path = _write_parquet(tmp_path / "return_positions.parquet", return_positions)
    pnl_positions_path = _write_parquet(tmp_path / "pnl_positions.parquet", pnl_positions)
    return_dashboard = build_bundle_dashboard_read_model(
        _with_artifacts(
            _build_bundle(),
            artifact_locations={"positions_report": return_positions_path.as_posix()},
        )
    )
    pnl_dashboard = build_bundle_dashboard_read_model(
        _with_artifacts(
            _build_bundle(),
            artifact_locations={"positions_report": pnl_positions_path.as_posix()},
        )
    )

    assert return_dashboard.heatmap.status == "available"
    assert return_dashboard.heatmap.metric_kind == "realized_return"
    assert return_dashboard.heatmap.metric_label == "Realized return correlation"
    assert pnl_dashboard.heatmap.status == "available"
    assert pnl_dashboard.heatmap.metric_kind == "realized_pnl_proxy"
    assert pnl_dashboard.heatmap.metric_label == "Realized PnL proxy correlation"


def test_dashboard_heatmap_excludes_insufficient_overlap_and_constant_series(
    tmp_path: Path,
) -> None:
    positions_path = _write_parquet(
        tmp_path / "positions_report.parquet",
        pd.DataFrame(
            {
                "strategy_id": [
                    "A",
                    "A",
                    "A",
                    "A",
                    "B",
                    "B",
                    "B",
                    "B",
                    "C",
                    "C",
                    "C",
                    "C",
                    "D",
                    "D",
                ],
                "timestamp_utc": [
                    "2024-01-01T00:00:00Z",
                    "2024-01-01T01:00:00Z",
                    "2024-01-01T02:00:00Z",
                    "2024-01-01T03:00:00Z",
                    "2024-01-01T00:00:00Z",
                    "2024-01-01T01:00:00Z",
                    "2024-01-01T02:00:00Z",
                    "2024-01-01T03:00:00Z",
                    "2024-01-01T00:00:00Z",
                    "2024-01-01T01:00:00Z",
                    "2024-01-01T02:00:00Z",
                    "2024-01-01T03:00:00Z",
                    "2024-01-01T00:00:00Z",
                    "2024-01-01T01:00:00Z",
                ],
                "realized_return": [
                    0.01,
                    0.03,
                    -0.02,
                    0.04,
                    -0.01,
                    0.02,
                    0.01,
                    -0.03,
                    0.01,
                    0.01,
                    0.01,
                    0.01,
                    0.02,
                    -0.01,
                ],
            }
        ),
    )
    bundle = _with_artifacts(
        _build_bundle(),
        artifact_locations={"positions_report": positions_path.as_posix()},
    )

    dashboard = build_bundle_dashboard_read_model(bundle)

    assert dashboard.heatmap.status == "available"
    assert dashboard.heatmap.strategy_ids == ("A", "B")
    assert {(cell.row_strategy_id, cell.column_strategy_id) for cell in dashboard.heatmap.cells} == {
        ("A", "A"),
        ("A", "B"),
        ("B", "A"),
        ("B", "B"),
    }


def test_dashboard_heatmap_drops_missing_strategy_ids(tmp_path: Path) -> None:
    timestamps = pd.date_range("2024-01-01", periods=3, freq="1h", tz="UTC")
    positions_path = _write_parquet(
        tmp_path / "positions_report.parquet",
        pd.DataFrame(
            {
                "strategy_id": [
                    "A",
                    "A",
                    "A",
                    "B",
                    "B",
                    "B",
                    pd.NA,
                    pd.NA,
                    pd.NA,
                ],
                "timestamp_utc": list(timestamps) * 3,
                "realized_return": [
                    0.01,
                    0.03,
                    -0.02,
                    -0.01,
                    0.02,
                    0.01,
                    0.50,
                    -0.50,
                    0.25,
                ],
            }
        ),
    )
    bundle = _with_artifacts(
        _build_bundle(),
        artifact_locations={"positions_report": positions_path.as_posix()},
    )

    dashboard = build_bundle_dashboard_read_model(bundle)

    assert dashboard.heatmap.status == "available"
    assert dashboard.heatmap.strategy_ids == ("A", "B")
    assert "<NA>" not in dashboard.model_dump_json()
