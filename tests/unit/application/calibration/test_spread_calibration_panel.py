from __future__ import annotations

import hashlib
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest
from pydantic import ValidationError

from backtest_engine.application.calibration import (
    SpreadCalibrationCommand,
    build_spread_calibration_panel,
)
from backtest_engine.core.enums import DatasetSource
from backtest_engine.core.errors import ApplicationError
from backtest_engine.domain.market.datasets import DatasetSpec
from backtest_engine.infrastructure.data.market_data_contracts import (
    SourceSliceManifest,
    ValidationManifest,
)
from backtest_engine.infrastructure.data.parquet_normalizer import (
    MaterializedDataset,
    NormalizedBarArtifact,
    NormalizedBarManifest,
)


OPEN_VALUES = [99.268728, 99.949389, 99.037372, 98.617758, 97.106084, 97.041004]
HIGH_VALUES = [100.085996, 100.343551, 99.251673, 98.973541, 97.985839, 97.306494]
LOW_VALUES = [98.889634, 99.523119, 97.693192, 97.418306, 96.668414, 96.585325]
CLOSE_VALUES = [99.958515, 99.848422, 98.103148, 97.635734, 97.970854, 97.121379]
FIRST_THREE_BAR_SIGNED_EDGE = -0.007166809603101239


def test_panel_uses_only_completed_window_before_fill_timestamp(tmp_path: Path) -> None:
    bars = _bars()
    materialized = _write_materialized_dataset(tmp_path, bars)

    result = build_spread_calibration_panel(
        SpreadCalibrationCommand(
            materialized_dataset=materialized,
            estimator_timeframe="1m",
            edge_window_bars=3,
        )
    )

    assert result.row_count == 3
    first = result.panel_rows[0]
    assert first.fill_timestamp_utc == datetime(2026, 1, 1, 0, 3, tzinfo=timezone.utc)
    assert first.edge_window_end_utc == datetime(
        2026,
        1,
        1,
        0,
        2,
        59,
        999999,
        tzinfo=timezone.utc,
    )
    assert first.target_observed_at_utc < first.fill_timestamp_utc
    assert first.feature_observed_at_utc < first.fill_timestamp_utc
    assert first.session_bucket_id == "regular"
    assert math.isfinite(first.volatility_stress_signal)
    assert math.isfinite(first.liquidity_stress_signal)
    assert first.liquidity_observed_volume > 0.0
    assert first.edge_full_spread_frac_signed == pytest.approx(FIRST_THREE_BAR_SIGNED_EDGE)
    assert first.edge_full_spread_frac_nonnegative == 0.0
    assert first.half_spread_price == 0.0

    summary = result.symbol_summaries[0]
    assert summary.eligible_window_count == 3
    assert summary.usable_row_count == 3
    assert summary.negative_estimate_count == 1
    assert summary.negative_rate == pytest.approx(1 / 3)


def test_panel_blocks_stale_validation_manifest(tmp_path: Path) -> None:
    materialized = _write_materialized_dataset(
        tmp_path,
        _bars(),
        validation_fingerprint="0" * 64,
    )

    with pytest.raises(ApplicationError, match="validation manifest fingerprint is stale"):
        build_spread_calibration_panel(
            SpreadCalibrationCommand(
                materialized_dataset=materialized,
                estimator_timeframe="1m",
                edge_window_bars=3,
            )
        )


def test_panel_blocks_missing_regular_grid_bar(tmp_path: Path) -> None:
    bars = _bars().drop(index=2).reset_index(drop=True)
    materialized = _write_materialized_dataset(tmp_path, bars)

    with pytest.raises(ApplicationError, match="regular grid"):
        build_spread_calibration_panel(
            SpreadCalibrationCommand(
                materialized_dataset=materialized,
                estimator_timeframe="1m",
                edge_window_bars=3,
            )
        )


def test_panel_blocks_non_positive_ohlc_before_edge(tmp_path: Path) -> None:
    bars = _bars()
    bars.loc[1, "close"] = 0.0
    materialized = _write_materialized_dataset(tmp_path, bars)

    with pytest.raises(ApplicationError, match="non-positive OHLC"):
        build_spread_calibration_panel(
            SpreadCalibrationCommand(
                materialized_dataset=materialized,
                estimator_timeframe="1m",
                edge_window_bars=3,
            )
        )


def test_panel_reports_invalid_edge_windows_and_blocks_threshold(tmp_path: Path) -> None:
    bars = _bars(
        open_values=[100.0, 100.0, 100.0, 100.0],
        high_values=[100.0, 100.0, 100.0, 100.0],
        low_values=[100.0, 100.0, 100.0, 100.0],
        close_values=[100.0, 100.0, 100.0, 100.0],
    )
    materialized = _write_materialized_dataset(tmp_path, bars)

    with pytest.raises(
        ApplicationError, match="insufficient usable EDGE calibration rows"
    ) as exc_info:
        build_spread_calibration_panel(
            SpreadCalibrationCommand(
                materialized_dataset=materialized,
                estimator_timeframe="1m",
                edge_window_bars=3,
            )
        )

    assert exc_info.value.context["invalid_reason_counts"] == {"nt_lt_2": 1}


def test_command_rejects_validation_skip_and_zero_row_publication(tmp_path: Path) -> None:
    materialized = _write_materialized_dataset(tmp_path, _bars())

    with pytest.raises(ValidationError):
        SpreadCalibrationCommand(
            materialized_dataset=materialized,
            estimator_timeframe="1m",
            edge_window_bars=3,
            minimum_usable_rows_per_symbol=0,
        )

    with pytest.raises(ValidationError):
        SpreadCalibrationCommand.model_validate(
            {
                "materialized_dataset": materialized,
                "estimator_timeframe": "1m",
                "edge_window_bars": 3,
                "require_fresh_validation": False,
            }
        )


def test_panel_blocks_duplicate_timestamps(tmp_path: Path) -> None:
    bars = _bars()
    bars.loc[2, "ts_event_utc"] = bars.loc[1, "ts_event_utc"]
    materialized = _write_materialized_dataset(tmp_path, bars)

    with pytest.raises(ApplicationError, match="duplicate timestamps"):
        build_spread_calibration_panel(
            SpreadCalibrationCommand(
                materialized_dataset=materialized,
                estimator_timeframe="1m",
                edge_window_bars=3,
            )
        )


def test_panel_blocks_unsorted_timestamps(tmp_path: Path) -> None:
    bars = _bars()
    bars.loc[1, "ts_event_utc"], bars.loc[2, "ts_event_utc"] = (
        bars.loc[2, "ts_event_utc"],
        bars.loc[1, "ts_event_utc"],
    )
    materialized = _write_materialized_dataset(tmp_path, bars)

    with pytest.raises(ApplicationError, match="sorted by UTC timestamp"):
        build_spread_calibration_panel(
            SpreadCalibrationCommand(
                materialized_dataset=materialized,
                estimator_timeframe="1m",
                edge_window_bars=3,
            )
        )


def test_panel_blocks_invalid_ohlc_shape_before_edge(tmp_path: Path) -> None:
    bars = _bars()
    bars.loc[2, "high"] = LOW_VALUES[2] - 0.1
    materialized = _write_materialized_dataset(tmp_path, bars)

    with pytest.raises(ApplicationError, match="invalid OHLC shape"):
        build_spread_calibration_panel(
            SpreadCalibrationCommand(
                materialized_dataset=materialized,
                estimator_timeframe="1m",
                edge_window_bars=3,
            )
        )


def test_panel_blocks_non_finite_ohlcv(tmp_path: Path) -> None:
    bars = _bars()
    bars.loc[2, "volume"] = float("nan")
    materialized = _write_materialized_dataset(tmp_path, bars)

    with pytest.raises(ApplicationError, match="non-finite OHLCV"):
        build_spread_calibration_panel(
            SpreadCalibrationCommand(
                materialized_dataset=materialized,
                estimator_timeframe="1m",
                edge_window_bars=3,
            )
        )


def test_panel_blocks_zero_volume_when_coverage_threshold_fails(tmp_path: Path) -> None:
    bars = _bars()
    bars.loc[2, "volume"] = 0.0
    materialized = _write_materialized_dataset(tmp_path, bars)

    with pytest.raises(ApplicationError, match="positive-volume coverage") as exc_info:
        build_spread_calibration_panel(
            SpreadCalibrationCommand(
                materialized_dataset=materialized,
                estimator_timeframe="1m",
                edge_window_bars=3,
            )
        )

    assert exc_info.value.context["zero_volume_row_count"] == 1


def test_panel_records_zero_volume_diagnostics_when_threshold_passes(tmp_path: Path) -> None:
    bars = _bars()
    bars.loc[2, "volume"] = 0.0
    materialized = _write_materialized_dataset(tmp_path, bars)

    result = build_spread_calibration_panel(
        SpreadCalibrationCommand(
            materialized_dataset=materialized,
            estimator_timeframe="1m",
            edge_window_bars=3,
            positive_volume_coverage_threshold=0.8,
        )
    )

    assert result.symbol_summaries[0].zero_volume_row_count == 1
    assert result.symbol_summaries[0].positive_volume_coverage == pytest.approx(5 / 6)


def test_panel_blocks_persisted_normalized_manifest_mismatch(tmp_path: Path) -> None:
    materialized = _write_materialized_dataset(tmp_path, _bars())
    persisted = materialized.artifacts[0].manifest.model_copy(update={"schema_version": "2"})
    materialized.artifacts[0].manifest_path.write_text(
        persisted.model_dump_json(indent=2),
        encoding="utf-8",
    )

    with pytest.raises(ApplicationError, match="object does not match persisted manifest"):
        build_spread_calibration_panel(
            SpreadCalibrationCommand(
                materialized_dataset=materialized,
                estimator_timeframe="1m",
                edge_window_bars=3,
            )
        )


def test_panel_blocks_dataset_contract_mismatch(tmp_path: Path) -> None:
    materialized = _write_materialized_dataset(tmp_path, _bars())
    drifted_dataset = materialized.dataset.model_copy(update={"schema_version": "2"})
    drifted = materialized.model_copy(update={"dataset": drifted_dataset})

    with pytest.raises(ApplicationError, match="dataset_id"):
        build_spread_calibration_panel(
            SpreadCalibrationCommand(
                materialized_dataset=drifted,
                estimator_timeframe="1m",
                edge_window_bars=3,
            )
        )


def test_panel_blocks_normalized_parquet_row_count_mismatch(tmp_path: Path) -> None:
    materialized = _write_materialized_dataset(tmp_path, _bars())
    truncated = _bars().iloc[:-1]
    truncated.to_parquet(materialized.artifacts[0].data_path, index=False)

    with pytest.raises(ApplicationError, match="row_count"):
        build_spread_calibration_panel(
            SpreadCalibrationCommand(
                materialized_dataset=materialized,
                estimator_timeframe="1m",
                edge_window_bars=3,
            )
        )


def test_panel_blocks_source_manifest_path_mismatch(tmp_path: Path) -> None:
    materialized = _write_materialized_dataset(tmp_path, _bars())
    source_manifest_path = (
        materialized.artifacts[0].manifest.source_path.parent / "source_manifest.json"
    )
    source_manifest = SourceSliceManifest.model_validate_json(
        source_manifest_path.read_text(encoding="utf-8"),
    )
    drifted = source_manifest.model_copy(
        update={
            "bars_path": materialized.artifacts[0].manifest.source_path.parent / "other.parquet"
        }
    )
    source_manifest_path.write_text(drifted.model_dump_json(indent=2), encoding="utf-8")

    with pytest.raises(ApplicationError, match="bars_path"):
        build_spread_calibration_panel(
            SpreadCalibrationCommand(
                materialized_dataset=materialized,
                estimator_timeframe="1m",
                edge_window_bars=3,
            )
        )


def test_panel_builds_multi_symbol_rows_with_independent_alignment(tmp_path: Path) -> None:
    materialized = _write_multi_symbol_materialized_dataset(
        tmp_path,
        {
            "EURUSD": _bars(),
            "GBPUSD": _bars(
                open_values=[value + 10.0 for value in OPEN_VALUES],
                high_values=[value + 10.0 for value in HIGH_VALUES],
                low_values=[value + 10.0 for value in LOW_VALUES],
                close_values=[value + 10.0 for value in CLOSE_VALUES],
            ),
        },
    )

    result = build_spread_calibration_panel(
        SpreadCalibrationCommand(
            materialized_dataset=materialized,
            estimator_timeframe="1m",
            edge_window_bars=3,
        )
    )

    assert result.row_count == 6
    assert {summary.symbol for summary in result.symbol_summaries} == {"EURUSD", "GBPUSD"}
    for row in result.panel_rows:
        assert row.edge_window_end_utc < row.fill_timestamp_utc


def _bars(
    *,
    open_values: list[float] | None = None,
    high_values: list[float] | None = None,
    low_values: list[float] | None = None,
    close_values: list[float] | None = None,
) -> pd.DataFrame:
    open_series = open_values or OPEN_VALUES
    high_series = high_values or HIGH_VALUES
    low_series = low_values or LOW_VALUES
    close_series = close_values or CLOSE_VALUES
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    timestamps = [start + timedelta(minutes=index) for index in range(len(open_series))]
    return pd.DataFrame(
        {
            "ts_event_utc": timestamps,
            "open": open_series,
            "high": high_series,
            "low": low_series,
            "close": close_series,
            "volume": [1000.0 + index for index in range(len(open_series))],
            "vwap": [pd.NA] * len(open_series),
            "trade_count": [pd.NA] * len(open_series),
            "contract_code": [pd.NA] * len(open_series),
        }
    )


def _write_materialized_dataset(
    tmp_path: Path,
    bars: pd.DataFrame,
    *,
    symbol: str = "EURUSD",
    validation_fingerprint: str | None = None,
) -> MaterializedDataset:
    timeframe = "1m"
    dataset = DatasetSpec(
        source_system=DatasetSource.MT5,
        normalization_policy="nautilus_v1",
        schema_version="1",
        symbol_universe=(symbol,),
        timeframe=timeframe,
        dataset_version="2026-01-01",
    )
    artifact = _write_symbol_artifact(
        tmp_path,
        bars,
        symbol=symbol,
        dataset=dataset,
        validation_fingerprint=validation_fingerprint,
    )
    materialization_manifest_path = tmp_path / "normalized" / "dataset_manifest.json"
    materialization_manifest_path.write_text("{}", encoding="utf-8")
    return MaterializedDataset(
        dataset=dataset,
        dataset_root=tmp_path / "normalized",
        manifest_path=materialization_manifest_path,
        artifacts=(artifact,),
    )


def _write_multi_symbol_materialized_dataset(
    tmp_path: Path,
    bars_by_symbol: dict[str, pd.DataFrame],
) -> MaterializedDataset:
    dataset = DatasetSpec(
        source_system=DatasetSource.MT5,
        normalization_policy="nautilus_v1",
        schema_version="1",
        symbol_universe=tuple(bars_by_symbol),
        timeframe="1m",
        dataset_version="2026-01-01",
    )
    artifacts = tuple(
        _write_symbol_artifact(tmp_path, bars, symbol=symbol, dataset=dataset)
        for symbol, bars in bars_by_symbol.items()
    )
    materialization_manifest_path = tmp_path / "normalized" / "dataset_manifest.json"
    materialization_manifest_path.write_text("{}", encoding="utf-8")
    return MaterializedDataset(
        dataset=dataset,
        dataset_root=tmp_path / "normalized",
        manifest_path=materialization_manifest_path,
        artifacts=artifacts,
    )


def _write_symbol_artifact(
    tmp_path: Path,
    bars: pd.DataFrame,
    *,
    symbol: str,
    dataset: DatasetSpec,
    validation_fingerprint: str | None = None,
) -> NormalizedBarArtifact:
    timeframe = "1m"
    provider_id = "mt5"
    source_path = tmp_path / "source" / provider_id / symbol / timeframe / "bars.parquet"
    normalized_path = tmp_path / "normalized" / symbol / timeframe / "bars.parquet"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    normalized_path.parent.mkdir(parents=True, exist_ok=True)
    bars.to_parquet(source_path, index=False)
    bars.to_parquet(normalized_path, index=False)
    source_fingerprint = _file_sha256(source_path)

    first_timestamp = pd.Timestamp(bars["ts_event_utc"].iloc[0]).to_pydatetime()
    last_timestamp = pd.Timestamp(bars["ts_event_utc"].iloc[-1]).to_pydatetime()
    source_manifest = SourceSliceManifest(
        provider_id=provider_id,
        source_system=DatasetSource.MT5,
        canonical_symbol=symbol,
        provider_symbol=symbol,
        timeframe=timeframe,
        calendar_id="24x7",
        timezone_name="UTC",
        bars_path=source_path,
        requested_start_utc=first_timestamp,
        requested_end_utc=last_timestamp,
        actual_start_utc=first_timestamp,
        actual_end_utc=last_timestamp,
        generated_at_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
        row_count=len(bars),
        source_fingerprint=source_fingerprint,
    )
    (source_path.parent / "source_manifest.json").write_text(
        source_manifest.model_dump_json(indent=2),
        encoding="utf-8",
    )
    validation_manifest = ValidationManifest(
        provider_id=provider_id,
        canonical_symbol=symbol,
        timeframe=timeframe,
        source_fingerprint=validation_fingerprint or source_fingerprint,
        validator_ruleset_version="market_data_rules_v5",
        verification_verdict="PASS",
        verified_at_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    (source_path.parent / "validation_manifest.json").write_text(
        validation_manifest.model_dump_json(indent=2),
        encoding="utf-8",
    )

    normalized_manifest = NormalizedBarManifest(
        dataset_id=dataset.dataset_id,
        source_system=DatasetSource.MT5,
        raw_symbol=symbol,
        timeframe=timeframe,
        normalization_policy=dataset.normalization_policy,
        schema_version=dataset.schema_version,
        source_path=source_path,
        source_fingerprint=source_fingerprint,
        row_count=len(bars),
        start_time_utc=first_timestamp,
        end_time_utc=last_timestamp,
        nautilus_instrument_id=f"{symbol}.SIM",
    )
    normalized_manifest_path = normalized_path.parent / "manifest.json"
    normalized_manifest_path.write_text(
        normalized_manifest.model_dump_json(indent=2),
        encoding="utf-8",
    )
    return NormalizedBarArtifact(
        symbol=symbol,
        timeframe=timeframe,
        data_path=normalized_path,
        manifest_path=normalized_manifest_path,
        manifest=normalized_manifest,
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
