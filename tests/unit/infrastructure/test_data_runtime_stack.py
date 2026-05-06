# mypy: ignore-errors
from __future__ import annotations

import json
import math
from decimal import Decimal
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, cast

import pandas as pd
import pytest

from backtest_engine.config.execution_costs import (
    DEFAULT_EXECUTION_COST_PROFILE_ID,
    execution_costs_config_hash,
    load_execution_costs,
)
from backtest_engine.config.runtime import (
    BacktestExecutionPolicy,
    BacktestRunSpec,
    ExecutionCostProfileRef,
    ExecutionVenueOverrides,
    ExecutionWindow,
    RuntimeSettings,
)
from backtest_engine.core.enums import DatasetSource, RunKind
from backtest_engine.core.errors import InfrastructureError
from backtest_engine.core.money import Money
from backtest_engine.core.types import JsonValue
from backtest_engine.domain.market.datasets import DatasetSpec
from backtest_engine.domain.strategy.specifications import (
    PortfolioStrategySpec,
    StrategyLegSpec,
    StrategySpec,
)
from backtest_engine.infrastructure.data import (
    FilesystemParquetCacheStore,
    FilesystemParquetDatasetNormalizer,
)
from backtest_engine.infrastructure.nautilus.catalogs import (
    CatalogReference,
    FilesystemNautilusCatalogBuilder,
)
from backtest_engine.infrastructure.nautilus.dynamic_spread_features import (
    _artifact_path_part,
    _read_normalized_bars,
)
from backtest_engine.infrastructure.nautilus.portfolio_projection import (
    FilesystemPortfolioProjector,
)
from backtest_engine.infrastructure.nautilus.reports import NautilusReportWriter
from backtest_engine.infrastructure.nautilus.run_spec_compiler import (
    CanonicalNautilusRunSpecCompiler,
    NautilusDataSpec,
    NautilusImportableModelSpec,
    NautilusRunSpec,
    NautilusStrategySpec,
    NautilusVenueSpec,
)
from backtest_engine.infrastructure.nautilus.runner import (
    NautilusRunArtifacts,
    _build_backtest_run_config,
)
from backtest_engine.infrastructure.nautilus.strategy_package_resolver import (
    build_default_nautilus_strategy_resolver,
)


class _DisposableBacktestNode(Protocol):
    def dispose(self) -> None: ...


def _write_source_parquet(
    source_root: Path, symbol: str, timeframe: str, start_price: float = 100.0
) -> None:
    source_root.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
        {
            "open": [start_price, start_price + 1, start_price + 2, start_price + 3],
            "high": [start_price + 1, start_price + 2, start_price + 3, start_price + 4],
            "low": [start_price - 1, start_price, start_price + 1, start_price + 2],
            "close": [start_price + 0.5, start_price + 1.5, start_price + 2.5, start_price + 3.5],
            "volume": [10.0, 10.0, 10.0, 10.0],
            "average": [
                start_price + 0.25,
                start_price + 1.25,
                start_price + 2.25,
                start_price + 3.25,
            ],
            "barCount": [5, 5, 5, 5],
        },
        index=pd.to_datetime(
            [
                "2024-01-01T00:00:00Z",
                "2024-01-01T00:30:00Z",
                "2024-01-01T01:00:00Z",
                "2024-01-01T01:30:00Z",
            ],
            utc=True,
        ),
    )
    frame.to_parquet(source_root / f"{symbol}_{timeframe}.parquet")


def _write_dynamic_source_parquet(
    source_root: Path,
    symbol: str,
    timeframe: str,
    *,
    volumes: tuple[float, ...] = (10.0, 12.0, 8.0, 15.0, 9.0),
    flat_ranges: bool = False,
) -> None:
    source_root.mkdir(parents=True, exist_ok=True)
    start_price = 5000.0
    row_count = len(volumes)
    index = pd.date_range("2024-01-01T00:00:00Z", periods=row_count, freq="30min")
    frame = pd.DataFrame(
        {
            "open": [start_price + index_ for index_ in range(row_count)],
            "high": [
                start_price + index_ if flat_ranges else start_price + index_ + 2
                for index_ in range(row_count)
            ],
            "low": [start_price + index_ for index_ in range(row_count)],
            "close": [
                start_price + index_ if flat_ranges else start_price + index_ + 1
                for index_ in range(row_count)
            ],
            "volume": list(volumes),
            "average": [start_price + index_ + 0.5 for index_ in range(row_count)],
            "barCount": [5 for _ in range(row_count)],
        },
        index=index,
    )
    frame.to_parquet(source_root / f"{symbol}_{timeframe}.parquet")


def _write_dynamic_source_frame(
    source_root: Path,
    symbol: str,
    timeframe: str,
    frame: pd.DataFrame,
) -> None:
    source_root.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(source_root / f"{symbol}_{timeframe}.parquet")


def _write_dynamic_execution_costs_yaml(
    costs_path: Path,
    *,
    include_runtime: bool = True,
    volatility_short_window_bars: int = 1,
    volatility_baseline_window_bars: int = 1,
    volatility_floor_price: str = "0.01",
    volatility_signal_method: str = "true_range_atr",
    dynamic_order_types: str = "[market]",
    provenance_venue: str = "CME",
    provenance_timeframe: str = "30m",
) -> None:
    runtime_block = (
        """
dynamic_spread_runtime:
  asset_class_defaults:
    INDEX:
      volatility_short_window_bars: {volatility_short_window_bars}
      volatility_baseline_window_bars: {volatility_baseline_window_bars}
      volatility_floor_price: "{volatility_floor_price}"
      volatility_signal_method: {volatility_signal_method}
      volume_baseline_window_bars: 1
      volume_floor: "1"
      dynamic_order_types: {dynamic_order_types}
      session_buckets:
        - session_bucket_id: regular
          weekdays: [0, 1, 2, 3, 4, 5, 6]
          start_time_utc: "00:00:00"
          end_time_utc: "00:00:00"
""".format(
            volatility_short_window_bars=volatility_short_window_bars,
            volatility_baseline_window_bars=volatility_baseline_window_bars,
            volatility_floor_price=volatility_floor_price,
            volatility_signal_method=volatility_signal_method,
            dynamic_order_types=dynamic_order_types,
        )
        if include_runtime
        else ""
    )
    costs_path.write_text(
        f"""
schema_version: 1
profile_id: default_execution_costs
owner: unit_test
description: Dynamic spread runtime fixture.
asset_class_defaults:
  INDEX:
    commission_model:
      model: fixed_per_contract
      amount_per_contract: "2.25"
      currency: USD
    spread_model:
      model: log_linear_dynamic_half_spread
      base_half_spread_price: "0.50"
      min_half_spread_price: "0.10"
      max_half_spread_price: "2.00"
      volatility_weight: "1.0"
      liquidity_weight: "1.0"
      session_buckets:
        - session_bucket_id: regular
          session_adjustment_log: "0"
      provenance:
        symbol: ES
        venue: {provenance_venue}
        timeframe: {provenance_timeframe}
        provider_or_broker: unit-test
        sample_start_utc: "2024-01-01T00:00:00Z"
        sample_end_utc: "2024-01-02T00:00:00Z"
        row_count: 5
        data_quality_notes: fixture
        sample_role: unit_test
        estimator_method: manual
        conversion_method: already_price_units
    slippage_model:
      model: none_explicit
      reason: unit_test
{runtime_block}
""".lstrip(),
        encoding="utf-8",
    )


def _build_run_spec(
    *,
    run_kind: RunKind = RunKind.SINGLE,
    symbols: tuple[str, ...] = ("ES",),
    execution_policy: BacktestExecutionPolicy | None = None,
) -> BacktestRunSpec:
    strategies = tuple(
        PortfolioStrategySpec(
            slot_id=f"slot-{index + 1}",
            weight_frac=1.0 / len(symbols),
            strategy=StrategySpec(
                strategy_id=f"passive-{symbol.lower()}",
                implementation_id="passive_bar",
                policy_version="v1",
            ),
            legs=(StrategyLegSpec(symbol=symbol),),
        )
        for index, symbol in enumerate(symbols)
    )
    return BacktestRunSpec(
        run_kind=run_kind,
        execution_window=ExecutionWindow(
            start_utc=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end_utc=datetime(2024, 1, 2, tzinfo=timezone.utc),
        ),
        dataset=DatasetSpec(
            source_system=DatasetSource.PARQUET,
            normalization_policy="nautilus_v1",
            schema_version="1",
            symbol_universe=symbols,
            timeframe="30m",
            dataset_version="2026-04-03",
        ),
        strategies=strategies,
        capital_base=Money(amount=Decimal("100000"), currency="USD"),
        execution_policy=execution_policy,
    )


def _build_materializer(source_root: Path, tmp_path: Path) -> FilesystemParquetDatasetNormalizer:
    return FilesystemParquetDatasetNormalizer(
        cache_store=FilesystemParquetCacheStore(source_cache_root=source_root),
        normalized_root=tmp_path / "normalized",
    )


def _execution_costs_hash(costs_path: Path) -> str:
    return execution_costs_config_hash(load_execution_costs(costs_path))


def test_parquet_normalizer_materializes_and_reuses_dataset(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    _write_source_parquet(source_root, "ES", "30m")
    run_spec = _build_run_spec()
    normalizer = _build_materializer(source_root, tmp_path)

    first = normalizer.materialize(run_spec.dataset)
    second = normalizer.materialize(run_spec.dataset)

    assert first.dataset_root == tmp_path / "normalized" / run_spec.dataset.dataset_id
    assert first.manifest_path.is_file()
    assert first.artifacts[0].data_path.is_file()
    assert first.artifacts[0].manifest.nautilus_instrument_id == "ES.CME"
    assert list(pd.read_parquet(first.artifacts[0].data_path).columns) == [
        "ts_event_utc",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "vwap",
        "trade_count",
        "contract_code",
    ]
    assert second.artifacts[0].data_path == first.artifacts[0].data_path


def test_parquet_normalizer_preserves_source_timestamps_without_close_shift(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    _write_source_parquet(source_root, "ES", "30m")
    run_spec = _build_run_spec()

    materialized = _build_materializer(source_root, tmp_path).materialize(run_spec.dataset)

    source_frame = pd.read_parquet(source_root / "ES_30m.parquet")
    normalized = pd.read_parquet(materialized.artifacts[0].data_path)
    source_timestamps = pd.DatetimeIndex(pd.to_datetime(source_frame.index, utc=True))
    normalized_timestamps = pd.DatetimeIndex(pd.to_datetime(normalized["ts_event_utc"], utc=True))
    close_shifted_source_timestamps = source_timestamps + pd.Timedelta(minutes=30)

    assert tuple(normalized_timestamps) == tuple(source_timestamps), (
        "Normalizer must preserve source timestamps exactly in the current contract. "
        "If a completed-bar close shift is introduced, make it an explicit policy "
        "and update this characterization test with the new owner."
    )
    assert tuple(normalized_timestamps) != tuple(close_shifted_source_timestamps), (
        "Normalizer unexpectedly shifted timestamps to bar close. "
        "Verify no other layer also shifts timestamps before accepting this change."
    )
    assert normalized_timestamps.is_monotonic_increasing, (
        "Normalized event timestamps must remain sorted for deterministic bar replay."
    )
    assert not normalized_timestamps.has_duplicates, (
        "Normalized event timestamps must be duplicate-free to avoid ambiguous replay ordering."
    )


def test_nautilus_bar_data_wrangler_preserves_frame_index_as_bar_event_time() -> None:
    from nautilus_trader.model import BarType
    from nautilus_trader.persistence.wranglers import BarDataWrangler

    from backtest_engine.infrastructure.nautilus.catalogs import _build_instrument
    from backtest_engine.infrastructure.nautilus.symbol_map import load_symbol_map

    index = pd.DatetimeIndex(
        pd.to_datetime(
            [
                "2024-01-01T00:00:00Z",
                "2024-01-01T00:30:00Z",
            ],
            utc=True,
        )
    )
    frame = pd.DataFrame(
        {
            "open": [100.0, 101.0],
            "high": [101.0, 102.0],
            "low": [99.0, 100.0],
            "close": [100.5, 101.5],
            "volume": [10.0, 11.0],
        },
        index=index,
    )
    mapping = load_symbol_map().resolve("ES")
    bars = BarDataWrangler(
        BarType.from_str("ES.CME-30-MINUTE-LAST-EXTERNAL"),
        _build_instrument(mapping),
    ).process(frame)

    bar_event_times = tuple(pd.Timestamp(bar.ts_event, unit="ns", tz="UTC") for bar in bars)
    close_shifted_times = tuple(index + pd.Timedelta(minutes=30))
    assert bar_event_times == tuple(index), (
        "Nautilus BarDataWrangler must preserve the DataFrame index as Bar.ts_event "
        "under the current contract. If this changes, re-check lookahead and t+2 risk."
    )
    assert bar_event_times != close_shifted_times, (
        "BarDataWrangler unexpectedly shifted bar timestamps to close time. "
        "Do not add another repository-side close shift without updating this contract."
    )


def test_catalog_builder_writes_nautilus_catalog_from_materialized_dataset(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    _write_source_parquet(source_root, "ES", "30m")
    run_spec = _build_run_spec()
    materialized = _build_materializer(source_root, tmp_path).materialize(run_spec.dataset)
    builder = FilesystemNautilusCatalogBuilder(catalog_cache_root=tmp_path / "catalogs")

    catalog = builder.build(materialized)

    assert isinstance(catalog, CatalogReference)
    assert catalog.catalog_root.is_dir()
    assert catalog.items[0].instrument_id == "ES.CME"
    assert catalog.items[0].bar_type == "ES.CME-30-MINUTE-LAST-EXTERNAL"
    assert all(item.bar_type.endswith("-LAST-EXTERNAL") for item in catalog.items)
    assert any(catalog.catalog_root.rglob("*.parquet"))


def test_run_spec_compiler_builds_concrete_runtime_payload(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    _write_source_parquet(source_root, "ES", "30m")
    run_spec = _build_run_spec()
    compiler = CanonicalNautilusRunSpecCompiler(
        runtime_settings=RuntimeSettings(nautilus_root=tmp_path / "runtime" / "nautilus"),
        dataset_materializer=_build_materializer(source_root, tmp_path),
        catalog_builder=FilesystemNautilusCatalogBuilder(catalog_cache_root=tmp_path / "catalogs"),
        strategy_resolver=build_default_nautilus_strategy_resolver(),
    )

    compiled = compiler.compile(run_spec)

    assert isinstance(compiled, NautilusRunSpec)
    [venue] = compiled.venues
    assert compiled.runtime_root == tmp_path / "runtime" / "nautilus" / run_spec.run_id
    assert compiled.artifact_root == compiled.runtime_root / "artifacts"
    assert run_spec.execution_policy is None
    assert venue.oms_type == "HEDGING"
    assert venue.account_type == "MARGIN"
    assert venue.book_type == "L1_MBP"
    assert compiled.data[0].instrument_id == "ES.CME"
    assert compiled.strategies[0].strategy_path.endswith("PassiveBarStrategy")
    assert compiled.strategies[0].config["bar_type"] == "ES.CME-30-MINUTE-LAST-EXTERNAL"
    assert venue.fill_model is None
    assert venue.fee_model is None


def test_run_spec_compiler_does_not_load_execution_costs_without_policy(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_root = tmp_path / "source"
    _write_source_parquet(source_root, "ES", "30m")
    run_spec = _build_run_spec()
    compiler = CanonicalNautilusRunSpecCompiler(
        runtime_settings=RuntimeSettings(nautilus_root=tmp_path / "runtime" / "nautilus"),
        dataset_materializer=_build_materializer(source_root, tmp_path),
        catalog_builder=FilesystemNautilusCatalogBuilder(catalog_cache_root=tmp_path / "catalogs"),
        strategy_resolver=build_default_nautilus_strategy_resolver(),
    )

    def _fail_if_loaded(*_args, **_kwargs):
        raise AssertionError("execution-cost YAML must not be loaded without execution_policy")

    monkeypatch.setattr(
        "backtest_engine.infrastructure.nautilus.run_spec_compiler.load_execution_costs",
        _fail_if_loaded,
    )

    compiled = compiler.compile(run_spec)

    [venue] = compiled.venues
    assert venue.fill_model is None
    assert venue.fee_model is None


def test_run_spec_compiler_applies_execution_policy_venue_overrides_and_models(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    _write_source_parquet(source_root, "ES", "30m")
    run_spec = _build_run_spec(
        execution_policy=BacktestExecutionPolicy(
            execution_costs=ExecutionCostProfileRef(
                profile_id=DEFAULT_EXECUTION_COST_PROFILE_ID,
            ),
            venue_overrides=ExecutionVenueOverrides(
                oms_type="NETTING",
                account_type="CASH",
                book_type="L2_MBP",
            ),
        ),
    )
    compiler = CanonicalNautilusRunSpecCompiler(
        runtime_settings=RuntimeSettings(nautilus_root=tmp_path / "runtime" / "nautilus"),
        dataset_materializer=_build_materializer(source_root, tmp_path),
        catalog_builder=FilesystemNautilusCatalogBuilder(catalog_cache_root=tmp_path / "catalogs"),
        strategy_resolver=build_default_nautilus_strategy_resolver(),
    )

    compiled = compiler.compile(run_spec)

    [venue] = compiled.venues
    assert run_spec.execution_policy is not None
    assert run_spec.execution_policy.venue_overrides is not None
    assert run_spec.execution_policy.venue_overrides.book_type == "L2_MBP"
    assert venue.oms_type == "NETTING"
    assert venue.account_type == "CASH"
    assert venue.book_type == "L2_MBP"
    assert venue.fill_model is not None
    assert venue.fee_model is not None
    assert venue.fill_model.model_path.endswith("ExecutionPolicyFillModel")
    assert venue.fee_model.model_path.endswith("ExecutionPolicyFeeModel")
    instrument_profiles = venue.fill_model.config["instrument_profiles"]
    assert isinstance(instrument_profiles, dict)
    assert set(instrument_profiles) == {"ES.CME"}
    assert "ES" not in instrument_profiles
    assert venue.fill_model.config["dynamic_spread_features"] == {}
    assert not (compiled.runtime_root / "dynamic_spread_features").exists()


def test_run_spec_compiler_builds_dynamic_spread_feature_artifacts(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    _write_dynamic_source_parquet(source_root, "ES", "30m")
    costs_path = tmp_path / "dynamic_execution_costs.yaml"
    _write_dynamic_execution_costs_yaml(costs_path)
    run_spec = _build_run_spec(
        execution_policy=BacktestExecutionPolicy(
            execution_costs=ExecutionCostProfileRef(
                profile_id=DEFAULT_EXECUTION_COST_PROFILE_ID,
                config_content_hash=_execution_costs_hash(costs_path),
            ),
        ),
    ).model_copy(
        update={
            "execution_window": ExecutionWindow(
                start_utc=datetime(2024, 1, 1, 1, 0, tzinfo=timezone.utc),
                end_utc=datetime(2024, 1, 1, 2, 0, tzinfo=timezone.utc),
            ),
        },
    )
    compiler = CanonicalNautilusRunSpecCompiler(
        runtime_settings=RuntimeSettings(nautilus_root=tmp_path / "runtime" / "nautilus"),
        dataset_materializer=_build_materializer(source_root, tmp_path),
        catalog_builder=FilesystemNautilusCatalogBuilder(catalog_cache_root=tmp_path / "catalogs"),
        strategy_resolver=build_default_nautilus_strategy_resolver(),
        execution_costs_path=costs_path,
    )

    compiled = compiler.compile(run_spec)

    [venue] = compiled.venues
    assert venue.fill_model is not None
    fill_model_config = cast(dict[str, Any], venue.fill_model.config)
    instrument_profiles = cast(dict[str, Any], fill_model_config["instrument_profiles"])
    dynamic_features = cast(dict[str, Any], fill_model_config["dynamic_spread_features"])
    instrument_profile = cast(dict[str, Any], instrument_profiles["ES.CME"])
    profile = cast(dict[str, Any], instrument_profile["profile"])
    spread_model = cast(dict[str, Any], profile["spread_model"])
    assert spread_model["model"] == "log_linear_dynamic_half_spread"
    assert set(dynamic_features) == {"ES.CME"}
    feature_ref = cast(dict[str, Any], dynamic_features["ES.CME"])
    assert Path(str(feature_ref["feature_table_path"])).is_file()
    assert Path(str(feature_ref["manifest_path"])).is_file()
    feature_table = pd.read_parquet(Path(str(feature_ref["feature_table_path"])))
    assert not feature_table.empty
    assert pd.Timestamp(feature_table.iloc[0]["feature_observed_at_utc"]) < pd.Timestamp(
        feature_table.iloc[0]["fill_timestamp_utc"],
    )
    assert pd.Timestamp(feature_table.iloc[0]["feature_observed_at_utc"]) == pd.Timestamp(
        "2024-01-01T00:59:59.999999Z",
    )
    manifest = json.loads(Path(str(feature_ref["manifest_path"])).read_text(encoding="utf-8"))
    assert manifest["feature_table_path"] == "features.parquet"
    assert manifest["volatility_floor_price"] == "0.01"
    assert manifest["volatility_signal_method"] == "true_range_atr"
    assert feature_ref["dynamic_order_types"] == ["market"]


def test_run_spec_compiler_true_range_volatility_detects_gap(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    frame = pd.DataFrame(
        {
            "open": [100.0, 110.0, 111.0, 112.0],
            "high": [101.0, 111.0, 112.0, 113.0],
            "low": [100.0, 110.0, 111.0, 112.0],
            "close": [100.0, 110.0, 111.0, 112.0],
            "volume": [10.0, 10.0, 10.0, 10.0],
            "average": [100.5, 110.5, 111.5, 112.5],
            "barCount": [5, 5, 5, 5],
        },
        index=pd.date_range("2024-01-01T00:00:00Z", periods=4, freq="30min"),
    )
    _write_dynamic_source_frame(source_root, "ES", "30m", frame)
    costs_path = tmp_path / "dynamic_execution_costs.yaml"
    _write_dynamic_execution_costs_yaml(
        costs_path,
        volatility_short_window_bars=2,
        volatility_baseline_window_bars=1,
    )
    run_spec = _build_run_spec(
        execution_policy=BacktestExecutionPolicy(
            execution_costs=ExecutionCostProfileRef(
                profile_id=DEFAULT_EXECUTION_COST_PROFILE_ID,
                config_content_hash=_execution_costs_hash(costs_path),
            ),
        ),
    ).model_copy(
        update={
            "execution_window": ExecutionWindow(
                start_utc=datetime(2024, 1, 1, 1, 30, tzinfo=timezone.utc),
                end_utc=datetime(2024, 1, 1, 2, 0, tzinfo=timezone.utc),
            ),
        },
    )
    compiler = CanonicalNautilusRunSpecCompiler(
        runtime_settings=RuntimeSettings(nautilus_root=tmp_path / "runtime" / "nautilus"),
        dataset_materializer=_build_materializer(source_root, tmp_path),
        catalog_builder=FilesystemNautilusCatalogBuilder(catalog_cache_root=tmp_path / "catalogs"),
        strategy_resolver=build_default_nautilus_strategy_resolver(),
        execution_costs_path=costs_path,
    )

    compiled = compiler.compile(run_spec)

    [venue] = compiled.venues
    assert venue.fill_model is not None
    fill_model_config = cast(dict[str, Any], venue.fill_model.config)
    dynamic_features = cast(dict[str, Any], fill_model_config["dynamic_spread_features"])
    feature_ref = cast(dict[str, Any], dynamic_features["ES.CME"])
    feature_table = pd.read_parquet(Path(str(feature_ref["feature_table_path"])))
    observed_signal = float(feature_table.iloc[0]["volatility_stress_signal"])
    assert observed_signal == pytest.approx(math.log(3.25))


def test_run_spec_compiler_volatility_floor_is_explicit_not_tick_size(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    frame = pd.DataFrame(
        {
            "open": [100.0, 100.0, 100.02, 100.10],
            "high": [100.0, 100.05, 100.17, 100.20],
            "low": [100.0, 100.0, 100.02, 100.10],
            "close": [100.0, 100.02, 100.10, 100.15],
            "volume": [10.0, 10.0, 10.0, 10.0],
            "average": [100.0, 100.03, 100.10, 100.15],
            "barCount": [5, 5, 5, 5],
        },
        index=pd.date_range("2024-01-01T00:00:00Z", periods=4, freq="30min"),
    )
    _write_dynamic_source_frame(source_root, "ES", "30m", frame)
    costs_path = tmp_path / "dynamic_execution_costs.yaml"
    _write_dynamic_execution_costs_yaml(
        costs_path,
        volatility_short_window_bars=1,
        volatility_baseline_window_bars=2,
        volatility_floor_price="0.10",
    )
    run_spec = _build_run_spec(
        execution_policy=BacktestExecutionPolicy(
            execution_costs=ExecutionCostProfileRef(
                profile_id=DEFAULT_EXECUTION_COST_PROFILE_ID,
                config_content_hash=_execution_costs_hash(costs_path),
            ),
        ),
    ).model_copy(
        update={
            "execution_window": ExecutionWindow(
                start_utc=datetime(2024, 1, 1, 1, 30, tzinfo=timezone.utc),
                end_utc=datetime(2024, 1, 1, 2, 0, tzinfo=timezone.utc),
            ),
        },
    )
    compiler = CanonicalNautilusRunSpecCompiler(
        runtime_settings=RuntimeSettings(nautilus_root=tmp_path / "runtime" / "nautilus"),
        dataset_materializer=_build_materializer(source_root, tmp_path),
        catalog_builder=FilesystemNautilusCatalogBuilder(catalog_cache_root=tmp_path / "catalogs"),
        strategy_resolver=build_default_nautilus_strategy_resolver(),
        execution_costs_path=costs_path,
    )

    compiled = compiler.compile(run_spec)

    [venue] = compiled.venues
    assert venue.fill_model is not None
    fill_model_config = cast(dict[str, Any], venue.fill_model.config)
    dynamic_features = cast(dict[str, Any], fill_model_config["dynamic_spread_features"])
    feature_ref = cast(dict[str, Any], dynamic_features["ES.CME"])
    feature_table = pd.read_parquet(Path(str(feature_ref["feature_table_path"])))
    observed_signal = float(feature_table.iloc[0]["volatility_stress_signal"])
    assert observed_signal == pytest.approx(math.log(1.5))
    assert observed_signal != 0.0


def test_run_spec_compiler_requires_hash_for_custom_execution_costs(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    _write_dynamic_source_parquet(source_root, "ES", "30m")
    costs_path = tmp_path / "dynamic_execution_costs.yaml"
    _write_dynamic_execution_costs_yaml(costs_path)
    run_spec = _build_run_spec(
        execution_policy=BacktestExecutionPolicy(
            execution_costs=ExecutionCostProfileRef(
                profile_id=DEFAULT_EXECUTION_COST_PROFILE_ID,
            ),
        ),
    ).model_copy(
        update={
            "execution_window": ExecutionWindow(
                start_utc=datetime(2024, 1, 1, 1, 0, tzinfo=timezone.utc),
                end_utc=datetime(2024, 1, 1, 2, 0, tzinfo=timezone.utc),
            ),
        },
    )
    compiler = CanonicalNautilusRunSpecCompiler(
        runtime_settings=RuntimeSettings(nautilus_root=tmp_path / "runtime" / "nautilus"),
        dataset_materializer=_build_materializer(source_root, tmp_path),
        catalog_builder=FilesystemNautilusCatalogBuilder(catalog_cache_root=tmp_path / "catalogs"),
        strategy_resolver=build_default_nautilus_strategy_resolver(),
        execution_costs_path=costs_path,
    )

    with pytest.raises(InfrastructureError, match="requires config_content_hash"):
        compiler.compile(run_spec)


def test_run_spec_compiler_rejects_mismatched_execution_cost_hash(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    _write_dynamic_source_parquet(source_root, "ES", "30m")
    costs_path = tmp_path / "dynamic_execution_costs.yaml"
    _write_dynamic_execution_costs_yaml(costs_path)
    run_spec = _build_run_spec(
        execution_policy=BacktestExecutionPolicy(
            execution_costs=ExecutionCostProfileRef(
                profile_id=DEFAULT_EXECUTION_COST_PROFILE_ID,
                config_content_hash="0" * 64,
            ),
        ),
    ).model_copy(
        update={
            "execution_window": ExecutionWindow(
                start_utc=datetime(2024, 1, 1, 1, 0, tzinfo=timezone.utc),
                end_utc=datetime(2024, 1, 1, 2, 0, tzinfo=timezone.utc),
            ),
        },
    )
    compiler = CanonicalNautilusRunSpecCompiler(
        runtime_settings=RuntimeSettings(nautilus_root=tmp_path / "runtime" / "nautilus"),
        dataset_materializer=_build_materializer(source_root, tmp_path),
        catalog_builder=FilesystemNautilusCatalogBuilder(catalog_cache_root=tmp_path / "catalogs"),
        strategy_resolver=build_default_nautilus_strategy_resolver(),
        execution_costs_path=costs_path,
    )

    with pytest.raises(InfrastructureError, match="config_content_hash does not match"):
        compiler.compile(run_spec)


@pytest.mark.parametrize(
    ("cost_kwargs", "match"),
    (
        ({"provenance_timeframe": "15m"}, "provenance timeframe"),
        ({"provenance_venue": "SIM"}, "provenance venue"),
    ),
)
def test_run_spec_compiler_rejects_dynamic_provenance_mismatches(
    tmp_path: Path,
    cost_kwargs: dict[str, Any],
    match: str,
) -> None:
    source_root = tmp_path / "source"
    _write_dynamic_source_parquet(source_root, "ES", "30m")
    costs_path = tmp_path / "dynamic_execution_costs.yaml"
    _write_dynamic_execution_costs_yaml(costs_path, **cost_kwargs)
    run_spec = _build_run_spec(
        execution_policy=BacktestExecutionPolicy(
            execution_costs=ExecutionCostProfileRef(
                profile_id=DEFAULT_EXECUTION_COST_PROFILE_ID,
                config_content_hash=_execution_costs_hash(costs_path),
            ),
        ),
    ).model_copy(
        update={
            "execution_window": ExecutionWindow(
                start_utc=datetime(2024, 1, 1, 1, 0, tzinfo=timezone.utc),
                end_utc=datetime(2024, 1, 1, 2, 0, tzinfo=timezone.utc),
            ),
        },
    )
    compiler = CanonicalNautilusRunSpecCompiler(
        runtime_settings=RuntimeSettings(nautilus_root=tmp_path / "runtime" / "nautilus"),
        dataset_materializer=_build_materializer(source_root, tmp_path),
        catalog_builder=FilesystemNautilusCatalogBuilder(catalog_cache_root=tmp_path / "catalogs"),
        strategy_resolver=build_default_nautilus_strategy_resolver(),
        execution_costs_path=costs_path,
    )

    with pytest.raises(InfrastructureError, match=match):
        compiler.compile(run_spec)


def test_dynamic_spread_feature_artifact_paths_are_collision_resistant() -> None:
    assert _artifact_path_part("BTC/USDT.SIM") != _artifact_path_part("BTC_USDT.SIM")


@pytest.mark.parametrize(
    ("column_updates", "match"),
    (
        ({"high": [5000.0, 4999.0]}, "high values below low values"),
        ({"high": [5000.0, float("nan")]}, "non-finite OHLCV values"),
        ({"close": [5000.0, 5001.5]}, "close values outside high-low range"),
        ({"close": [5000.0, 4999.5]}, "close values outside high-low range"),
        ({"volume": [10.0, -1.0]}, "negative volume"),
        ({"close": None}, "missing dynamic spread feature columns"),
    ),
)
def test_dynamic_spread_feature_reader_rejects_invalid_ohlcv(
    tmp_path: Path,
    column_updates: dict[str, list[float] | None],
    match: str,
) -> None:
    bars_path = tmp_path / "bars.parquet"
    frame = pd.DataFrame(
        {
            "ts_event_utc": pd.to_datetime(
                ["2024-01-01T00:00:00Z", "2024-01-01T00:30:00Z"],
                utc=True,
            ),
            "high": [5000.0, 5001.0],
            "low": [5000.0, 5000.0],
            "close": [5000.0, 5000.5],
            "volume": [10.0, 10.0],
        },
    )
    for column_name, values in column_updates.items():
        if values is None:
            frame = frame.drop(columns=[column_name])
        else:
            frame[column_name] = values
    frame.to_parquet(bars_path, index=False)

    with pytest.raises(InfrastructureError, match=match):
        _read_normalized_bars(bars_path, "ES.CME")


def test_run_spec_compiler_fails_dynamic_spread_without_runtime_config(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    _write_dynamic_source_parquet(source_root, "ES", "30m")
    costs_path = tmp_path / "dynamic_without_runtime.yaml"
    _write_dynamic_execution_costs_yaml(costs_path, include_runtime=False)
    run_spec = _build_run_spec(
        execution_policy=BacktestExecutionPolicy(
            execution_costs=ExecutionCostProfileRef(
                profile_id=DEFAULT_EXECUTION_COST_PROFILE_ID,
                config_content_hash=_execution_costs_hash(costs_path),
            ),
        ),
    )
    compiler = CanonicalNautilusRunSpecCompiler(
        runtime_settings=RuntimeSettings(nautilus_root=tmp_path / "runtime" / "nautilus"),
        dataset_materializer=_build_materializer(source_root, tmp_path),
        catalog_builder=FilesystemNautilusCatalogBuilder(catalog_cache_root=tmp_path / "catalogs"),
        strategy_resolver=build_default_nautilus_strategy_resolver(),
        execution_costs_path=costs_path,
    )

    with pytest.raises(InfrastructureError, match="requires dynamic_spread_runtime"):
        compiler.compile(run_spec)


def test_run_spec_compiler_fails_dynamic_spread_warmup_before_first_feature(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    _write_dynamic_source_parquet(source_root, "ES", "30m")
    costs_path = tmp_path / "dynamic_execution_costs.yaml"
    _write_dynamic_execution_costs_yaml(costs_path)
    run_spec = _build_run_spec(
        execution_policy=BacktestExecutionPolicy(
            execution_costs=ExecutionCostProfileRef(
                profile_id=DEFAULT_EXECUTION_COST_PROFILE_ID,
                config_content_hash=_execution_costs_hash(costs_path),
            ),
        ),
    )
    compiler = CanonicalNautilusRunSpecCompiler(
        runtime_settings=RuntimeSettings(nautilus_root=tmp_path / "runtime" / "nautilus"),
        dataset_materializer=_build_materializer(source_root, tmp_path),
        catalog_builder=FilesystemNautilusCatalogBuilder(catalog_cache_root=tmp_path / "catalogs"),
        strategy_resolver=build_default_nautilus_strategy_resolver(),
        execution_costs_path=costs_path,
    )

    with pytest.raises(
        InfrastructureError, match="before first eligible dynamic spread feature row"
    ):
        compiler.compile(run_spec)


def test_run_spec_compiler_blocks_dynamic_spread_non_positive_volume(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    _write_dynamic_source_parquet(source_root, "ES", "30m", volumes=(10.0, 0.0, 10.0, 10.0, 10.0))
    costs_path = tmp_path / "dynamic_execution_costs.yaml"
    _write_dynamic_execution_costs_yaml(costs_path)
    run_spec = _build_run_spec(
        execution_policy=BacktestExecutionPolicy(
            execution_costs=ExecutionCostProfileRef(
                profile_id=DEFAULT_EXECUTION_COST_PROFILE_ID,
                config_content_hash=_execution_costs_hash(costs_path),
            ),
        ),
    ).model_copy(
        update={
            "execution_window": ExecutionWindow(
                start_utc=datetime(2024, 1, 1, 1, 0, tzinfo=timezone.utc),
                end_utc=datetime(2024, 1, 1, 2, 0, tzinfo=timezone.utc),
            ),
        },
    )
    compiler = CanonicalNautilusRunSpecCompiler(
        runtime_settings=RuntimeSettings(nautilus_root=tmp_path / "runtime" / "nautilus"),
        dataset_materializer=_build_materializer(source_root, tmp_path),
        catalog_builder=FilesystemNautilusCatalogBuilder(catalog_cache_root=tmp_path / "catalogs"),
        strategy_resolver=build_default_nautilus_strategy_resolver(),
        execution_costs_path=costs_path,
    )

    with pytest.raises(InfrastructureError, match="requires positive observed volume"):
        compiler.compile(run_spec)


def test_run_spec_compiler_floors_flat_dynamic_volatility_ranges(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    _write_dynamic_source_parquet(source_root, "ES", "30m", flat_ranges=True)
    costs_path = tmp_path / "dynamic_execution_costs.yaml"
    _write_dynamic_execution_costs_yaml(costs_path)
    run_spec = _build_run_spec(
        execution_policy=BacktestExecutionPolicy(
            execution_costs=ExecutionCostProfileRef(
                profile_id=DEFAULT_EXECUTION_COST_PROFILE_ID,
                config_content_hash=_execution_costs_hash(costs_path),
            ),
        ),
    ).model_copy(
        update={
            "execution_window": ExecutionWindow(
                start_utc=datetime(2024, 1, 1, 1, 0, tzinfo=timezone.utc),
                end_utc=datetime(2024, 1, 1, 2, 0, tzinfo=timezone.utc),
            ),
        },
    )
    compiler = CanonicalNautilusRunSpecCompiler(
        runtime_settings=RuntimeSettings(nautilus_root=tmp_path / "runtime" / "nautilus"),
        dataset_materializer=_build_materializer(source_root, tmp_path),
        catalog_builder=FilesystemNautilusCatalogBuilder(catalog_cache_root=tmp_path / "catalogs"),
        strategy_resolver=build_default_nautilus_strategy_resolver(),
        execution_costs_path=costs_path,
    )

    compiled = compiler.compile(run_spec)

    [venue] = compiled.venues
    assert venue.fill_model is not None
    fill_model_config = cast(dict[str, Any], venue.fill_model.config)
    dynamic_features = cast(dict[str, Any], fill_model_config["dynamic_spread_features"])
    feature_ref = cast(dict[str, Any], dynamic_features["ES.CME"])
    feature_table = pd.read_parquet(Path(str(feature_ref["feature_table_path"])))
    assert set(feature_table["volatility_stress_signal"]) == {"0.0"}


def test_run_spec_compiler_applies_partial_venue_overrides_field_by_field(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    _write_source_parquet(source_root, "ES", "30m")
    run_spec = _build_run_spec(
        execution_policy=BacktestExecutionPolicy(
            execution_costs=ExecutionCostProfileRef(
                profile_id=DEFAULT_EXECUTION_COST_PROFILE_ID,
            ),
            venue_overrides=ExecutionVenueOverrides(book_type="L2_MBP"),
        ),
    )
    compiler = CanonicalNautilusRunSpecCompiler(
        runtime_settings=RuntimeSettings(nautilus_root=tmp_path / "runtime" / "nautilus"),
        dataset_materializer=_build_materializer(source_root, tmp_path),
        catalog_builder=FilesystemNautilusCatalogBuilder(catalog_cache_root=tmp_path / "catalogs"),
        strategy_resolver=build_default_nautilus_strategy_resolver(),
    )

    compiled = compiler.compile(run_spec)

    [venue] = compiled.venues
    assert venue.oms_type == "HEDGING"
    assert venue.account_type == "MARGIN"
    assert venue.book_type == "L2_MBP"


def test_run_spec_compiler_fails_missing_execution_cost_coverage(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    _write_source_parquet(source_root, "ES", "30m")
    costs_path = tmp_path / "execution_costs.yaml"
    costs_path.write_text(
        """
schema_version: 1
profile_id: default_execution_costs
owner: unit_test
description: Missing INDEX coverage for compile-time failure.
asset_class_defaults:
  FX:
    commission_model:
      model: rate_of_notional
      commission_rate_bps: "0.20"
    spread_model:
      model: static_half_spread_ticks
      half_spread_ticks: "5"
    slippage_model:
      model: fixed_ticks
      slippage_ticks: "1"
""".lstrip(),
        encoding="utf-8",
    )
    run_spec = _build_run_spec(
        execution_policy=BacktestExecutionPolicy(
            execution_costs=ExecutionCostProfileRef(
                profile_id=DEFAULT_EXECUTION_COST_PROFILE_ID,
                config_content_hash=_execution_costs_hash(costs_path),
            ),
        ),
    )
    compiler = CanonicalNautilusRunSpecCompiler(
        runtime_settings=RuntimeSettings(nautilus_root=tmp_path / "runtime" / "nautilus"),
        dataset_materializer=_build_materializer(source_root, tmp_path),
        catalog_builder=FilesystemNautilusCatalogBuilder(catalog_cache_root=tmp_path / "catalogs"),
        strategy_resolver=build_default_nautilus_strategy_resolver(),
        execution_costs_path=costs_path,
    )

    with pytest.raises(InfrastructureError, match="failed to resolve execution-cost profile"):
        compiler.compile(run_spec)


def test_backtest_run_config_remains_bar_only_without_explicit_fill_or_latency_models(
    tmp_path: Path,
) -> None:
    compiled = NautilusRunSpec(
        run_id="run-characterization",
        dataset_id="dataset-characterization",
        runtime_root=tmp_path / "runtime",
        artifact_root=tmp_path / "runtime" / "artifacts",
        annualization_policy="252d",
        catalog=CatalogReference(
            dataset_id="dataset-characterization",
            catalog_root=tmp_path / "catalogs",
        ),
        venues=(
            NautilusVenueSpec(
                name="SIM",
                base_currency="USD",
                starting_balances=("100000 USD",),
            ),
        ),
        data=(
            NautilusDataSpec(
                catalog_root=tmp_path / "catalogs",
                instrument_id="ES.CME",
                bar_type="ES.CME-30-MINUTE-LAST-EXTERNAL",
                start_time_utc=datetime(2024, 1, 1, tzinfo=timezone.utc),
                end_time_utc=datetime(2024, 1, 2, tzinfo=timezone.utc),
            ),
        ),
        strategies=(),
        strategy_ids=(),
    )

    config = _build_backtest_run_config(compiled)

    from nautilus_trader.model import Bar

    [data_config] = config.data
    [venue_config] = config.venues
    assert data_config.data_cls is Bar
    assert data_config.bar_types == ["ES.CME-30-MINUTE-LAST-EXTERNAL"]
    assert data_config.instrument_ids == ["ES.CME"]
    assert venue_config.fill_model is None
    assert venue_config.fee_model is None
    assert venue_config.latency_model is None


def test_backtest_run_config_adapts_compiled_importable_execution_models(
    tmp_path: Path,
) -> None:
    model_spec = NautilusImportableModelSpec(
        model_path="backtest_engine.infrastructure.nautilus.execution_models:ExecutionPolicyFillModel",
        config_path="backtest_engine.infrastructure.nautilus.execution_models:ExecutionPolicyModelConfig",
        config={"instrument_profiles": {}},
    )
    compiled = NautilusRunSpec(
        run_id="run-characterization",
        dataset_id="dataset-characterization",
        runtime_root=tmp_path / "runtime",
        artifact_root=tmp_path / "runtime" / "artifacts",
        annualization_policy="252d",
        catalog=CatalogReference(
            dataset_id="dataset-characterization",
            catalog_root=tmp_path / "catalogs",
        ),
        venues=(
            NautilusVenueSpec(
                name="SIM",
                base_currency="USD",
                starting_balances=("100000 USD",),
                fill_model=model_spec,
                fee_model=NautilusImportableModelSpec(
                    model_path=(
                        "backtest_engine.infrastructure.nautilus.execution_models:"
                        "ExecutionPolicyFeeModel"
                    ),
                    config_path=model_spec.config_path,
                    config=model_spec.config,
                ),
            ),
        ),
        data=(),
        strategies=(),
        strategy_ids=(),
    )

    config = _build_backtest_run_config(compiled)

    [venue_config] = config.venues
    assert venue_config.fill_model is not None
    assert venue_config.fee_model is not None
    assert venue_config.fill_model.fill_model_path.endswith("ExecutionPolicyFillModel")
    assert venue_config.fee_model.fee_model_path.endswith("ExecutionPolicyFeeModel")


def test_strategy_bar_replay_observes_open_event_timestamps_without_future_bar(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from nautilus_trader.backtest.node import BacktestNode

    test_fixture_dir = Path(__file__).parents[2] / "fixtures"
    monkeypatch.syspath_prepend(str(test_fixture_dir))
    source_root = tmp_path / "source"
    _write_source_parquet(source_root, "ES", "30m")
    run_spec = _build_run_spec()
    materialized = _build_materializer(source_root, tmp_path).materialize(run_spec.dataset)
    catalog = FilesystemNautilusCatalogBuilder(catalog_cache_root=tmp_path / "catalogs").build(
        materialized,
    )
    [catalog_item] = catalog.items
    observed_path = tmp_path / "observed" / "bar_replay.json"
    source_frame = pd.read_parquet(source_root / "ES_30m.parquet")
    source_timestamps = tuple(
        pd.DatetimeIndex(pd.to_datetime(source_frame.index, utc=True)),
    )
    expected_ts_event_ns = [int(timestamp.value) for timestamp in source_timestamps]
    strategy_config: dict[str, JsonValue] = {
        "bar_type": catalog_item.bar_type,
        "expected_ts_event_ns": cast(JsonValue, expected_ts_event_ns),
        "output_path": observed_path.as_posix(),
    }
    compiled = NautilusRunSpec(
        run_id="run-bar-replay-causality",
        dataset_id=run_spec.dataset.dataset_id,
        runtime_root=tmp_path / "runtime",
        artifact_root=tmp_path / "runtime" / "artifacts",
        annualization_policy="252d",
        catalog=catalog,
        venues=(
            NautilusVenueSpec(
                name=catalog_item.venue,
                base_currency=catalog_item.quote_currency,
                starting_balances=("100000 USD",),
            ),
        ),
        data=(
            NautilusDataSpec(
                catalog_root=catalog.catalog_root,
                instrument_id=catalog_item.instrument_id,
                bar_type=catalog_item.bar_type,
                start_time_utc=datetime(2024, 1, 1, tzinfo=timezone.utc),
                end_time_utc=datetime(2024, 1, 2, tzinfo=timezone.utc),
            ),
        ),
        strategies=(
            NautilusStrategySpec(
                strategy_id="observing-bar-replay",
                implementation_id="test_observing_bar_replay",
                strategy_path="nautilus_observing_strategy:ObservingBarReplayStrategy",
                config_path="nautilus_observing_strategy:ObservingBarReplayStrategyConfig",
                config=strategy_config,
            ),
        ),
        strategy_ids=("observing-bar-replay",),
    )
    node = BacktestNode(configs=[_build_backtest_run_config(compiled)])
    try:
        node.run()
    finally:
        cast(_DisposableBacktestNode, node).dispose()

    observations = json.loads(observed_path.read_text(encoding="utf-8"))
    observed_ts_event_ns = observations["observed_ts_event_ns"]
    records = observations["records"]

    assert observed_ts_event_ns == expected_ts_event_ns
    assert [record["ts_event_ns"] for record in records] == expected_ts_event_ns
    assert observed_ts_event_ns == sorted(observed_ts_event_ns)
    assert [record["observed_count_before"] for record in records] == list(range(len(records)))
    assert not any(record["next_bar_seen_before"] for record in records)


class _FakeAnalyzer:
    def returns(self) -> pd.Series:
        return pd.Series([0.0, 0.0], dtype=float)


class _FakePortfolio:
    analyzer = _FakeAnalyzer()


class _FakeTrader:
    def generate_account_report(self, _venue) -> pd.DataFrame:
        return pd.DataFrame({"equity": [100000.0]})

    def generate_positions_report(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "is_snapshot": [False, False],
                "ts_closed": [pd.Timestamp("2024-01-01T01:00:00Z"), pd.NaT],
                "realized_pnl": ["125.5 USD", None],
                "commissions": ["2.5 USD", "1.5 USD"],
            }
        )

    def generate_orders_report(self) -> pd.DataFrame:
        return pd.DataFrame({"info": [{"source": "unit-test"}]})

    def generate_order_fills_report(self) -> pd.DataFrame:
        return pd.DataFrame({"commissions": [{"amount": 2.5}]})


class _FakeEngine:
    trader = _FakeTrader()
    portfolio = _FakePortfolio()


class _FakeRunResult:
    total_orders = 2
    total_positions = 1
    total_events = 3
    stats_pnls = {"USD": {"PnL (total)": 125.5}}


def _build_compiled_spec(tmp_path: Path) -> NautilusRunSpec:
    return NautilusRunSpec(
        run_id="run-unit-test",
        dataset_id="dataset-unit-test",
        runtime_root=tmp_path / "runtime",
        artifact_root=tmp_path / "runtime" / "artifacts",
        annualization_policy="252d",
        catalog=CatalogReference(
            dataset_id="dataset-unit-test",
            catalog_root=tmp_path / "catalogs",
        ),
        venues=(),
        data=(),
        strategies=(),
        strategy_ids=(),
    )


def test_report_writer_persists_normalized_runtime_reports(tmp_path: Path) -> None:
    writer = NautilusReportWriter()
    compiled = _build_compiled_spec(tmp_path)

    artifacts = writer.persist(
        compiled_spec=compiled,
        run_result=_FakeRunResult(),
        engine=_FakeEngine(),
        runtime_sec=1.25,
        run_spec_path=tmp_path / "runtime" / "compiled_run_spec.json",
    )

    assert Path(artifacts.report_locations["summary"]).is_file()
    assert Path(artifacts.report_locations["fills_report"]).is_file()
    assert artifacts.metrics["total_orders"] == 2.0
    assert artifacts.metrics["fill_count"] == 1.0
    assert artifacts.metrics["order_count"] == 1.0
    assert artifacts.metrics["position_count"] == 2.0
    assert artifacts.metrics["closed_position_count"] == 1.0
    assert artifacts.metrics["trade_count"] == 1.0
    orders_report = pd.read_parquet(artifacts.report_locations["orders_report"])
    fills_report = pd.read_parquet(artifacts.report_locations["fills_report"])
    assert orders_report.iloc[0]["info"] == '{"source": "unit-test"}'
    assert fills_report.iloc[0]["commissions"] == '{"amount": 2.5}'


def test_portfolio_projector_builds_projection_from_runtime_reports(tmp_path: Path) -> None:
    positions_report = pd.DataFrame(
        {
            "is_snapshot": [False, False, True],
            "ts_closed": [pd.Timestamp("2024-01-01T01:00:00Z"), pd.NaT, pd.NaT],
            "realized_pnl": ["125.5 USD", None, None],
            "commissions": ["2.5 USD", "1.5 USD", "0.5 USD"],
        }
    )
    account_report = pd.DataFrame({"equity": [100000.0, 100250.0]})
    report_root = tmp_path / "runtime"
    report_root.mkdir(parents=True)
    positions_path = report_root / "positions_report.parquet"
    account_path = report_root / "account_report.parquet"
    positions_report.to_parquet(positions_path)
    account_report.to_parquet(account_path)
    run_spec = _build_run_spec(run_kind=RunKind.PORTFOLIO, symbols=("ES", "NQ"))
    projector = FilesystemPortfolioProjector()

    projection = projector.project(
        run_spec=run_spec,
        artifacts=NautilusRunArtifacts(
            run_id=run_spec.run_id,
            runtime_root=report_root.as_posix(),
            report_locations={
                "positions_report": positions_path.as_posix(),
                "account_report": account_path.as_posix(),
            },
        ),
    )

    assert projection.position_count == 2
    assert projection.summary["open_position_count"] == 1
    assert projection.summary["closed_position_count"] == 1
    assert projection.summary["realized_pnl"] == 125.5
    assert projection.summary["commission_paid"] == 4.5
    assert projection.summary["ending_balance"] == 100250.0
    assert Path(projection.artifact_locations["portfolio_projection"]).is_file()
