from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from backtest_engine.application.calibration import (
    PublishedCalibrationSymbol,
    SpreadCalibrationPublicationResult,
)
from backtest_engine.core.enums import RunKind
from backtest_engine.interfaces.cli.calibration.rendering import format_spread_success


def test_spread_success_rendering_includes_hash_snippet_and_backtest_handoff() -> None:
    result = _publication_result()

    output = format_spread_success(
        result,
        spec_path=Path("run_profiles/fx_single_asset.yaml"),
        run_kind=RunKind.SINGLE,
    )

    assert output.splitlines() == [
        "OK spread-calibration",
        "calibration_id: spread-calibration-001",
        "profile_id: default_execution_costs",
        "estimator_timeframe: 1m",
        "target_timeframe: 1h",
        "output_dir: var/runtime/calibration/spread-calibration-001/target-1h",
        (
            "execution_costs_yaml: "
            "var/runtime/calibration/spread-calibration-001/target-1h/execution_costs.yaml"
        ),
        (
            "calibration_report_json: "
            "var/runtime/calibration/spread-calibration-001/target-1h/calibration_report.json"
        ),
        (
            "calibration_panel_parquet: "
            "var/runtime/calibration/spread-calibration-001/target-1h/calibration_panel.parquet"
        ),
        "diagnostic_pngs:",
        (
            "  var/runtime/calibration/spread-calibration-001/target-1h/"
            "calibration_diagnostics_summary.png"
        ),
        (
            "  var/runtime/calibration/spread-calibration-001/target-1h/"
            "calibration_diagnostics_EURUSD.png"
        ),
        f"execution_costs_config_hash: {'a' * 64}",
        "published_symbols:",
        "  EURUSD",
        "run_profile_snippet:",
        "  execution_policy:",
        "    execution_costs:",
        "      profile_id: default_execution_costs",
        f"      config_content_hash: {'a' * 64}",
        "backtest_handoff:",
        "  python -m backtest_engine.interfaces.cli.backtest single \\",
        "    --spec run_profiles/fx_single_asset.yaml \\",
        (
            "    --execution-costs-path "
            "var/runtime/calibration/spread-calibration-001/target-1h/execution_costs.yaml"
        ),
    ]


def _publication_result() -> SpreadCalibrationPublicationResult:
    output_dir = Path("var/runtime/calibration/spread-calibration-001/target-1h")
    return SpreadCalibrationPublicationResult(
        calibration_id="spread-calibration-001",
        profile_id="default_execution_costs",
        estimator_timeframe="1m",
        target_timeframe="1h",
        output_dir=output_dir,
        execution_costs_path=output_dir / "execution_costs.yaml",
        calibration_report_path=output_dir / "calibration_report.json",
        calibration_panel_path=output_dir / "calibration_panel.parquet",
        diagnostic_artifact_paths=(
            output_dir / "calibration_diagnostics_summary.png",
            output_dir / "calibration_diagnostics_EURUSD.png",
        ),
        execution_costs_config_hash="a" * 64,
        published_symbols=(
            PublishedCalibrationSymbol(
                symbol="EURUSD",
                base_half_spread_price=Decimal("0.00005"),
                min_half_spread_price=Decimal("0.00001"),
                max_half_spread_price=Decimal("0.00050"),
                volatility_weight=Decimal("0"),
                liquidity_weight=Decimal("0"),
                train_row_count=10,
                holdout_row_count=5,
                train_max_clip_rate=0.0,
                holdout_max_clip_rate=0.0,
            ),
        ),
        train_row_count=10,
        holdout_row_count=5,
        purged_row_count=1,
    )
