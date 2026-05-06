from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from backtest_engine.application.calibration import (
    PublishedCalibrationSymbol,
    SpreadCalibrationCommand,
    SpreadCalibrationPanelRow,
    SpreadCalibrationPublicationCommand,
    SpreadCalibrationPublicationResult,
    SpreadCalibrationResult,
    SpreadCalibrationSymbolSummary,
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
from backtest_engine.infrastructure.data.parquet_normalizer import MaterializedDataset
from backtest_engine.interfaces.cli.run_spread_calibration import (
    SpreadCalibrationCliCommand,
    run_spread_calibration_cli,
)


class FakeMaterializer:
    def __init__(self) -> None:
        self.datasets: list[DatasetSpec] = []

    def materialize(self, dataset: DatasetSpec) -> MaterializedDataset:
        self.datasets.append(dataset)
        return MaterializedDataset(
            dataset=dataset,
            dataset_root=Path("var/data/datasets") / dataset.dataset_id,
            manifest_path=Path("var/data/datasets") / dataset.dataset_id / "dataset_manifest.json",
            artifacts=(),
        )


def test_spread_calibration_cli_materializes_estimator_timeframe_and_publishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_spec = _build_run_spec()
    materializer = FakeMaterializer()
    captured_panel_commands: list[SpreadCalibrationCommand] = []
    captured_publication_commands: list[SpreadCalibrationPublicationCommand] = []

    def fake_build_spread_calibration_panel(
        command: SpreadCalibrationCommand,
    ) -> SpreadCalibrationResult:
        captured_panel_commands.append(command)
        return _calibration_result()

    def fake_publish_spread_calibration(
        command: SpreadCalibrationPublicationCommand,
    ) -> SpreadCalibrationPublicationResult:
        captured_publication_commands.append(command)
        return _publication_result()

    monkeypatch.setattr(
        "backtest_engine.interfaces.cli.run_spread_calibration.build_spread_calibration_panel",
        fake_build_spread_calibration_panel,
    )
    monkeypatch.setattr(
        "backtest_engine.interfaces.cli.run_spread_calibration.publish_spread_calibration",
        fake_publish_spread_calibration,
    )

    result = run_spread_calibration_cli(
        command=SpreadCalibrationCliCommand(
            run_spec=run_spec,
            spec_path=Path("run_profiles/fx_single_asset.yaml"),
            estimator_timeframe="M1",
            output_root=Path("custom/calibration"),
            requested_by="operator",
            correlation_id="calibration-001",
        ),
        materializer=materializer,
    )

    assert result.execution_costs_config_hash == "a" * 64
    assert materializer.datasets[0].timeframe == "1m"
    assert materializer.datasets[0].symbol_universe == run_spec.dataset.symbol_universe
    assert materializer.datasets[0].dataset_version == run_spec.dataset.dataset_version
    panel_command = captured_panel_commands[0]
    assert panel_command.estimator_timeframe == "1m"
    assert panel_command.calibration_start_utc == run_spec.execution_window.start_utc
    assert panel_command.calibration_end_utc == run_spec.execution_window.end_utc
    assert panel_command.requested_by == "operator"
    assert panel_command.correlation_id == "calibration-001"
    publication_command = captured_publication_commands[0]
    assert publication_command.target_timeframe == "1h"
    assert publication_command.output_root == Path("custom/calibration")


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


def _calibration_result() -> SpreadCalibrationResult:
    row = _panel_row()
    return SpreadCalibrationResult(
        calibration_id="spread-calibration-001",
        dataset_id="dataset-001",
        estimator_timeframe="1m",
        edge_window_bars=3,
        price_basis="last_window_close",
        panel_rows=(row,),
        symbol_summaries=(
            SpreadCalibrationSymbolSummary(
                symbol="EURUSD",
                estimator_timeframe="1m",
                source_fingerprint="f" * 64,
                input_bar_count=10,
                eligible_window_count=1,
                usable_row_count=1,
                invalid_window_count=0,
                negative_estimate_count=0,
                invalid_reason_counts={},
                positive_volume_row_count=10,
                zero_volume_row_count=0,
            ),
        ),
        source_fingerprints={"EURUSD": "f" * 64},
        requested_by="unit-test",
    )


def _panel_row() -> SpreadCalibrationPanelRow:
    fill_timestamp = datetime(2026, 1, 1, 0, 3, tzinfo=timezone.utc)
    edge_full_spread = 0.0001
    reference_price = 1.1
    return SpreadCalibrationPanelRow(
        symbol="EURUSD",
        estimator_timeframe="1m",
        fill_timestamp_utc=fill_timestamp,
        target_observed_at_utc=fill_timestamp - timedelta(microseconds=1),
        feature_observed_at_utc=fill_timestamp - timedelta(microseconds=1),
        edge_window_start_utc=fill_timestamp - timedelta(minutes=3),
        edge_window_end_utc=fill_timestamp - timedelta(microseconds=1),
        edge_window_bars=3,
        session_bucket_id="regular",
        volatility_stress_signal=0.0,
        liquidity_stress_signal=0.0,
        liquidity_observed_volume=1000.0,
        edge_full_spread_frac_signed=edge_full_spread,
        edge_full_spread_frac_nonnegative=edge_full_spread,
        reference_price=reference_price,
        half_spread_price=reference_price * edge_full_spread / 2.0,
        price_basis="last_window_close",
        conversion_method="unit test",
        source_fingerprint="f" * 64,
        validator_ruleset_version="market_data_rules_v5",
        negative_edge_estimate=False,
    )


def _publication_result() -> SpreadCalibrationPublicationResult:
    output_dir = Path("custom/calibration/spread-calibration-001/target-1h")
    return SpreadCalibrationPublicationResult(
        calibration_id="spread-calibration-001",
        profile_id="default_execution_costs",
        estimator_timeframe="1m",
        target_timeframe="1h",
        output_dir=output_dir,
        execution_costs_path=output_dir / "execution_costs.yaml",
        calibration_report_path=output_dir / "calibration_report.json",
        calibration_panel_path=output_dir / "calibration_panel.parquet",
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
