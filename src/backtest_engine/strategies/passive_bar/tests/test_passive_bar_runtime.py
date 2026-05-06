# mypy: disable-error-code=no-untyped-def
from __future__ import annotations

from decimal import Decimal
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from backtest_engine.application.single.run_single_backtest import SingleRunCommand
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
        return datetime(2026, 4, 3, tzinfo=timezone.utc)


def test_passive_bar_runtime_runs_end_to_end_through_v2_stack(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    frame = pd.DataFrame(
        {
            "open": [100.0, 101.0, 102.0, 103.0],
            "high": [101.0, 102.0, 103.0, 104.0],
            "low": [99.0, 100.0, 101.0, 102.0],
            "close": [100.5, 101.5, 102.5, 103.5],
            "volume": [10.0, 10.0, 10.0, 10.0],
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
    frame.to_parquet(source_root / "ES_30m.parquet")

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
        run_kind=RunKind.SINGLE,
        execution_window=ExecutionWindow(
            start_utc=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end_utc=datetime(2024, 1, 2, tzinfo=timezone.utc),
        ),
        dataset=DatasetSpec(
            source_system=DatasetSource.PARQUET,
            normalization_policy="nautilus_v1",
            schema_version="1",
            symbol_universe=("ES",),
            timeframe="30m",
            dataset_version="2026-04-03",
        ),
        strategies=(
            PortfolioStrategySpec(
                slot_id="slot-1",
                weight_frac=1.0,
                strategy=StrategySpec(
                    strategy_id="passive-es",
                    implementation_id="passive_bar",
                    policy_version="v1",
                ),
                legs=(StrategyLegSpec(symbol="ES"),),
            ),
        ),
        capital_base=Money(amount=Decimal("100000"), currency="USD"),
    )
    container = build_application_container(
        settings=settings,
        ports=build_default_infrastructure_ports(settings),
        clock=FixedClock(),
    )

    result = container.run_single_backtest(
        command=SingleRunCommand(requested_by="integration"),
        run_spec=run_spec,
    )
    read_model = container.load_bundle_read_model(Path(result.bundle_uri))

    assert Path(result.bundle_uri).is_file()
    assert read_model.run_id == run_spec.run_id
    assert result.metric_values["total_orders"] == 0.0
    assert (tmp_path / "runtime" / "nautilus" / run_spec.run_id / "compiled_run_spec.json").is_file()
    assert (
        tmp_path / "runtime" / "nautilus" / run_spec.run_id / "artifacts" / "summary.json"
    ).is_file()
