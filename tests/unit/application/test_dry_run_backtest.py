from __future__ import annotations

from decimal import Decimal
from datetime import datetime, timezone
from pathlib import Path

from backtest_engine.application.backtests.dry_run_backtest import (
    BacktestDryRunCommand,
    BacktestDryRunDependencies,
    dry_run_backtest,
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
from backtest_engine.infrastructure.nautilus.catalogs import CatalogItem, CatalogReference
from backtest_engine.infrastructure.nautilus.run_spec_compiler import (
    NautilusDataSpec,
    NautilusRunSpec,
    NautilusStrategySpec,
    NautilusVenueSpec,
)


def test_dry_run_backtest_maps_compiled_run_spec_to_result() -> None:
    run_spec = _build_portfolio_run_spec()
    compiler = FakeDryRunCompiler()

    result = dry_run_backtest(
        command=BacktestDryRunCommand(requested_by="unit-test"),
        run_spec=run_spec,
        dependencies=BacktestDryRunDependencies(compiler=compiler),
    )

    assert compiler.run_specs == [run_spec]
    assert result.run_id == run_spec.run_id
    assert result.run_kind is RunKind.PORTFOLIO
    assert result.dataset_id == run_spec.dataset.dataset_id
    assert result.runtime_root == f"var/runtime/nautilus/{run_spec.run_id}"
    assert result.artifact_root == f"var/runtime/nautilus/{run_spec.run_id}/artifacts"
    assert result.catalog_root == f"var/cache/nautilus_catalogs/{run_spec.dataset.dataset_id}"
    assert result.venue_names == ("CME", "SIM")
    assert result.data_count == 2
    assert result.instrument_ids == ("AAA.SIM", "ZZZ.SIM")
    assert result.bar_types == (
        "AAA.SIM-30-MINUTE-LAST-EXTERNAL",
        "ZZZ.SIM-30-MINUTE-LAST-EXTERNAL",
    )
    assert result.strategy_ids == ("fixture_strategy_b", "fixture_strategy_a")


class FakeDryRunCompiler:
    def __init__(self) -> None:
        self.run_specs: list[BacktestRunSpec] = []

    def compile(self, run_spec: BacktestRunSpec) -> NautilusRunSpec:
        self.run_specs.append(run_spec)
        catalog_root = Path("var/cache/nautilus_catalogs") / run_spec.dataset.dataset_id
        return NautilusRunSpec(
            run_id=run_spec.run_id,
            dataset_id=run_spec.dataset.dataset_id,
            runtime_root=Path("var/runtime/nautilus") / run_spec.run_id,
            artifact_root=Path("var/runtime/nautilus") / run_spec.run_id / "artifacts",
            annualization_policy="252d",
            catalog=CatalogReference(
                dataset_id=run_spec.dataset.dataset_id,
                catalog_root=catalog_root,
                items=(
                    CatalogItem(
                        symbol="ZZZ",
                        timeframe="30m",
                        instrument_id="ZZZ.SIM",
                        venue="SIM",
                        quote_currency="USD",
                        bar_type="ZZZ.SIM-30-MINUTE-LAST-EXTERNAL",
                        row_count=4,
                    ),
                    CatalogItem(
                        symbol="AAA",
                        timeframe="30m",
                        instrument_id="AAA.SIM",
                        venue="CME",
                        quote_currency="USD",
                        bar_type="AAA.SIM-30-MINUTE-LAST-EXTERNAL",
                        row_count=4,
                    ),
                ),
            ),
            venues=(
                NautilusVenueSpec(
                    name="SIM",
                    base_currency="USD",
                    starting_balances=("100000 USD",),
                ),
                NautilusVenueSpec(
                    name="CME",
                    base_currency="USD",
                    starting_balances=("100000 USD",),
                ),
            ),
            data=(
                NautilusDataSpec(
                    catalog_root=catalog_root,
                    instrument_id="ZZZ.SIM",
                    bar_type="ZZZ.SIM-30-MINUTE-LAST-EXTERNAL",
                    start_time_utc=run_spec.execution_window.start_utc,
                    end_time_utc=run_spec.execution_window.end_utc,
                ),
                NautilusDataSpec(
                    catalog_root=catalog_root,
                    instrument_id="AAA.SIM",
                    bar_type="AAA.SIM-30-MINUTE-LAST-EXTERNAL",
                    start_time_utc=run_spec.execution_window.start_utc,
                    end_time_utc=run_spec.execution_window.end_utc,
                ),
            ),
            strategies=(
                NautilusStrategySpec(
                    strategy_id="fixture_strategy_b",
                    implementation_id="fixture_strategy_b",
                    strategy_path="tests.fixtures:StrategyB",
                    config_path="tests.fixtures:ConfigB",
                ),
                NautilusStrategySpec(
                    strategy_id="fixture_strategy_a",
                    implementation_id="fixture_strategy_a",
                    strategy_path="tests.fixtures:StrategyA",
                    config_path="tests.fixtures:ConfigA",
                ),
            ),
            strategy_ids=("fixture_strategy_b", "fixture_strategy_a"),
        )


def _build_portfolio_run_spec() -> BacktestRunSpec:
    return BacktestRunSpec(
        run_kind=RunKind.PORTFOLIO,
        execution_window=ExecutionWindow(
            start_utc=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end_utc=datetime(2024, 2, 1, tzinfo=timezone.utc),
        ),
        dataset=DatasetSpec(
            source_system=DatasetSource.PARQUET,
            normalization_policy="nautilus_v1",
            schema_version="1",
            symbol_universe=("ZZZ", "AAA"),
            timeframe="30m",
            dataset_version="2026-04-19",
        ),
        strategies=(
            PortfolioStrategySpec(
                slot_id="slot-b",
                weight_frac=0.5,
                strategy=StrategySpec(
                    strategy_id="fixture_strategy_b",
                    implementation_id="fixture_strategy_b",
                    policy_version="v1",
                ),
                legs=(StrategyLegSpec(symbol="ZZZ"),),
            ),
            PortfolioStrategySpec(
                slot_id="slot-a",
                weight_frac=0.5,
                strategy=StrategySpec(
                    strategy_id="fixture_strategy_a",
                    implementation_id="fixture_strategy_a",
                    policy_version="v1",
                ),
                legs=(StrategyLegSpec(symbol="AAA"),),
            ),
        ),
        capital_base=Money(amount=Decimal("100000"), currency="USD"),
    )
