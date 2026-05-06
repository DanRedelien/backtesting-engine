from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest
import yaml
from pydantic import ValidationError

from backtest_engine.application.calibration import (
    SpreadCalibrationPanelRow,
    SpreadCalibrationPublicationCommand,
    SpreadCalibrationResult,
    SpreadCalibrationSymbolSummary,
    publish_spread_calibration,
)
from backtest_engine.application.calibration.diagnostics_plots import diagnostic_symbol_png_name
from backtest_engine.config.calibration import CalibrationVolumeSemantics
from backtest_engine.config.execution_costs import (
    execution_costs_config_hash,
    load_execution_costs,
)
from backtest_engine.core.errors import ApplicationError
from backtest_engine.domain.execution.instrument_metadata import (
    ExecutionAssetClass,
    ExecutionInstrumentMetadata,
    ExecutionInstrumentType,
)
from backtest_engine.domain.execution.spreads import (
    LogLinearDynamicHalfSpread,
    StaticHalfSpreadTicks,
)
from backtest_engine.infrastructure.nautilus.symbol_map import load_symbol_map


def test_publish_spread_calibration_writes_valid_hashable_generated_yaml(
    tmp_path: Path,
) -> None:
    calibration_result = _calibration_result(symbols=("ES",), volatility_weight=0.50)

    publication = publish_spread_calibration(
        SpreadCalibrationPublicationCommand(
            calibration_result=calibration_result,
            target_timeframe="H1",
            output_root=tmp_path,
            train_fraction=0.6,
            minimum_train_rows_per_symbol=5,
            minimum_holdout_rows_per_symbol=5,
        )
    )

    loaded = load_execution_costs(publication.execution_costs_path)
    assert publication.execution_costs_config_hash == execution_costs_config_hash(loaded)

    symbol_map = load_symbol_map()
    es_profile = loaded.resolve_profile(_metadata("ES"))
    assert isinstance(es_profile.spread_model, LogLinearDynamicHalfSpread)
    assert es_profile.spread_model.provenance.timeframe == "1h"
    assert es_profile.spread_model.provenance.estimator_method.endswith(
        "estimator_timeframe=1m; edge_window_bars=3"
    )
    assert es_profile.spread_model.min_half_spread_price == Decimal("0.125")
    assert es_profile.spread_model.base_half_spread_price >= Decimal("0.125")
    assert es_profile.spread_model.liquidity_weight == Decimal("0")
    assert es_profile.spread_model.volatility_weight == Decimal("0")

    eurusd_profile = loaded.resolve_profile(_metadata("EURUSD"))
    assert isinstance(eurusd_profile.spread_model, StaticHalfSpreadTicks)
    assert publication.execution_costs_path != Path(
        "src/backtest_engine/config/execution_costs.yaml"
    )
    assert symbol_map.resolve("ES").tick_size == Decimal("0.25")

    report = json.loads(publication.calibration_report_path.read_text(encoding="utf-8"))
    assert report["schema_version"] == "spread_calibration_report.v2"
    assert report["generated_execution_costs"]["config_content_hash"] == (
        publication.execution_costs_config_hash
    )
    assert report["diagnostics"]["threshold_policy"]["policy_name"] == (
        "spread_calibration_internal_heuristics_v1"
    )
    assert "row_weighted" in report["diagnostics"]["aggregate"]
    assert "symbol_equal_weighted" in report["diagnostics"]["aggregate"]
    assert report["diagnostic_artifacts"]["summary_png"] == (
        "calibration_diagnostics_summary.png"
    )
    assert report["diagnostic_artifacts"]["symbol_pngs"] == {
        "ES": diagnostic_symbol_png_name("ES")
    }
    assert report["diagnostic_artifacts"]["path_base"] == (
        "relative_to_calibration_report_directory"
    )
    assert all(flag["publication_blocking"] is False for flag in report["flags"])
    assert publication.diagnostic_artifact_paths
    for diagnostic_path in publication.diagnostic_artifact_paths:
        assert diagnostic_path.exists()
        assert diagnostic_path.stat().st_size > 0
    assert report["generated_execution_costs"]["run_profile_snippet"] == {
        "execution_policy": {
            "execution_costs": {
                "profile_id": loaded.profile_id,
                "config_content_hash": publication.execution_costs_config_hash,
            }
        }
    }
    assert report["estimator_timeframe"] == "1m"
    assert report["target_timeframe"] == "1h"
    assert report["liquidity_fit"]["enabled"] is False
    assert float(report["fitted_shared_coefficients"]["volatility_weight"]) == pytest.approx(
        0.50,
        abs=0.05,
    )
    assert report["published_shared_coefficients"]["volatility_weight"] == "0"
    assert report["published_shared_coefficients"]["projection_reason"] == (
        "dynamic_weights_disabled_for_cross_timeframe_feature_projection"
    )

    panel = pd.read_parquet(publication.calibration_panel_path)
    assert set(panel["sample_role"]) == {"train", "purged", "holdout"}


def test_publish_spread_calibration_rejects_mixed_asset_class_panel(tmp_path: Path) -> None:
    calibration_result = _calibration_result(symbols=("ES", "EURUSD"), volatility_weight=0.25)

    with pytest.raises(ApplicationError, match="homogeneous asset-class"):
        publish_spread_calibration(
            SpreadCalibrationPublicationCommand(
                calibration_result=calibration_result,
                target_timeframe="5m",
                output_root=tmp_path,
                train_fraction=0.6,
            )
        )


def test_publish_spread_calibration_can_fit_liquidity_when_explicitly_allowed(
    tmp_path: Path,
) -> None:
    calibration_result = _calibration_result(
        symbols=("ES",),
        volatility_weight=0.20,
        liquidity_weight=0.35,
    )

    publication = publish_spread_calibration(
        SpreadCalibrationPublicationCommand(
            calibration_result=calibration_result,
            target_timeframe="1m",
            output_root=tmp_path,
            train_fraction=0.6,
            allow_liquidity_weight=True,
            volume_semantics=CalibrationVolumeSemantics.CONTRACT_VOLUME,
            liquidity_coverage_threshold=1.0,
            minimum_train_rows_per_symbol=5,
            minimum_holdout_rows_per_symbol=5,
        )
    )

    profile = load_execution_costs(publication.execution_costs_path).resolve_profile(
        _metadata("ES")
    )

    assert isinstance(profile.spread_model, LogLinearDynamicHalfSpread)
    assert float(profile.spread_model.volatility_weight) == pytest.approx(0.20, abs=0.08)
    assert float(profile.spread_model.liquidity_weight) == pytest.approx(0.35, abs=0.08)


def test_publish_spread_calibration_blocks_untrusted_liquidity_volume_semantics(
    tmp_path: Path,
) -> None:
    with pytest.raises(ApplicationError, match="trusted volume semantics"):
        publish_spread_calibration(
            SpreadCalibrationPublicationCommand(
                calibration_result=_calibration_result(
                    symbols=("ES",),
                    volatility_weight=0.20,
                    liquidity_weight=0.35,
                ),
                target_timeframe="1m",
                output_root=tmp_path,
                train_fraction=0.6,
                allow_liquidity_weight=True,
            )
        )


def test_publication_command_rejects_tick_floor_below_half_tick() -> None:
    with pytest.raises(ValidationError, match="min_half_spread_tick_fraction"):
        SpreadCalibrationPublicationCommand(
            calibration_result=_calibration_result(symbols=("ES",), volatility_weight=0.20),
            target_timeframe="1m",
            min_half_spread_tick_fraction=Decimal("0.25"),
        )


def test_publish_spread_calibration_rejects_incomplete_bundle_provenance(
    tmp_path: Path,
) -> None:
    calibration_result = _calibration_result(symbols=("ES",), volatility_weight=0.20)
    incomplete = calibration_result.model_copy(update={"source_fingerprints": {}})

    with pytest.raises(ApplicationError, match="symbol sets must match"):
        publish_spread_calibration(
            SpreadCalibrationPublicationCommand(
                calibration_result=incomplete,
                target_timeframe="1m",
                output_root=tmp_path,
                train_fraction=0.6,
            )
        )


def test_publish_spread_calibration_rejects_duplicate_panel_row_identities(
    tmp_path: Path,
) -> None:
    calibration_result = _calibration_result(symbols=("ES",), volatility_weight=0.20)
    duplicated = calibration_result.model_copy(
        update={
            "panel_rows": (
                calibration_result.panel_rows
                + (calibration_result.panel_rows[0],)
            )
        }
    )

    with pytest.raises(ApplicationError, match="duplicate panel row identities"):
        publish_spread_calibration(
            SpreadCalibrationPublicationCommand(
                calibration_result=duplicated,
                target_timeframe="1m",
                output_root=tmp_path,
                train_fraction=0.6,
            )
        )


def test_publish_spread_calibration_rejects_summary_count_drift(
    tmp_path: Path,
) -> None:
    calibration_result = _calibration_result(symbols=("ES",), volatility_weight=0.20)
    dropped_row = calibration_result.model_copy(
        update={"panel_rows": calibration_result.panel_rows[:-1]}
    )

    with pytest.raises(ApplicationError, match="usable_row_count does not match panel rows"):
        publish_spread_calibration(
            SpreadCalibrationPublicationCommand(
                calibration_result=dropped_row,
                target_timeframe="1m",
                output_root=tmp_path,
                train_fraction=0.6,
                minimum_train_rows_per_symbol=1,
                minimum_holdout_rows_per_symbol=1,
            )
        )


def test_publish_spread_calibration_uses_target_specific_artifact_paths(
    tmp_path: Path,
) -> None:
    calibration_result = _calibration_result(symbols=("ES",), volatility_weight=0.20)

    h1 = publish_spread_calibration(
        SpreadCalibrationPublicationCommand(
            calibration_result=calibration_result,
            target_timeframe="1h",
            output_root=tmp_path,
            train_fraction=0.6,
        )
    )
    five_minute = publish_spread_calibration(
        SpreadCalibrationPublicationCommand(
            calibration_result=calibration_result,
            target_timeframe="5m",
            output_root=tmp_path,
            train_fraction=0.6,
        )
    )

    assert h1.execution_costs_path != five_minute.execution_costs_path
    assert h1.calibration_report_path != five_minute.calibration_report_path
    assert (
        json.loads(h1.calibration_report_path.read_text(encoding="utf-8"))["target_timeframe"]
        == "1h"
    )
    assert (
        json.loads(five_minute.calibration_report_path.read_text(encoding="utf-8"))[
            "target_timeframe"
        ]
        == "5m"
    )


def test_publish_spread_calibration_canonicalizes_panel_and_summary_order(
    tmp_path: Path,
) -> None:
    calibration_result = _calibration_result(
        symbols=("ES", "NQ"),
        volatility_weight=0.20,
    )
    permuted = calibration_result.model_copy(
        update={
            "panel_rows": tuple(reversed(calibration_result.panel_rows)),
            "symbol_summaries": tuple(reversed(calibration_result.symbol_summaries)),
        }
    )

    ordered_publication = publish_spread_calibration(
        SpreadCalibrationPublicationCommand(
            calibration_result=calibration_result,
            target_timeframe="1m",
            output_root=tmp_path / "ordered",
            train_fraction=0.6,
        )
    )
    permuted_publication = publish_spread_calibration(
        SpreadCalibrationPublicationCommand(
            calibration_result=permuted,
            target_timeframe="1m",
            output_root=tmp_path / "permuted",
            train_fraction=0.6,
        )
    )

    ordered_panel = pd.read_parquet(ordered_publication.calibration_panel_path)
    permuted_panel = pd.read_parquet(permuted_publication.calibration_panel_path)
    ordered_keys = _panel_order_keys(ordered_panel)
    permuted_keys = _panel_order_keys(permuted_panel)
    assert ordered_keys == sorted(ordered_keys)
    assert permuted_keys == ordered_keys
    assert (
        ordered_panel[["symbol", "fill_timestamp_utc", "sample_role"]].to_dict("records")
        == permuted_panel[["symbol", "fill_timestamp_utc", "sample_role"]].to_dict("records")
    )

    ordered_report = json.loads(
        ordered_publication.calibration_report_path.read_text(encoding="utf-8")
    )
    permuted_report = json.loads(
        permuted_publication.calibration_report_path.read_text(encoding="utf-8")
    )
    ordered_summaries = ordered_report["symbol_summaries"]
    permuted_summaries = permuted_report["symbol_summaries"]
    assert [summary["symbol"] for summary in ordered_summaries] == ["ES", "NQ"]
    assert permuted_summaries == ordered_summaries


def test_publish_spread_calibration_writes_multi_symbol_diagnostic_pngs(
    tmp_path: Path,
) -> None:
    publication = publish_spread_calibration(
        SpreadCalibrationPublicationCommand(
            calibration_result=_calibration_result(
                symbols=("ES", "NQ"),
                volatility_weight=0.20,
            ),
            target_timeframe="1m",
            output_root=tmp_path,
            train_fraction=0.6,
        )
    )

    report = json.loads(publication.calibration_report_path.read_text(encoding="utf-8"))

    assert report["diagnostic_artifacts"]["summary_png"] == (
        "calibration_diagnostics_summary.png"
    )
    assert report["diagnostic_artifacts"]["symbol_pngs"] == {
        "ES": diagnostic_symbol_png_name("ES"),
        "NQ": diagnostic_symbol_png_name("NQ"),
    }
    assert len(publication.diagnostic_artifact_paths) == 3
    assert all(path.exists() and path.stat().st_size > 0 for path in publication.diagnostic_artifact_paths)


def test_publish_spread_calibration_path_includes_base_config_and_symbol_map_inputs(
    tmp_path: Path,
) -> None:
    calibration_result = _calibration_result(symbols=("ES",), volatility_weight=0.20)
    custom_base_path = tmp_path / "custom_execution_costs.yaml"
    custom_symbol_map_path = tmp_path / "custom_symbol_map.yaml"

    base_payload = load_execution_costs().model_dump(mode="json", exclude_none=True)
    base_payload["description"] = "custom base config for publication identity"
    custom_base_path.write_text(
        yaml.safe_dump(base_payload, sort_keys=False),
        encoding="utf-8",
    )

    symbol_map_payload = load_symbol_map().model_dump(mode="json", exclude_none=True)
    symbol_map_payload["description"] = "custom symbol map for publication identity"
    custom_symbol_map_path.write_text(
        yaml.safe_dump(symbol_map_payload, sort_keys=False),
        encoding="utf-8",
    )

    default_publication = publish_spread_calibration(
        SpreadCalibrationPublicationCommand(
            calibration_result=calibration_result,
            target_timeframe="1m",
            output_root=tmp_path,
            train_fraction=0.6,
        )
    )
    custom_base_publication = publish_spread_calibration(
        SpreadCalibrationPublicationCommand(
            calibration_result=calibration_result,
            target_timeframe="1m",
            output_root=tmp_path,
            train_fraction=0.6,
            base_execution_costs_path=custom_base_path,
        )
    )
    custom_symbol_map_publication = publish_spread_calibration(
        SpreadCalibrationPublicationCommand(
            calibration_result=calibration_result,
            target_timeframe="1m",
            output_root=tmp_path,
            train_fraction=0.6,
            symbol_map_path=custom_symbol_map_path,
        )
    )

    assert (
        len(
            {
                default_publication.output_dir,
                custom_base_publication.output_dir,
                custom_symbol_map_publication.output_dir,
            }
        )
        == 3
    )


def test_publish_spread_calibration_uses_symbol_specific_provenance_window(
    tmp_path: Path,
) -> None:
    calibration_result = _calibration_result(
        symbols=("ES", "NQ"),
        volatility_weight=0.20,
        symbol_start_offsets={"NQ": 10},
    )

    publication = publish_spread_calibration(
        SpreadCalibrationPublicationCommand(
            calibration_result=calibration_result,
            target_timeframe="1m",
            output_root=tmp_path,
            train_fraction=0.6,
            allow_cross_timeframe_dynamic_weights=True,
        )
    )
    profile = load_execution_costs(publication.execution_costs_path).resolve_profile(
        _metadata("NQ")
    )

    assert isinstance(profile.spread_model, LogLinearDynamicHalfSpread)
    assert profile.spread_model.provenance.sample_start_utc == datetime(
        2026,
        1,
        1,
        0,
        13,
        tzinfo=timezone.utc,
    )


def test_publish_spread_calibration_reports_mixed_asset_override(tmp_path: Path) -> None:
    publication = publish_spread_calibration(
        SpreadCalibrationPublicationCommand(
            calibration_result=_calibration_result(
                symbols=("ES", "EURUSD"),
                volatility_weight=0.20,
            ),
            target_timeframe="1m",
            output_root=tmp_path,
            train_fraction=0.6,
            allow_mixed_asset_classes=True,
        )
    )

    report = json.loads(publication.calibration_report_path.read_text(encoding="utf-8"))
    assert report["asset_class_panel"]["allow_mixed_asset_classes"] is True
    assert report["asset_class_panel"]["asset_classes"] == ["FX", "INDEX"]
    assert report["asset_class_panel"]["rationale"] == (
        "operator_explicitly_allowed_mixed_asset_class_panel"
    )


def test_publish_spread_calibration_blocks_non_converged_fit(tmp_path: Path) -> None:
    with pytest.raises(ApplicationError, match="fit did not converge"):
        publish_spread_calibration(
            SpreadCalibrationPublicationCommand(
                calibration_result=_calibration_result(symbols=("ES",), volatility_weight=0.50),
                target_timeframe="1m",
                output_root=tmp_path,
                train_fraction=0.6,
                max_fit_iterations=1,
            )
        )


def test_publish_spread_calibration_rejects_aliases_to_same_canonical_symbol(
    tmp_path: Path,
) -> None:
    with pytest.raises(ApplicationError, match="multiple input symbols"):
        publish_spread_calibration(
            SpreadCalibrationPublicationCommand(
                calibration_result=_calibration_result(
                    symbols=("ES", "ESH6"),
                    volatility_weight=0.20,
                ),
                target_timeframe="1m",
                output_root=tmp_path,
                train_fraction=0.6,
            )
        )


def _calibration_result(
    *,
    symbols: tuple[str, ...],
    volatility_weight: float,
    liquidity_weight: float = 0.0,
    symbol_start_offsets: dict[str, int] | None = None,
) -> SpreadCalibrationResult:
    rows: list[SpreadCalibrationPanelRow] = []
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bases = {"ES": 0.25, "ESH6": 0.25, "NQ": 0.25, "EURUSD": 0.00008}
    reference_prices = {"ES": 5000.0, "ESH6": 5000.0, "NQ": 18000.0, "EURUSD": 1.10}
    for symbol in symbols:
        for index in range(24):
            start_offset = (symbol_start_offsets or {}).get(symbol, 0)
            fill_timestamp = start + timedelta(minutes=start_offset + index + 3)
            volatility_signal = (index % 6) / 5
            liquidity_signal = ((index * 2) % 7) / 6
            target = bases[symbol] * math.exp(
                volatility_weight * volatility_signal + liquidity_weight * liquidity_signal
            )
            reference_price = reference_prices[symbol]
            edge_full_spread = target * 2 / reference_price
            rows.append(
                _panel_row(
                    symbol=symbol,
                    fill_timestamp_utc=fill_timestamp,
                    edge_full_spread_frac_signed=edge_full_spread,
                    edge_full_spread_frac_nonnegative=edge_full_spread,
                    reference_price=reference_price,
                    half_spread_price=target,
                    volatility_stress_signal=volatility_signal,
                    liquidity_stress_signal=liquidity_signal,
                    liquidity_observed_volume=1000.0 + index,
                )
            )

    summaries = tuple(
        SpreadCalibrationSymbolSummary(
            symbol=symbol,
            estimator_timeframe="1m",
            source_fingerprint="f" * 64,
            input_bar_count=30,
            eligible_window_count=24,
            usable_row_count=24,
            invalid_window_count=0,
            negative_estimate_count=0,
            invalid_reason_counts={},
            positive_volume_row_count=30,
            zero_volume_row_count=0,
        )
        for symbol in symbols
    )
    return SpreadCalibrationResult(
        calibration_id="spread-calibration-abcdef123456",
        dataset_id="dataset-abcdef123456",
        estimator_timeframe="M1",
        edge_window_bars=3,
        price_basis="last_window_close",
        panel_rows=tuple(rows),
        symbol_summaries=summaries,
        source_fingerprints={symbol: "f" * 64 for symbol in symbols},
        requested_by="unit-test",
    )


def _panel_row(**overrides: object) -> SpreadCalibrationPanelRow:
    fill_timestamp = overrides.pop(
        "fill_timestamp_utc",
        datetime(2026, 1, 1, 0, 3, tzinfo=timezone.utc),
    )
    if not isinstance(fill_timestamp, datetime):
        raise AssertionError("fill_timestamp_utc override must be datetime")
    payload = {
        "symbol": "ES",
        "estimator_timeframe": "1m",
        "fill_timestamp_utc": fill_timestamp,
        "target_observed_at_utc": fill_timestamp - timedelta(microseconds=1),
        "feature_observed_at_utc": fill_timestamp - timedelta(microseconds=1),
        "edge_window_start_utc": fill_timestamp - timedelta(minutes=3),
        "edge_window_end_utc": fill_timestamp - timedelta(microseconds=1),
        "edge_window_bars": 3,
        "session_bucket_id": "regular",
        "volatility_stress_signal": 0.0,
        "liquidity_stress_signal": 0.0,
        "liquidity_observed_volume": 1000.0,
        "edge_full_spread_frac_signed": 0.0001,
        "edge_full_spread_frac_nonnegative": 0.0001,
        "reference_price": 5000.0,
        "half_spread_price": 0.25,
        "price_basis": "last_window_close",
        "conversion_method": "unit test",
        "source_fingerprint": "f" * 64,
        "validator_ruleset_version": "market_data_rules_v5",
        "negative_edge_estimate": False,
    }
    payload.update(overrides)
    return SpreadCalibrationPanelRow.model_validate(payload)


def _metadata(symbol: str) -> ExecutionInstrumentMetadata:
    mapping = load_symbol_map().resolve(symbol)
    if mapping.asset_class is None:
        raise AssertionError(f"{symbol} must define asset_class")
    return ExecutionInstrumentMetadata(
        symbol=mapping.mt5_symbol,
        instrument_type=ExecutionInstrumentType(mapping.instrument_type),
        asset_class=ExecutionAssetClass(mapping.asset_class),
        quote_currency=mapping.quote_currency,
        tick_size=mapping.tick_size,
        point_size=mapping.point_size,
        lot_size=mapping.lot_size,
        multiplier=mapping.multiplier or Decimal("1"),
        price_precision=mapping.price_precision,
    )


def _panel_order_keys(frame: pd.DataFrame) -> list[tuple[str, str]]:
    return [
        (str(row["symbol"]).strip().upper(), str(row["fill_timestamp_utc"]))
        for row in frame[["symbol", "fill_timestamp_utc"]].to_dict("records")
    ]
