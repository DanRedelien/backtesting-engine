from __future__ import annotations

from decimal import Decimal
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backtest_engine.analytics.read_models import BundleReadModel, build_bundle_read_model
from backtest_engine.config.runtime import BacktestRunSpec, ExecutionWindow
from backtest_engine.core.enums import DatasetSource, RunKind, RuntimeBoundary
from backtest_engine.core.errors import ApplicationError
from backtest_engine.core.money import Money
from backtest_engine.domain.artifacts.bundles import ResultBundle
from backtest_engine.domain.artifacts.manifests import ArtifactManifest
from backtest_engine.domain.artifacts.provenance import ProvenanceRecord
from backtest_engine.domain.market.datasets import DatasetSpec
from backtest_engine.domain.strategy.specifications import (
    PortfolioStrategySpec,
    StrategyLegSpec,
    StrategySpec,
)
from backtest_engine.interfaces.terminal_ui.prepare_scenario_rerun import (
    ScenarioRerunRequest,
    prepare_scenario_rerun,
)
from backtest_engine.interfaces.terminal_ui.read_bundle_view import (
    BundleViewRequest,
    read_bundle_view,
)


def _build_run_spec(run_kind: RunKind) -> BacktestRunSpec:
    return BacktestRunSpec(
        run_kind=run_kind,
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


def _build_bundle(run_kind: RunKind) -> ResultBundle:
    run_spec = _build_run_spec(run_kind)
    return ResultBundle(
        manifest=ArtifactManifest(
            run_id=run_spec.run_id,
            run_spec_hash=run_spec.content_hash,
            runtime_boundary=RuntimeBoundary.NAUTILUS,
            dataset_id=run_spec.dataset.dataset_id,
            config_hash=run_spec.content_hash,
            symbol_universe=run_spec.dataset.symbol_universe,
            strategy_ids=tuple(spec.strategy.strategy_id for spec in run_spec.strategies),
            capital_base=run_spec.capital_base,
            semantic_policy_version=run_spec.semantic_policy_version,
        ),
        provenance=ProvenanceRecord(
            run_id=run_spec.run_id,
            run_spec_hash=run_spec.content_hash,
            dataset_id=run_spec.dataset.dataset_id,
            created_at_utc=datetime(2026, 4, 3, tzinfo=timezone.utc),
        ),
        run_spec=run_spec,
        artifact_locations={"runtime_root": f"var/runtime/nautilus/{run_spec.run_id}"},
        summary={"net_profit": 125.0},
    )


class FakeTerminalUIService:
    def __init__(self, bundle: ResultBundle) -> None:
        self.bundle = bundle
        self.bundle_paths: list[Path] = []
        self.read_model_paths: list[Path] = []

    def load_bundle(self, bundle_path: Path) -> ResultBundle:
        self.bundle_paths.append(bundle_path)
        return self.bundle

    def load_bundle_read_model(self, bundle_path: Path) -> BundleReadModel:
        self.read_model_paths.append(bundle_path)
        return build_bundle_read_model(self.bundle)


def test_read_bundle_view_marks_portfolio_bundles_as_rerunnable() -> None:
    bundle = _build_bundle(RunKind.PORTFOLIO)
    service = FakeTerminalUIService(bundle)
    command = BundleViewRequest(bundle_path=Path("results/portfolio-bundle"))

    result = read_bundle_view(command=command, service=service)

    assert service.bundle_paths == [command.bundle_path]
    assert service.read_model_paths == [command.bundle_path]
    assert result.summary.run_kind is RunKind.PORTFOLIO
    assert result.can_run_scenario is True
    assert result.scenario_block_reason == ""


def test_read_bundle_view_blocks_single_bundles_from_scenario_reruns() -> None:
    bundle = _build_bundle(RunKind.SINGLE)
    service = FakeTerminalUIService(bundle)

    result = read_bundle_view(
        command=BundleViewRequest(bundle_path=Path("results/single-bundle")),
        service=service,
    )

    assert result.summary.run_kind is RunKind.SINGLE
    assert result.can_run_scenario is False
    assert result.scenario_block_reason == "Scenario reruns are only available for portfolio bundles."


def test_prepare_scenario_rerun_builds_the_canonical_worker_request() -> None:
    bundle = _build_bundle(RunKind.PORTFOLIO)
    service = FakeTerminalUIService(bundle)
    command = ScenarioRerunRequest(
        bundle_path=Path("results/portfolio-bundle"),
        scenario_name="stress-drawdown",
        requested_by="terminal-ui-test",
    )

    result = prepare_scenario_rerun(command=command, service=service)

    assert service.bundle_paths == [command.bundle_path]
    assert result.source_bundle_id == bundle.bundle_id
    assert result.source_run_id == bundle.run_spec.run_id
    assert result.job_command.scenario_name == "stress-drawdown"
    assert result.job_command.requested_by == "terminal-ui-test"
    assert result.job_command.base_run_spec == bundle.run_spec


def test_prepare_scenario_rerun_rejects_non_portfolio_bundles() -> None:
    bundle = _build_bundle(RunKind.SINGLE)
    service = FakeTerminalUIService(bundle)

    with pytest.raises(ApplicationError, match="portfolio bundles"):
        prepare_scenario_rerun(
            command=ScenarioRerunRequest(
                bundle_path=Path("results/single-bundle"),
                scenario_name="stress-drawdown",
            ),
            service=service,
        )
