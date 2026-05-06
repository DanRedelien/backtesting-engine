from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from backtest_engine.application.calibration import (
    PublishedCalibrationSymbol,
    SpreadCalibrationPublicationResult,
)
from backtest_engine.config.runtime import BacktestRunSpec, ExecutionWindow
from backtest_engine.core.enums import DatasetSource, RunKind
from backtest_engine.core.money import Money
from backtest_engine.domain.market.datasets import DatasetSpec
from backtest_engine.domain.strategy.specifications import (
    PortfolioStrategySpec,
    StrategyLegSpec,
    StrategySpec,
)
from backtest_engine.interfaces.cli.calibration import __main__ as calibration_main
from backtest_engine.interfaces.cli.run_spread_calibration import SpreadCalibrationCliCommand


class FakeMaterializer:
    pass


def test_calibration_cli_missing_subcommand_returns_usage_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        calibration_main,
        "build_calibration_dataset_materializer",
        _raise_if_materializer_is_built,
    )

    exit_code = calibration_main.main([])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "usage:" in captured.out
    assert "spread" in captured.out


def test_calibration_cli_spread_loads_profile_and_prints_handoff(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run_spec = _build_run_spec()
    materializer = FakeMaterializer()
    captured_commands: list[tuple[SpreadCalibrationCliCommand, object]] = []

    def fake_run_spread_calibration_cli(
        command: SpreadCalibrationCliCommand,
        materializer: object,
    ) -> SpreadCalibrationPublicationResult:
        captured_commands.append((command, materializer))
        return _publication_result()

    monkeypatch.setattr(calibration_main, "load_run_profile_spec", lambda path: run_spec)
    monkeypatch.setattr(
        calibration_main,
        "build_calibration_dataset_materializer",
        lambda: materializer,
    )
    monkeypatch.setattr(
        calibration_main,
        "run_spread_calibration_cli",
        fake_run_spread_calibration_cli,
    )

    exit_code = calibration_main.main(
        [
            "spread",
            "--spec",
            "run_profiles/fx_single_asset.yaml",
            "--estimator-timeframe",
            "1m",
            "--output-root",
            "var/runtime/calibration",
            "--requested-by",
            "operator",
            "--correlation-id",
            "calibration-001",
        ]
    )

    captured = capsys.readouterr()
    command, delegated_materializer = captured_commands[0]
    assert exit_code == 0
    assert delegated_materializer is materializer
    assert command.run_spec == run_spec
    assert command.spec_path == Path("run_profiles/fx_single_asset.yaml")
    assert command.estimator_timeframe == "1m"
    assert command.output_root == Path("var/runtime/calibration")
    assert command.requested_by == "operator"
    assert command.correlation_id == "calibration-001"
    assert "OK spread-calibration" in captured.out
    assert "execution_costs_yaml:" in captured.out
    assert "diagnostic_pngs:" in captured.out
    assert "calibration_diagnostics_summary.png" in captured.out
    assert f"config_content_hash: {'a' * 64}" in captured.out
    assert "--execution-costs-path" in captured.out


def _build_run_spec() -> BacktestRunSpec:
    return BacktestRunSpec(
        run_kind=RunKind.SINGLE,
        execution_window=ExecutionWindow(
            start_utc=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end_utc=datetime(2024, 2, 1, tzinfo=timezone.utc),
        ),
        dataset=DatasetSpec(
            source_system=DatasetSource.MT5,
            normalization_policy="nautilus_v1",
            schema_version="1",
            symbol_universe=("EURUSD",),
            timeframe="1h",
            dataset_version="2026-04-03",
        ),
        strategies=(
            PortfolioStrategySpec(
                slot_id="slot-1",
                weight_frac=1.0,
                strategy=StrategySpec(
                    strategy_id="fixture_single_strategy",
                    implementation_id="fixture_single_strategy",
                    policy_version="v1",
                ),
                legs=(StrategyLegSpec(symbol="EURUSD"),),
            ),
        ),
        capital_base=Money(amount=Decimal("100000"), currency="USD"),
    )


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


def _raise_if_materializer_is_built(*args: object, **kwargs: object) -> None:
    raise AssertionError("materializer should not be constructed")
