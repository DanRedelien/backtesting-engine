from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from backtest_engine.infrastructure.nautilus.catalogs import CatalogReference
from backtest_engine.infrastructure.nautilus.reports import NautilusReportWriter
from backtest_engine.infrastructure.nautilus.run_spec_compiler import (
    NautilusDataSpec,
    NautilusImportableModelSpec,
    NautilusRunSpec,
    NautilusVenueSpec,
)
from backtest_engine.infrastructure.nautilus.synthetic_fill_diagnostics import (
    SYNTHETIC_FILL_DIAGNOSTICS_ARTIFACT_KEY,
    SYNTHETIC_FILL_DIAGNOSTICS_FILENAME,
    SyntheticFillDiagnostics,
    build_synthetic_fill_diagnostics,
)


def test_synthetic_fill_diagnostics_schema_json_round_trip(tmp_path: Path) -> None:
    compiled = _dynamic_compiled_spec(tmp_path)
    fills = _fills_report(("101.25", "101.26"))
    diagnostics = build_synthetic_fill_diagnostics(
        compiled_spec=compiled,
        fills_report=fills,
        orders_report=pd.DataFrame(),
        report_locations={"fills_report": (tmp_path / "fills.parquet").as_posix()},
        generated_at_utc=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )

    payload = json.loads(diagnostics.model_dump_json())
    reloaded = SyntheticFillDiagnostics.model_validate(payload)

    assert reloaded.schema_version == "synthetic_fill_diagnostics.v1"
    assert reloaded.run_id == "run-diagnostics"
    assert reloaded.policy_mode == "dynamic_spread_policy"
    assert reloaded.diagnostics_status == "available"
    assert reloaded.classification_counts["primary"]["dynamic_spread_fill"] == 2
    assert reloaded.classification_counts["flags"]["outside_ohlc"] == 1
    assert reloaded.classification_rates["outside_ohlc"].denominator == 2
    assert reloaded.classification_rates["outside_ohlc"].rate == 0.5


def test_synthetic_fill_diagnostics_not_applicable_for_no_policy(tmp_path: Path) -> None:
    compiled = _base_compiled_spec(tmp_path, venues=(_no_policy_venue(),))
    diagnostics = build_synthetic_fill_diagnostics(
        compiled_spec=compiled,
        fills_report=_fills_report(("101.26",)),
        orders_report=pd.DataFrame(),
        report_locations={},
        generated_at_utc=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )

    assert diagnostics.diagnostics_status == "not_applicable"
    assert diagnostics.reason == "no_execution_policy"
    assert diagnostics.feature_coverage_summary == {}


def test_synthetic_fill_diagnostics_not_applicable_for_static_policy(
    tmp_path: Path,
) -> None:
    compiled = _base_compiled_spec(tmp_path, venues=(_static_policy_venue(),))
    diagnostics = build_synthetic_fill_diagnostics(
        compiled_spec=compiled,
        fills_report=_fills_report(("101.26",)),
        orders_report=pd.DataFrame(),
        report_locations={},
        generated_at_utc=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )

    assert diagnostics.diagnostics_status == "not_applicable"
    assert diagnostics.reason == "no_dynamic_spread_profile"
    assert diagnostics.feature_coverage_summary == {}


def test_synthetic_fill_diagnostics_reports_missing_inputs_without_fabricated_zero(
    tmp_path: Path,
) -> None:
    compiled = _dynamic_compiled_spec(tmp_path, include_bar_path=False)
    diagnostics = build_synthetic_fill_diagnostics(
        compiled_spec=compiled,
        fills_report=_fills_report(("101.26",)),
        orders_report=pd.DataFrame(),
        report_locations={},
        generated_at_utc=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )

    assert diagnostics.diagnostics_status == "unavailable"
    assert diagnostics.reason == "all_dynamic_fills_missing_ohlc"
    assert "normalized_bar_data.ES.CME.path" in diagnostics.missing_required_columns
    assert diagnostics.classification_counts["primary"]["dynamic_spread_fill"] == 1
    assert diagnostics.classification_counts["flags"]["missing_ohlc"] == 1
    assert diagnostics.classification_rates["missing_ohlc"].numerator == 1
    assert diagnostics.classification_rates["missing_ohlc"].denominator == 1


def test_synthetic_fill_diagnostics_unavailable_when_classification_columns_missing(
    tmp_path: Path,
) -> None:
    compiled = _dynamic_compiled_spec(tmp_path)
    fills = pd.DataFrame(
        {
            "last_px": ["101.26"],
            "ts_event": [pd.Timestamp("2024-01-01T00:00:00Z")],
        }
    )

    diagnostics = build_synthetic_fill_diagnostics(
        compiled_spec=compiled,
        fills_report=fills,
        orders_report=pd.DataFrame(),
        report_locations={},
        generated_at_utc=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )

    assert diagnostics.diagnostics_status == "unavailable"
    assert diagnostics.reason == "missing_required_fill_columns"
    assert "fills_report.instrument_id" in diagnostics.missing_required_columns
    assert "fills_report.order_type" in diagnostics.missing_required_columns
    assert diagnostics.classification_rates["dynamic_spread_fill"].denominator == 0
    assert diagnostics.classification_rates["dynamic_spread_fill"].rate is None


def test_synthetic_fill_diagnostics_unavailable_when_row_values_are_unclassifiable(
    tmp_path: Path,
) -> None:
    compiled = _dynamic_compiled_spec(tmp_path)
    fills = pd.DataFrame(
        {
            "instrument_id": [None],
            "order_type": ["market"],
            "last_px": ["101.26"],
            "ts_event": [pd.Timestamp("2024-01-01T00:00:00Z")],
        }
    )

    diagnostics = build_synthetic_fill_diagnostics(
        compiled_spec=compiled,
        fills_report=fills,
        orders_report=pd.DataFrame(),
        report_locations={},
        generated_at_utc=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )

    assert diagnostics.diagnostics_status == "unavailable"
    assert diagnostics.reason == "no_classifiable_fill_rows"
    assert diagnostics.classification_counts["primary"]["unclassified"] == 1
    assert diagnostics.classification_counts["flags"]["missing_ohlc"] == 0
    assert diagnostics.classification_rates["missing_ohlc"].numerator == 0
    assert diagnostics.classification_rates["missing_ohlc"].denominator == 0


def test_synthetic_fill_diagnostics_partial_when_some_dynamic_features_missing(
    tmp_path: Path,
) -> None:
    compiled = _dynamic_compiled_spec(tmp_path)
    fills = pd.DataFrame(
        {
            "instrument_id": ["ES.CME", "ES.CME"],
            "order_type": ["market", "market"],
            "last_px": ["101.00", "101.00"],
            "ts_event": [
                pd.Timestamp("2024-01-01T00:00:00Z"),
                pd.Timestamp("2024-01-01T00:30:00Z"),
            ],
        }
    )

    diagnostics = build_synthetic_fill_diagnostics(
        compiled_spec=compiled,
        fills_report=fills,
        orders_report=pd.DataFrame(),
        report_locations={},
        generated_at_utc=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )

    assert diagnostics.diagnostics_status == "partial"
    assert diagnostics.reason == "row_level_diagnostics_inputs_missing"
    assert diagnostics.classification_counts["flags"]["dynamic_feature_covered"] == 1
    assert diagnostics.classification_counts["flags"]["dynamic_feature_missing"] == 1
    assert diagnostics.classification_counts["flags"]["missing_ohlc"] == 1
    assert diagnostics.classification_rates["dynamic_feature_missing"].denominator == 2
    assert diagnostics.classification_rates["missing_ohlc"].denominator == 2


def test_synthetic_fill_diagnostics_unavailable_when_feature_artifact_unavailable(
    tmp_path: Path,
) -> None:
    compiled = _dynamic_compiled_spec(tmp_path, include_feature_table=False)
    diagnostics = build_synthetic_fill_diagnostics(
        compiled_spec=compiled,
        fills_report=_fills_report(("101.00",)),
        orders_report=pd.DataFrame(),
        report_locations={},
        generated_at_utc=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )

    feature_summary = diagnostics.feature_coverage_summary["ES.CME"]
    assert isinstance(feature_summary, dict)
    assert diagnostics.diagnostics_status == "unavailable"
    assert diagnostics.reason == "all_dynamic_fills_missing_feature_coverage"
    assert feature_summary["feature_artifact_status"] == "unavailable"
    assert diagnostics.classification_counts["flags"]["dynamic_feature_missing"] == 1


def test_synthetic_fill_diagnostics_uses_inclusive_tick_size_ohlc_boundary(
    tmp_path: Path,
) -> None:
    compiled = _dynamic_compiled_spec(tmp_path)
    diagnostics = build_synthetic_fill_diagnostics(
        compiled_spec=compiled,
        fills_report=_fills_report(("101.25",)),
        orders_report=pd.DataFrame(),
        report_locations={},
        generated_at_utc=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )

    assert diagnostics.classification_counts["flags"]["outside_ohlc"] == 0
    assert diagnostics.outside_ohlc_examples_sample == ()


def test_report_writer_persists_synthetic_fill_diagnostics_artifact(
    tmp_path: Path,
) -> None:
    compiled = _base_compiled_spec(tmp_path, venues=(_no_policy_venue(),))
    artifacts = NautilusReportWriter().persist(
        compiled_spec=compiled,
        run_result=_FakeRunResult(),
        engine=_FakeEngine(),
        runtime_sec=0.25,
    )

    diagnostics_path = Path(artifacts.report_locations[SYNTHETIC_FILL_DIAGNOSTICS_ARTIFACT_KEY])
    payload = json.loads(diagnostics_path.read_text(encoding="utf-8"))

    assert diagnostics_path == compiled.artifact_root / SYNTHETIC_FILL_DIAGNOSTICS_FILENAME
    assert payload["schema_version"] == "synthetic_fill_diagnostics.v1"
    assert payload["diagnostics_status"] == "not_applicable"


def _base_compiled_spec(
    tmp_path: Path,
    *,
    venues: tuple[NautilusVenueSpec, ...],
    include_bar_path: bool = True,
) -> NautilusRunSpec:
    bar_path = _write_bar_report(tmp_path) if include_bar_path else None
    return NautilusRunSpec(
        run_id="run-diagnostics",
        dataset_id="dataset-diagnostics",
        runtime_root=tmp_path / "runtime",
        artifact_root=tmp_path / "runtime" / "artifacts",
        annualization_policy="252d",
        catalog=CatalogReference(
            dataset_id="dataset-diagnostics",
            catalog_root=tmp_path / "catalogs",
        ),
        venues=venues,
        data=(
            NautilusDataSpec(
                catalog_root=tmp_path / "catalogs",
                instrument_id="ES.CME",
                bar_type="ES.CME-30-MINUTE-LAST-EXTERNAL",
                start_time_utc=datetime(2024, 1, 1, tzinfo=timezone.utc),
                end_time_utc=datetime(2024, 1, 2, tzinfo=timezone.utc),
                normalized_bar_data_path=bar_path,
            ),
        ),
        strategies=(),
        strategy_ids=(),
    )


def _dynamic_compiled_spec(
    tmp_path: Path,
    *,
    include_bar_path: bool = True,
    include_feature_table: bool = True,
) -> NautilusRunSpec:
    feature_table_path = (
        _write_feature_table(tmp_path)
        if include_feature_table
        else tmp_path / "missing_features.parquet"
    )
    venue = NautilusVenueSpec(
        name="CME",
        base_currency="USD",
        starting_balances=("100000 USD",),
        fill_model=_model_spec(
            {
                "instrument_profiles": {
                    "ES.CME": _instrument_profile_payload("log_linear_dynamic_half_spread"),
                },
                "dynamic_spread_features": {
                    "ES.CME": {"feature_table_path": feature_table_path.as_posix()},
                },
            },
        ),
    )
    return _base_compiled_spec(tmp_path, venues=(venue,), include_bar_path=include_bar_path)


def _static_policy_venue() -> NautilusVenueSpec:
    return NautilusVenueSpec(
        name="CME",
        base_currency="USD",
        starting_balances=("100000 USD",),
        fill_model=_model_spec(
            {
                "instrument_profiles": {
                    "ES.CME": _instrument_profile_payload("static_half_spread_price"),
                },
                "dynamic_spread_features": {},
            },
        ),
    )


def _no_policy_venue() -> NautilusVenueSpec:
    return NautilusVenueSpec(
        name="CME",
        base_currency="USD",
        starting_balances=("100000 USD",),
    )


def _model_spec(config: dict[str, Any]) -> NautilusImportableModelSpec:
    return NautilusImportableModelSpec(
        model_path="test:FillModel",
        config_path="test:Config",
        config=config,
    )


def _instrument_profile_payload(spread_model_name: str) -> dict[str, Any]:
    return {
        "instrument_id": "ES.CME",
        "metadata": {
            "symbol": "ES",
            "instrument_type": "FUTURES",
            "asset_class": "INDEX",
            "quote_currency": "USD",
            "tick_size": "0.25",
            "point_size": "1",
            "lot_size": "1",
            "multiplier": "50",
            "price_precision": 2,
        },
        "profile": {
            "symbol": "ES",
            "instrument_type": "FUTURES",
            "asset_class": "INDEX",
            "quote_currency": "USD",
            "commission_model": {"model": "fixed_per_contract"},
            "spread_model": {"model": spread_model_name},
            "slippage_model": {"model": "none_explicit"},
        },
    }


def _fills_report(prices: tuple[str, ...]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "instrument_id": ["ES.CME" for _ in prices],
            "order_type": ["market" for _ in prices],
            "last_px": list(prices),
            "ts_event": [pd.Timestamp("2024-01-01T00:00:00Z") for _ in prices],
        }
    )


def _write_bar_report(tmp_path: Path) -> Path:
    path = tmp_path / "bars.parquet"
    pd.DataFrame(
        {
            "ts_event_utc": [pd.Timestamp("2024-01-01T00:00:00Z")],
            "open": ["100.50"],
            "high": ["101.00"],
            "low": ["100.00"],
            "close": ["100.75"],
        }
    ).to_parquet(path, index=False)
    return path


def _write_feature_table(tmp_path: Path) -> Path:
    path = tmp_path / "features.parquet"
    pd.DataFrame(
        {
            "fill_timestamp_utc": [pd.Timestamp("2024-01-01T00:00:00Z")],
        }
    ).to_parquet(path, index=False)
    return path


class _FakeAnalyzer:
    def returns(self) -> pd.Series:
        return pd.Series([0.0], dtype=float)


class _FakePortfolio:
    analyzer = _FakeAnalyzer()


class _FakeTrader:
    def generate_account_report(self, _venue: object) -> pd.DataFrame:
        return pd.DataFrame({"equity": [100000.0]})

    def generate_positions_report(self) -> pd.DataFrame:
        return pd.DataFrame()

    def generate_orders_report(self) -> pd.DataFrame:
        return pd.DataFrame()

    def generate_order_fills_report(self) -> pd.DataFrame:
        return _fills_report(("101.25",))


class _FakeEngine:
    trader = _FakeTrader()
    portfolio = _FakePortfolio()


class _FakeRunResult:
    total_orders = 1
    total_positions = 0
    total_events = 1
    stats_pnls: dict[str, dict[str, float]] = {}
