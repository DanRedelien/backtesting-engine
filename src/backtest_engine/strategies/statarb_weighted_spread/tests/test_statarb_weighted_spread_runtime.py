# mypy: disable-error-code=no-untyped-def
from __future__ import annotations

from decimal import Decimal
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from backtest_engine.application.portfolio.run_portfolio_backtest import PortfolioRunCommand
from backtest_engine.bootstrap import (
    build_application_container,
    build_default_infrastructure_ports,
)
from backtest_engine.config.data import DataSettings
from backtest_engine.config.runtime import BacktestRunSpec, ExecutionWindow, RuntimeSettings
from backtest_engine.config.settings import PlatformSettings
from backtest_engine.core.enums import DatasetSource, RunKind
from backtest_engine.core.money import Money
from backtest_engine.domain.market.datasets import DatasetSpec
from backtest_engine.domain.strategy.specifications import (
    PortfolioStrategySpec,
    StrategyLegSpec,
    StrategySpec,
)


class FixedClock:
    def now_utc(self) -> datetime:
        return datetime(2026, 4, 8, tzinfo=timezone.utc)


def _write_pair_sample(path: Path, *, start_price: float, deviations: list[float]) -> None:
    index = pd.date_range("2025-01-01 00:00:00", periods=len(deviations), freq="30min", tz="UTC")
    close = pd.Series(
        [start_price + deviation for deviation in deviations],
        index=index,
        dtype=float,
    )
    open_price = close.shift(1).fillna(close.iloc[0] - 1.0)
    high = pd.concat([open_price, close], axis=1).max(axis=1) + 1.0
    low = pd.concat([open_price, close], axis=1).min(axis=1) - 1.0
    frame = pd.DataFrame(
        {
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "volume": 1000.0,
            "average": (open_price + high + low + close) / 4.0,
            "barCount": 10,
        },
        index=index,
    )
    frame.to_parquet(path)


def test_statarb_weighted_spread_runs_end_to_end_through_portfolio_stack(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    es_path = source_root / "ES_30m.parquet"
    nq_path = source_root / "NQ_30m.parquet"

    common = [index * 0.5 for index in range(120)]
    divergence = [0.0] * 30 + [index * 1.2 for index in range(30)] + [36.0 - index * 1.4 for index in range(60)]
    es_deviations = [base + (spread * 0.2) for base, spread in zip(common, divergence)]
    nq_deviations = [base + spread for base, spread in zip(common, divergence)]
    _write_pair_sample(es_path, start_price=5000.0, deviations=es_deviations)
    _write_pair_sample(nq_path, start_price=17500.0, deviations=nq_deviations)

    settings = PlatformSettings(
        runtime=RuntimeSettings(
            runtime_root=tmp_path / "runtime",
            nautilus_root=tmp_path / "runtime" / "nautilus",
            results_root=tmp_path / "results",
        ),
        data=DataSettings(
            source_cache_root=source_root,
            data_root=tmp_path / "data",
            cache_root=tmp_path / "cache",
        ),
    )
    run_spec = BacktestRunSpec(
        run_kind=RunKind.PORTFOLIO,
        execution_window=ExecutionWindow(
            start_utc=datetime(2025, 1, 1, tzinfo=timezone.utc),
            end_utc=datetime(2025, 1, 4, tzinfo=timezone.utc),
        ),
        dataset=DatasetSpec(
            source_system=DatasetSource.PARQUET,
            normalization_policy="nautilus_v1",
            schema_version="1",
            symbol_universe=("ES", "NQ"),
            timeframe="30m",
            dataset_version="2026-04-08",
        ),
        strategies=(
            PortfolioStrategySpec(
                slot_id="slot-statarb-es-nq",
                weight_frac=1.0,
                strategy=StrategySpec(
                    strategy_id="statarb-es-nq",
                    implementation_id="statarb_weighted_spread",
                    policy_version="v1",
                    parameters={
                        "trade_sizes": [1.0, 1.0],
                        "spread_weights": [1.0, -1.0],
                        "zscore_window": 20,
                        "entry_zscore": 1.0,
                        "exit_zscore": 0.2,
                        "trade_direction": "both",
                    },
                ),
                legs=(StrategyLegSpec(symbol="ES"), StrategyLegSpec(symbol="NQ")),
            ),
        ),
        capital_base=Money(amount=Decimal("100000"), currency="USD"),
    )
    container = build_application_container(
        settings=settings,
        ports=build_default_infrastructure_ports(settings),
        clock=FixedClock(),
    )

    result = container.run_portfolio_backtest(
        command=PortfolioRunCommand(requested_by="integration"),
        run_spec=run_spec,
    )
    read_model = container.load_bundle_read_model(Path(result.bundle_uri))
    compiled_run_spec_path = (
        tmp_path / "runtime" / "nautilus" / run_spec.run_id / "compiled_run_spec.json"
    )
    fills_report_path = (
        tmp_path / "runtime" / "nautilus" / run_spec.run_id / "artifacts" / "fills_report.csv"
    )

    assert Path(result.bundle_uri).is_file()
    assert read_model.run_id == run_spec.run_id
    assert compiled_run_spec_path.is_file()
    assert fills_report_path.is_file()

    compiled = json.loads(compiled_run_spec_path.read_text(encoding="utf-8"))
    [compiled_strategy] = compiled["strategies"]
    assert compiled_strategy["implementation_id"] == "statarb_weighted_spread"
    assert compiled_strategy["config"]["leg_symbols"] == ["ES", "NQ"]
    assert compiled_strategy["config"]["instrument_ids"] == ["ES.CME", "NQ.CME"]
    assert compiled_strategy["config"]["bar_types"] == [
        "ES.CME-30-MINUTE-LAST-EXTERNAL",
        "NQ.CME-30-MINUTE-LAST-EXTERNAL",
    ]

    fills_report = pd.read_csv(fills_report_path)
    assert not fills_report.empty
    assert set(fills_report["instrument_id"]) == {"ES.CME", "NQ.CME"}
    assert {"BUY", "SELL"}.issubset(set(fills_report["side"]))
