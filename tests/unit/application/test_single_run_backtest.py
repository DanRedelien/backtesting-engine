from __future__ import annotations

from decimal import Decimal
from datetime import datetime, timezone

from backtest_engine.application.single.run_single_backtest import (
    SingleRunCommand,
    SingleRunDependencies,
    run_single_backtest,
)
from backtest_engine.config.runtime import BacktestRunSpec, ExecutionWindow
from backtest_engine.core.enums import DatasetSource, RunKind
from backtest_engine.core.money import Money
from backtest_engine.domain.artifacts.bundles import ResultBundle
from backtest_engine.domain.market.datasets import DatasetSpec
from backtest_engine.domain.strategy.specifications import (
    PortfolioStrategySpec,
    StrategyLegSpec,
    StrategySpec,
)
from backtest_engine.infrastructure.artifacts.artifact_store import SavedBundle
from backtest_engine.infrastructure.nautilus.runner import NautilusRunArtifacts


def _build_single_run_spec() -> BacktestRunSpec:
    return BacktestRunSpec(
        run_kind=RunKind.SINGLE,
        execution_window=ExecutionWindow(
            start_utc=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end_utc=datetime(2024, 2, 1, tzinfo=timezone.utc),
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
                    strategy_id="sma_pullback",
                    implementation_id="sma_pullback",
                    policy_version="v1",
                ),
                legs=(StrategyLegSpec(symbol="ES"),),
            ),
        ),
        capital_base=Money(amount=Decimal("100000"), currency="USD"),
    )


class FakeClock:
    def now_utc(self) -> datetime:
        return datetime(2026, 4, 3, tzinfo=timezone.utc)


class FakeRunner:
    def __init__(self) -> None:
        self.run_specs: list[BacktestRunSpec] = []

    def run(self, run_spec: BacktestRunSpec) -> NautilusRunArtifacts:
        self.run_specs.append(run_spec)
        return NautilusRunArtifacts(
            run_id=run_spec.run_id,
            runtime_root="var/runtime/nautilus/run-1",
            report_locations={"fills": "var/runtime/nautilus/run-1/fills.csv"},
            metrics={"sharpe": 1.25},
        )


class FakeArtifactStore:
    def __init__(self) -> None:
        self.saved_bundles: list[ResultBundle] = []

    def save_bundle(self, bundle: ResultBundle) -> SavedBundle:
        self.saved_bundles.append(bundle)
        return SavedBundle(
            bundle_id=bundle.bundle_id,
            bundle_uri=f"results/{bundle.bundle_id}",
        )


def test_run_single_backtest_persists_bundle() -> None:
    runner = FakeRunner()
    store = FakeArtifactStore()
    run_spec = _build_single_run_spec()

    result = run_single_backtest(
        command=SingleRunCommand(requested_by="test"),
        run_spec=run_spec,
        dependencies=SingleRunDependencies(
            runner=runner,
            artifact_store=store,
            clock=FakeClock(),
        ),
    )

    assert result.run_id == run_spec.run_id
    assert result.bundle_uri == f"results/{result.bundle_id}"
    assert result.metric_values == {"sharpe": 1.25}
    assert runner.run_specs == [run_spec]
    assert len(store.saved_bundles) == 1
    assert store.saved_bundles[0].manifest.run_id == run_spec.run_id
    assert store.saved_bundles[0].manifest.run_spec_hash == run_spec.content_hash
    assert store.saved_bundles[0].manifest.config_hash == run_spec.content_hash
    assert store.saved_bundles[0].run_spec == run_spec
    assert store.saved_bundles[0].summary["requested_by"] == "test"
