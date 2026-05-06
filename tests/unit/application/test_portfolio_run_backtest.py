from __future__ import annotations

from decimal import Decimal
from datetime import datetime, timezone

from backtest_engine.application.portfolio.run_portfolio_backtest import (
    PortfolioRunCommand,
    PortfolioRunDependencies,
    run_portfolio_backtest,
)
from backtest_engine.application.portfolio.build_portfolio_plan import build_portfolio_plan
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
from backtest_engine.infrastructure.nautilus.portfolio_projection import PortfolioProjection
from backtest_engine.infrastructure.nautilus.runner import NautilusRunArtifacts


def _build_portfolio_run_spec() -> BacktestRunSpec:
    strategies = (
        PortfolioStrategySpec(
            slot_id="slot-1",
            weight_frac=0.6,
            strategy=StrategySpec(
                strategy_id="sma_pullback",
                implementation_id="sma_pullback",
                policy_version="v1",
            ),
            legs=(StrategyLegSpec(symbol="ES"), StrategyLegSpec(symbol="NQ")),
        ),
        PortfolioStrategySpec(
            slot_id="slot-2",
            weight_frac=0.4,
            strategy=StrategySpec(
                strategy_id="breakout",
                implementation_id="breakout",
                policy_version="v1",
            ),
            legs=(StrategyLegSpec(symbol="NQ"),),
        ),
    )
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
            symbol_universe=("ES", "NQ"),
            timeframe="30m",
            dataset_version="2026-04-03",
        ),
        strategies=strategies,
        capital_base=Money(amount=Decimal("250000"), currency="USD"),
    )


class FakeClock:
    def now_utc(self) -> datetime:
        return datetime(2026, 4, 3, tzinfo=timezone.utc)


class FakeRunner:
    def run(self, run_spec: BacktestRunSpec) -> NautilusRunArtifacts:
        return NautilusRunArtifacts(
            run_id=run_spec.run_id,
            runtime_root="var/runtime/nautilus/portfolio-1",
            report_locations={"fills": "var/runtime/nautilus/portfolio-1/fills.csv"},
            metrics={"net_profit": 2500.0},
        )


class FakeProjector:
    def project(
        self,
        run_spec: BacktestRunSpec,
        artifacts: NautilusRunArtifacts,
    ) -> PortfolioProjection:
        return PortfolioProjection(
            run_id=run_spec.run_id,
            position_count=3,
            summary={"max_drawdown_pct": 8.5},
            artifact_locations={"portfolio_projection": "var/runtime/nautilus/portfolio-1/portfolio_projection.json"},
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


def test_run_portfolio_backtest_builds_plan_and_bundle() -> None:
    run_spec = _build_portfolio_run_spec()
    store = FakeArtifactStore()

    result = run_portfolio_backtest(
        command=PortfolioRunCommand(requested_by="test"),
        run_spec=run_spec,
        dependencies=PortfolioRunDependencies(
            runner=FakeRunner(),
            projector=FakeProjector(),
            artifact_store=store,
            clock=FakeClock(),
        ),
    )

    assert result.run_id == run_spec.run_id
    assert result.allocation_count == 2
    assert result.position_count == 3
    assert run_spec.portfolio_policy is not None
    assert result.metric_values == {
        "position_count": 3.0,
        "portfolio_scalar": 1.0,
        "effective_weight_sum": 1.0,
        "net_profit": 2500.0,
        "max_drawdown_pct": 8.5,
    }
    plan = build_portfolio_plan(run_spec.strategies, run_spec.portfolio_policy)
    assert len(plan.allocation_plan.targets) == 2
    assert plan.allocation_plan.targets[0].slot_id == "slot-1"
    assert plan.allocation_plan.targets[0].leg_symbols == ("ES", "NQ")
    assert store.saved_bundles[0].manifest.run_spec_hash == run_spec.content_hash
    assert store.saved_bundles[0].manifest.config_hash == run_spec.content_hash
    assert store.saved_bundles[0].run_spec == run_spec
    assert store.saved_bundles[0].summary["position_count"] == 3
    assert store.saved_bundles[0].summary["requested_by"] == "test"
    assert (
        store.saved_bundles[0].artifact_locations["portfolio_projection"]
        == "var/runtime/nautilus/portfolio-1/portfolio_projection.json"
    )
