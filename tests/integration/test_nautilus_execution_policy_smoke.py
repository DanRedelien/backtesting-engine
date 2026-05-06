from __future__ import annotations

import json
from decimal import Decimal
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol, cast

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
    ExecutionWindow,
    RuntimeSettings,
)
from backtest_engine.core.enums import DatasetSource, RunKind
from backtest_engine.core.money import Money
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
from backtest_engine.infrastructure.nautilus.reports import NautilusReportWriter
from backtest_engine.infrastructure.nautilus.run_spec_compiler import (
    CanonicalNautilusRunSpecCompiler,
    NautilusImportableModelSpec,
    NautilusRunSpec,
    NautilusStrategySpec,
)
from backtest_engine.infrastructure.nautilus.runner import _build_backtest_run_config


class _DisposableBacktestNode(Protocol):
    def dispose(self) -> None: ...


class _RunnableBacktestNode(_DisposableBacktestNode, Protocol):
    def run(self) -> list[Any]: ...

    def get_engine(self, config_id: Any) -> Any | None: ...


class _MarketOrderStrategyResolver:
    def resolve(
        self,
        strategy_spec: object,
        catalog: CatalogReference,
        slot_sizing: object | None = None,
    ) -> NautilusStrategySpec:
        del strategy_spec, slot_sizing
        [item] = catalog.items
        return NautilusStrategySpec(
            strategy_id="market-order-smoke",
            implementation_id="test_market_order",
            strategy_path=("nautilus_market_order_strategy:MarketOrderOnFirstBarStrategy"),
            config_path=("nautilus_market_order_strategy:MarketOrderOnFirstBarStrategyConfig"),
            config={
                "instrument_id": item.instrument_id,
                "bar_type": item.bar_type,
                "side": "BUY",
                "quantity": "1",
            },
        )


@pytest.mark.integration
@pytest.mark.slow
def test_execution_policy_changes_persisted_nautilus_fill_reports(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nautilus_trader.backtest.node import BacktestNode

    test_fixture_dir = Path(__file__).parents[1] / "fixtures"
    monkeypatch.syspath_prepend(str(test_fixture_dir))
    source_root = tmp_path / "source"
    _write_source_parquet(source_root, "EURUSD", "30m", start_price=1.1)
    runtime_settings = RuntimeSettings(nautilus_root=tmp_path / "runtime" / "nautilus")
    baseline_compiled = _compile_market_order_run(
        tmp_path=tmp_path,
        source_root=source_root,
        runtime_settings=runtime_settings,
        execution_policy=None,
    )
    policy_compiled = _compile_market_order_run(
        tmp_path=tmp_path,
        source_root=source_root,
        runtime_settings=runtime_settings,
        execution_policy=BacktestExecutionPolicy(
            execution_costs=ExecutionCostProfileRef(
                profile_id=DEFAULT_EXECUTION_COST_PROFILE_ID,
            ),
        ),
    )

    baseline_fills = _run_and_persist_fills(baseline_compiled, BacktestNode)
    policy_fills = _run_and_persist_fills(policy_compiled, BacktestNode)

    assert not baseline_fills.empty
    assert not policy_fills.empty
    assert _first_fill_price(policy_fills) != _first_fill_price(baseline_fills)


@pytest.mark.integration
@pytest.mark.slow
def test_dynamic_spread_policy_uses_compiled_feature_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nautilus_trader.backtest.node import BacktestNode

    test_fixture_dir = Path(__file__).parents[1] / "fixtures"
    monkeypatch.syspath_prepend(str(test_fixture_dir))
    source_root = tmp_path / "source"
    costs_path = tmp_path / "dynamic_execution_costs.yaml"
    _write_source_parquet(source_root, "EURUSD", "30m", start_price=1.1, gap_volatility=True)
    _write_dynamic_execution_costs_yaml(costs_path)
    dynamic_config_hash = _execution_costs_hash(costs_path)
    runtime_settings = RuntimeSettings(nautilus_root=tmp_path / "runtime" / "nautilus")
    baseline_compiled = _compile_market_order_run(
        tmp_path=tmp_path,
        source_root=source_root,
        runtime_settings=runtime_settings,
        execution_policy=None,
        execution_start_utc=datetime(2024, 1, 1, 1, 30, tzinfo=timezone.utc),
    )
    dynamic_policy = BacktestExecutionPolicy(
        execution_costs=ExecutionCostProfileRef(
            profile_id=DEFAULT_EXECUTION_COST_PROFILE_ID,
            config_content_hash=dynamic_config_hash,
        ),
    )
    different_hash_policy = BacktestExecutionPolicy(
        execution_costs=ExecutionCostProfileRef(
            profile_id=DEFAULT_EXECUTION_COST_PROFILE_ID,
            config_content_hash="f" * 64,
        ),
    )
    assert (
        _build_run_spec(
            execution_policy=dynamic_policy,
            execution_start_utc=datetime(2024, 1, 1, 1, 30, tzinfo=timezone.utc),
        ).content_hash
        != _build_run_spec(
            execution_policy=different_hash_policy,
            execution_start_utc=datetime(2024, 1, 1, 1, 30, tzinfo=timezone.utc),
        ).content_hash
    )
    dynamic_compiled = _compile_market_order_run(
        tmp_path=tmp_path,
        source_root=source_root,
        runtime_settings=runtime_settings,
        execution_policy=dynamic_policy,
        execution_costs_path=costs_path,
        execution_start_utc=datetime(2024, 1, 1, 1, 30, tzinfo=timezone.utc),
    )

    [venue] = dynamic_compiled.venues
    assert venue.fill_model is not None
    fill_config = cast(dict[str, Any], venue.fill_model.config)
    instrument_profiles = cast(dict[str, Any], fill_config["instrument_profiles"])
    assert instrument_profiles["EUR/USD.SIM"]["profile"]["spread_model"]["model"] == (
        "log_linear_dynamic_half_spread"
    )
    dynamic_features = cast(dict[str, dict[str, Any]], fill_config["dynamic_spread_features"])
    assert set(dynamic_features) == {"EUR/USD.SIM"}
    assert Path(str(dynamic_features["EUR/USD.SIM"]["manifest_path"])).is_file()

    baseline_fills = _run_and_persist_fills(baseline_compiled, BacktestNode)
    dynamic_fills = _run_and_persist_fills(dynamic_compiled, BacktestNode)

    assert not dynamic_fills.empty
    assert _first_fill_price(dynamic_fills) == Decimal("1.2525")
    assert _first_fill_price(dynamic_fills) != _first_fill_price(baseline_fills)


@pytest.mark.integration
@pytest.mark.slow
def test_market_order_fill_model_timestamp_matches_fill_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nautilus_trader.backtest.node import BacktestNode

    test_fixture_dir = Path(__file__).parents[1] / "fixtures"
    monkeypatch.syspath_prepend(str(test_fixture_dir))
    source_root = tmp_path / "source"
    observation_path = tmp_path / "observed" / "market_timestamps.json"
    _write_source_parquet(source_root, "EURUSD", "30m", start_price=1.1)
    compiled = _compile_market_order_run(
        tmp_path=tmp_path,
        source_root=source_root,
        runtime_settings=RuntimeSettings(nautilus_root=tmp_path / "runtime" / "nautilus"),
        execution_policy=None,
    )
    [venue] = compiled.venues
    compiled = compiled.model_copy(
        update={
            "venues": (
                venue.model_copy(
                    update={
                        "fill_model": NautilusImportableModelSpec(
                            model_path=(
                                "nautilus_timestamp_fill_model:TimestampObservingFillModel"
                            ),
                            config_path=(
                                "nautilus_timestamp_fill_model:TimestampObservingFillModelConfig"
                            ),
                            config={"output_path": observation_path.as_posix()},
                        ),
                    },
                ),
            ),
        },
    )

    fills = _run_and_persist_fills(compiled, BacktestNode)

    records = json.loads(observation_path.read_text(encoding="utf-8"))
    [market_record] = records
    assert market_record["order_type"] == "1"
    assert market_record["ts_init"] is not None
    assert market_record["ts_init"] > 0
    assert market_record["ts_accepted"] == 0
    assert market_record["selected_market_timestamp_utc"] is not None
    assert pd.Timestamp(market_record["selected_market_timestamp_utc"]) == _first_fill_timestamp(
        fills,
    )


def _write_source_parquet(
    source_root: Path,
    symbol: str,
    timeframe: str,
    start_price: float,
    *,
    gap_volatility: bool = False,
) -> None:
    source_root.mkdir(parents=True, exist_ok=True)
    if gap_volatility:
        frame = pd.DataFrame(
            {
                "open": [start_price, start_price + 0.10, start_price + 0.11, start_price + 0.12],
                "high": [
                    start_price + 0.01,
                    start_price + 0.11,
                    start_price + 0.12,
                    start_price + 0.13,
                ],
                "low": [start_price, start_price + 0.10, start_price + 0.11, start_price + 0.12],
                "close": [start_price, start_price + 0.10, start_price + 0.11, start_price + 0.12],
                "volume": [10.0, 10.0, 10.0, 10.0],
                "average": [
                    start_price + 0.005,
                    start_price + 0.105,
                    start_price + 0.115,
                    start_price + 0.125,
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
        return
    frame = pd.DataFrame(
        {
            "open": [start_price, start_price + 1, start_price + 2, start_price + 3],
            "high": [start_price + 1, start_price + 2, start_price + 3, start_price + 4],
            "low": [start_price - 1, start_price, start_price + 1, start_price + 2],
            "close": [
                start_price + 0.5,
                start_price + 1.5,
                start_price + 2.5,
                start_price + 3.5,
            ],
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


def _build_run_spec(
    *,
    execution_policy: BacktestExecutionPolicy | None,
    execution_start_utc: datetime | None = None,
) -> BacktestRunSpec:
    return BacktestRunSpec(
        run_kind=RunKind.SINGLE,
        execution_window=ExecutionWindow(
            start_utc=execution_start_utc or datetime(2024, 1, 1, tzinfo=timezone.utc),
            end_utc=datetime(2024, 1, 2, tzinfo=timezone.utc),
        ),
        dataset=DatasetSpec(
            source_system=DatasetSource.PARQUET,
            normalization_policy="nautilus_v1",
            schema_version="1",
            symbol_universe=("EURUSD",),
            timeframe="30m",
            dataset_version="2026-04-03",
        ),
        strategies=(
            PortfolioStrategySpec(
                slot_id="slot-1",
                weight_frac=1.0,
                strategy=StrategySpec(
                    strategy_id="passive-eurusd",
                    implementation_id="passive_bar",
                    policy_version="v1",
                ),
                legs=(StrategyLegSpec(symbol="EURUSD"),),
            ),
        ),
        capital_base=Money(amount=Decimal("100000"), currency="USD"),
        execution_policy=execution_policy,
    )


def _build_materializer(
    source_root: Path,
    tmp_path: Path,
) -> FilesystemParquetDatasetNormalizer:
    return FilesystemParquetDatasetNormalizer(
        cache_store=FilesystemParquetCacheStore(source_cache_root=source_root),
        normalized_root=tmp_path / "normalized",
    )


def _compile_market_order_run(
    *,
    tmp_path: Path,
    source_root: Path,
    runtime_settings: RuntimeSettings,
    execution_policy: BacktestExecutionPolicy | None,
    execution_costs_path: Path | None = None,
    execution_start_utc: datetime | None = None,
) -> NautilusRunSpec:
    compiler = CanonicalNautilusRunSpecCompiler(
        runtime_settings=runtime_settings,
        dataset_materializer=_build_materializer(source_root, tmp_path),
        catalog_builder=FilesystemNautilusCatalogBuilder(catalog_cache_root=tmp_path / "catalogs"),
        strategy_resolver=_MarketOrderStrategyResolver(),
        execution_costs_path=execution_costs_path,
    )
    return compiler.compile(
        _build_run_spec(
            execution_policy=execution_policy,
            execution_start_utc=execution_start_utc,
        ),
    )


def _write_dynamic_execution_costs_yaml(costs_path: Path) -> None:
    costs_path.write_text(
        """
schema_version: 1
profile_id: default_execution_costs
owner: integration_test
description: Dynamic spread runtime fixture.
asset_class_defaults:
  FX:
    commission_model:
      model: rate_of_notional
      commission_rate_bps: "0.20"
    spread_model:
      model: log_linear_dynamic_half_spread
      base_half_spread_price: "0.01"
      min_half_spread_price: "0.001"
      max_half_spread_price: "0.05"
      volatility_weight: "1.0"
      liquidity_weight: "0"
      session_buckets:
        - session_bucket_id: regular
          session_adjustment_log: "0"
      provenance:
        symbol: EURUSD
        venue: SIM
        timeframe: 30m
        provider_or_broker: integration-test
        sample_start_utc: "2024-01-01T00:00:00Z"
        sample_end_utc: "2024-01-02T00:00:00Z"
        row_count: 4
        data_quality_notes: fixture
        sample_role: integration_test
        estimator_method: manual
        conversion_method: already_price_units
    slippage_model:
      model: none_explicit
      reason: integration_test
dynamic_spread_runtime:
  asset_class_defaults:
    FX:
      volatility_short_window_bars: 2
      volatility_baseline_window_bars: 1
      volatility_floor_price: "0.00001"
      volatility_signal_method: true_range_atr
      volume_baseline_window_bars: 1
      volume_floor: "1"
      dynamic_order_types: [market]
      session_buckets:
        - session_bucket_id: regular
          weekdays: [0, 1, 2, 3, 4, 5, 6]
          start_time_utc: "00:00:00"
          end_time_utc: "00:00:00"
""".lstrip(),
        encoding="utf-8",
    )


def _execution_costs_hash(costs_path: Path) -> str:
    return execution_costs_config_hash(load_execution_costs(costs_path))


def _run_and_persist_fills(
    compiled: NautilusRunSpec,
    backtest_node_cls: Callable[..., _RunnableBacktestNode],
) -> pd.DataFrame:
    compiled.runtime_root.mkdir(parents=True, exist_ok=True)
    compiled.artifact_root.mkdir(parents=True, exist_ok=True)
    run_spec_path = compiled.runtime_root / "compiled_run_spec.json"
    run_spec_path.write_text(compiled.model_dump_json(indent=2), encoding="utf-8")
    config = _build_backtest_run_config(compiled)
    node = backtest_node_cls(configs=[config])
    try:
        [run_result] = node.run()
        engine = node.get_engine(config.id)
        if engine is None:
            raise AssertionError("Nautilus engine missing after smoke run")
        artifacts = NautilusReportWriter().persist(
            compiled_spec=compiled,
            run_result=run_result,
            engine=engine,
            runtime_sec=0.0,
            run_spec_path=run_spec_path,
        )
        fills_report_path = artifacts.report_locations["fills_report"]
        assert Path(fills_report_path).is_file()
        return pd.read_parquet(fills_report_path)
    finally:
        cast(_DisposableBacktestNode, node).dispose()


def _first_fill_price(fills_report: pd.DataFrame) -> Decimal:
    for column_name in ("last_px", "avg_px", "price"):
        if column_name not in fills_report.columns:
            continue
        raw_value = fills_report.iloc[0][column_name]
        return Decimal(str(raw_value).split()[0])
    raise AssertionError(f"fills report has no fill price column: {list(fills_report.columns)}")


def _first_fill_timestamp(fills_report: pd.DataFrame) -> pd.Timestamp:
    for column_name in ("ts_event", "ts_init", "ts_filled", "timestamp"):
        if column_name not in fills_report.columns:
            continue
        raw_value = fills_report.iloc[0][column_name]
        if isinstance(raw_value, int):
            return pd.Timestamp(raw_value, unit="ns", tz="UTC")
        timestamp = pd.Timestamp(raw_value)
        if timestamp.tzinfo is None:
            return timestamp.tz_localize("UTC")
        return timestamp.tz_convert("UTC")
    raise AssertionError(f"fills report has no fill timestamp column: {list(fills_report.columns)}")
