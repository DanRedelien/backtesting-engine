from __future__ import annotations

from decimal import Decimal
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backtest_engine.config.data import DataSettings, IbDataSettings
from backtest_engine.analytics.read_models import BundleReadModel
from backtest_engine.application.batch.run_batch_backtests import BatchRunCommand
from backtest_engine.application.backtests.dry_run_backtest import BacktestDryRunCommand
from backtest_engine.application.optimization.run_walk_forward import WalkForwardCommand
from backtest_engine.application.single.run_single_backtest import SingleRunCommand
from backtest_engine.bootstrap.composition_root import (
    InfrastructurePorts,
    build_application_container,
    build_cli_container,
    build_ib_historical_ingestor,
    build_infrastructure_ports,
    build_market_data_service,
)
from backtest_engine.config.runtime import BacktestRunSpec, ExecutionWindow
from backtest_engine.config.runtime import RuntimeSettings
from backtest_engine.config.settings import PlatformSettings
from backtest_engine.core.enums import DatasetSource, RunKind
from backtest_engine.core.errors import InfrastructureError
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
from backtest_engine.infrastructure.artifacts import (
    FilesystemArtifactStore,
    FilesystemBundleLoader,
)
from backtest_engine.infrastructure.artifacts.artifact_store import SavedBundle
from backtest_engine.infrastructure.optimization.study_store import FilesystemStudyArtifactStore
from backtest_engine.infrastructure.nautilus.portfolio_projection import PortfolioProjection
from backtest_engine.infrastructure.nautilus.catalogs import CatalogItem, CatalogReference
from backtest_engine.infrastructure.nautilus.run_spec_compiler import (
    NautilusDataSpec,
    NautilusRunSpec,
    NautilusStrategySpec,
    NautilusVenueSpec,
)
from backtest_engine.infrastructure.nautilus.runner import BacktestNodeNautilusRunner
from backtest_engine.infrastructure.nautilus.runner import NautilusRunArtifacts
from backtest_engine.infrastructure.observability import InMemoryDiagnosticsSink


def _build_single_run_spec(strategy_id: str) -> BacktestRunSpec:
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
                    strategy_id=strategy_id,
                    implementation_id=strategy_id,
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
        self.run_count = 0

    def run(self, run_spec: BacktestRunSpec) -> NautilusRunArtifacts:
        self.run_count += 1
        return NautilusRunArtifacts(
            run_id=run_spec.run_id,
            runtime_root=f"var/runtime/nautilus/{run_spec.run_id}",
            metrics={},
        )


class FakeCompiler:
    def __init__(self) -> None:
        self.run_specs: list[BacktestRunSpec] = []

    def compile(self, run_spec: BacktestRunSpec) -> NautilusRunSpec:
        self.run_specs.append(run_spec)
        return _build_compiled_run_spec(run_spec)


class FailingCompiler:
    def compile(self, run_spec: BacktestRunSpec) -> NautilusRunSpec:
        raise InfrastructureError("compiler failed during dry-run", run_id=run_spec.run_id)


class FakeArtifactStore:
    def __init__(self) -> None:
        self.saved_bundles: list[ResultBundle] = []

    def save_bundle(self, bundle: ResultBundle) -> SavedBundle:
        self.saved_bundles.append(bundle)
        return SavedBundle(bundle_id=bundle.bundle_id, bundle_uri=f"results/{bundle.bundle_id}")


class FakeBundleLoader:
    def __init__(self, bundle: ResultBundle) -> None:
        self.bundle = bundle
        self.paths: list[Path] = []

    def load_bundle(self, path: Path) -> ResultBundle:
        self.paths.append(path)
        return self.bundle


class FakeProjector:
    def project(
        self,
        run_spec: BacktestRunSpec,
        artifacts: NautilusRunArtifacts,
    ) -> PortfolioProjection:
        return PortfolioProjection(run_id=run_spec.run_id)


def _build_study_store() -> FilesystemStudyArtifactStore:
    return FilesystemStudyArtifactStore(results_root=Path("results"))


def _build_bundle(run_spec: BacktestRunSpec) -> ResultBundle:
    return ResultBundle(
        manifest=ArtifactManifest(
            run_id=run_spec.run_id,
            run_spec_hash=run_spec.content_hash,
            runtime_boundary=run_spec.runtime_boundary,
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
        summary={"net_profit": 100.0},
    )


def _build_ports(
    *,
    compiler: FakeCompiler | None = None,
    runner: FakeRunner | None = None,
    store: FakeArtifactStore | None = None,
    bundle_loader: FakeBundleLoader | None = None,
    projector: FakeProjector | None = None,
) -> InfrastructurePorts:
    run_spec = _build_single_run_spec("fixture-loader")
    active_compiler = compiler or FakeCompiler()
    return InfrastructurePorts(
        run_spec_compiler=active_compiler,
        nautilus_runner=runner or FakeRunner(),
        artifact_store=store or FakeArtifactStore(),
        bundle_loader=bundle_loader or FakeBundleLoader(_build_bundle(run_spec)),
        portfolio_projector=projector or FakeProjector(),
        study_artifact_store=_build_study_store(),
    )


def _build_compiled_run_spec(run_spec: BacktestRunSpec) -> NautilusRunSpec:
    return NautilusRunSpec(
        run_id=run_spec.run_id,
        dataset_id=run_spec.dataset.dataset_id,
        runtime_root=Path("var/runtime/nautilus") / run_spec.run_id,
        artifact_root=Path("var/runtime/nautilus") / run_spec.run_id / "artifacts",
        annualization_policy="252d",
        catalog=CatalogReference(
            dataset_id=run_spec.dataset.dataset_id,
            catalog_root=Path("var/cache/nautilus_catalogs") / run_spec.dataset.dataset_id,
            items=(
                CatalogItem(
                    symbol="ES",
                    timeframe="30m",
                    instrument_id="ES.CME",
                    venue="CME",
                    quote_currency="USD",
                    bar_type="ES.CME-30-MINUTE-LAST-EXTERNAL",
                    row_count=4,
                ),
            ),
        ),
        venues=(
            NautilusVenueSpec(
                name="CME",
                base_currency="USD",
                starting_balances=("100000 USD",),
            ),
        ),
        data=(
            NautilusDataSpec(
                catalog_root=Path("var/cache/nautilus_catalogs") / run_spec.dataset.dataset_id,
                instrument_id="ES.CME",
                bar_type="ES.CME-30-MINUTE-LAST-EXTERNAL",
                start_time_utc=run_spec.execution_window.start_utc,
                end_time_utc=run_spec.execution_window.end_utc,
            ),
        ),
        strategies=(
            NautilusStrategySpec(
                strategy_id=run_spec.strategies[0].strategy.strategy_id,
                implementation_id=run_spec.strategies[0].strategy.implementation_id,
                strategy_path="tests.fixtures:Strategy",
                config_path="tests.fixtures:Config",
            ),
        ),
        strategy_ids=(run_spec.strategies[0].strategy.strategy_id,),
    )


def test_composition_root_wires_batch_to_single_use_case() -> None:
    runner = FakeRunner()
    store = FakeArtifactStore()
    bundle_loader = FakeBundleLoader(_build_bundle(_build_single_run_spec("sma_pullback")))
    container = build_application_container(
        settings=PlatformSettings(),
        ports=_build_ports(runner=runner, store=store, bundle_loader=bundle_loader),
        clock=FakeClock(),
    )

    result = container.run_batch_backtests(
        BatchRunCommand(
            requested_by="test",
            run_specs=(
                _build_single_run_spec("sma_pullback"),
                _build_single_run_spec("breakout"),
            ),
        ),
    )

    assert len(result.results) == 2
    assert result.summary.total_runs == 2
    assert runner.run_count == 2
    assert len(store.saved_bundles) == 2


def test_composition_root_wires_walk_forward_to_canonical_use_cases() -> None:
    runner = FakeRunner()
    store = FakeArtifactStore()
    bundle_loader = FakeBundleLoader(_build_bundle(_build_single_run_spec("sma_pullback")))
    container = build_application_container(
        settings=PlatformSettings(),
        ports=_build_ports(runner=runner, store=store, bundle_loader=bundle_loader),
        clock=FakeClock(),
    )

    first_spec = _build_single_run_spec("sma_pullback")
    second_spec = _build_single_run_spec("breakout")

    result = container.run_walk_forward(
        WalkForwardCommand(
            requested_by="test",
            metric_name="net_profit",
            fold_run_specs=(first_spec, second_spec),
        )
    )

    assert len(result.fold_results) == 2
    assert result.best_run_id == first_spec.run_id
    assert runner.run_count == 2
    assert len(store.saved_bundles) == 2


def test_composition_root_wires_bundle_read_models_for_delivery_surfaces() -> None:
    run_spec = _build_single_run_spec("sma_pullback")
    bundle_loader = FakeBundleLoader(_build_bundle(run_spec))
    container = build_application_container(
        settings=PlatformSettings(),
        ports=_build_ports(bundle_loader=bundle_loader),
        clock=FakeClock(),
    )

    read_model = container.load_bundle_read_model(Path("results/bundle.json"))

    assert isinstance(read_model, BundleReadModel)
    assert bundle_loader.paths == [Path("results/bundle.json")]
    assert read_model.run_id == run_spec.run_id


def test_composition_root_exposes_typed_bundle_loading_for_interfaces() -> None:
    run_spec = _build_single_run_spec("sma_pullback")
    bundle = _build_bundle(run_spec)
    bundle_loader = FakeBundleLoader(bundle)
    container = build_application_container(
        settings=PlatformSettings(),
        ports=_build_ports(bundle_loader=bundle_loader),
        clock=FakeClock(),
    )

    loaded_bundle = container.load_bundle(Path("results/bundle.json"))

    assert bundle_loader.paths == [Path("results/bundle.json")]
    assert loaded_bundle == bundle


def test_build_infrastructure_ports_assembles_filesystem_bundle_adapters(
    tmp_path: Path,
) -> None:
    ports = build_infrastructure_ports(
        settings=PlatformSettings(
            runtime=RuntimeSettings(results_root=tmp_path / "results"),
        ),
        run_spec_compiler=FakeCompiler(),
        nautilus_runner=FakeRunner(),
        portfolio_projector=FakeProjector(),
    )

    assert isinstance(ports.artifact_store, FilesystemArtifactStore)
    assert isinstance(ports.bundle_loader, FilesystemBundleLoader)
    assert isinstance(ports.study_artifact_store, FilesystemStudyArtifactStore)


def test_build_default_infrastructure_ports_reuses_one_compiler_for_runner_and_dry_run(
    tmp_path: Path,
) -> None:
    from backtest_engine.bootstrap.composition_root import build_default_infrastructure_ports

    ports = build_default_infrastructure_ports(
        PlatformSettings(
            runtime=RuntimeSettings(nautilus_root=tmp_path / "runtime" / "nautilus"),
            data=DataSettings(
                source_cache_root=tmp_path / "source-cache",
                data_root=tmp_path / "data",
                cache_root=tmp_path / "cache",
            ),
        )
    )

    assert isinstance(ports.nautilus_runner, BacktestNodeNautilusRunner)
    assert ports.nautilus_runner.compiler is ports.run_spec_compiler


def test_build_default_infrastructure_ports_passes_custom_execution_costs_path(
    tmp_path: Path,
) -> None:
    from backtest_engine.bootstrap.composition_root import build_default_infrastructure_ports
    from backtest_engine.infrastructure.nautilus.run_spec_compiler import (
        CanonicalNautilusRunSpecCompiler,
    )

    costs_path = tmp_path / "generated_execution_costs.yaml"
    ports = build_default_infrastructure_ports(
        PlatformSettings(
            runtime=RuntimeSettings(nautilus_root=tmp_path / "runtime" / "nautilus"),
            data=DataSettings(
                source_cache_root=tmp_path / "source-cache",
                data_root=tmp_path / "data",
                cache_root=tmp_path / "cache",
            ),
        ),
        execution_costs_path=costs_path,
    )

    assert isinstance(ports.run_spec_compiler, CanonicalNautilusRunSpecCompiler)
    assert ports.run_spec_compiler.execution_costs_path == costs_path


def test_composition_root_wires_dry_run_to_compiler() -> None:
    compiler = FakeCompiler()
    run_spec = _build_single_run_spec("fixture-dry-run")
    container = build_application_container(
        settings=PlatformSettings(),
        ports=_build_ports(compiler=compiler),
        clock=FakeClock(),
    )

    result = container.dry_run_backtest(
        BacktestDryRunCommand(requested_by="test", correlation_id="dry-run-correlation"),
        run_spec=run_spec,
    )

    assert compiler.run_specs == [run_spec]
    assert result.run_id == run_spec.run_id
    assert result.dataset_id == run_spec.dataset.dataset_id
    assert result.data_count == 1


def test_composition_root_emits_failed_diagnostics_for_dry_run_compiler_failure() -> None:
    diagnostics = InMemoryDiagnosticsSink()
    run_spec = _build_single_run_spec("fixture-dry-run")
    container = build_application_container(
        settings=PlatformSettings(),
        ports=InfrastructurePorts(
            run_spec_compiler=FailingCompiler(),
            nautilus_runner=FakeRunner(),
            artifact_store=FakeArtifactStore(),
            bundle_loader=FakeBundleLoader(_build_bundle(run_spec)),
            portfolio_projector=FakeProjector(),
            study_artifact_store=_build_study_store(),
        ),
        clock=FakeClock(),
        diagnostics=diagnostics,
    )

    with pytest.raises(InfrastructureError):
        container.dry_run_backtest(
            BacktestDryRunCommand(requested_by="test", correlation_id="dry-run-correlation"),
            run_spec=run_spec,
        )

    stages = [(event.stage, event.status) for event in diagnostics.events]
    assert ("backtest.dry_run", "started") in stages
    assert ("backtest.dry_run", "failed") in stages
    failed_event = diagnostics.events[-1]
    assert failed_event.details["error_type"] == "InfrastructureError"


def test_build_cli_container_assembles_default_application_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_spec = _build_single_run_spec("sma_pullback")
    bundle_loader = FakeBundleLoader(_build_bundle(run_spec))
    ports = _build_ports(bundle_loader=bundle_loader)
    settings = PlatformSettings()
    captured: dict[str, object] = {}

    def fake_build_default_infrastructure_ports(
        resolved_settings: PlatformSettings,
        *,
        execution_costs_path: Path | None = None,
    ) -> InfrastructurePorts:
        captured["settings"] = resolved_settings
        captured["execution_costs_path"] = execution_costs_path
        return ports

    monkeypatch.setattr(
        "backtest_engine.bootstrap.composition_root.build_default_infrastructure_ports",
        fake_build_default_infrastructure_ports,
    )

    costs_path = Path("var/runtime/calibration/generated/execution_costs.yaml")
    container = build_cli_container(
        settings=settings,
        clock=FakeClock(),
        execution_costs_path=costs_path,
    )

    assert container.settings is settings
    assert container.bundle_loader is bundle_loader
    assert captured["settings"] is settings
    assert captured["execution_costs_path"] == costs_path


def test_build_ib_historical_ingestor_assembles_v2_ib_adapters(tmp_path: Path) -> None:
    ingestor = build_ib_historical_ingestor(
        PlatformSettings(
            data=DataSettings(
                source_cache_root=tmp_path / "source-cache",
                ib=IbDataSettings(
                    host="127.0.0.1",
                    port=4002,
                    client_id=17,
                    timeout_sec=45,
                ),
            )
        )
    )

    assert ingestor.client.settings.port == 4002
    assert ingestor.client.settings.client_id == 17
    assert ingestor.cache_store.source_cache_root == tmp_path / "source-cache"


def test_composition_root_can_persist_and_reload_bundle_with_filesystem_adapters(
    tmp_path: Path,
) -> None:
    run_spec = _build_single_run_spec("sma_pullback")
    settings = PlatformSettings(runtime=RuntimeSettings(results_root=tmp_path / "results"))
    container = build_application_container(
        settings=settings,
        ports=build_infrastructure_ports(
            settings=settings,
            run_spec_compiler=FakeCompiler(),
            nautilus_runner=FakeRunner(),
            portfolio_projector=FakeProjector(),
        ),
        clock=FakeClock(),
    )

    result = container.run_single_backtest(
        SingleRunCommand(requested_by="test"),
        run_spec=run_spec,
    )
    read_model = container.load_bundle_read_model(Path(result.bundle_uri))

    assert Path(result.bundle_uri).is_file()
    assert read_model.bundle_id == result.bundle_id
    assert read_model.run_id == run_spec.run_id


def test_composition_root_emits_stage_diagnostics_for_walk_forward_runs() -> None:
    diagnostics = InMemoryDiagnosticsSink()
    runner = FakeRunner()
    store = FakeArtifactStore()
    bundle_loader = FakeBundleLoader(_build_bundle(_build_single_run_spec("sma_pullback")))
    container = build_application_container(
        settings=PlatformSettings(),
        ports=_build_ports(runner=runner, store=store, bundle_loader=bundle_loader),
        clock=FakeClock(),
        diagnostics=diagnostics,
    )

    container.run_walk_forward(
        WalkForwardCommand(
            requested_by="test",
            correlation_id="wf-correlation",
            metric_name="net_profit",
            fold_run_specs=(
                _build_single_run_spec("sma_pullback"),
                _build_single_run_spec("breakout"),
            ),
        )
    )

    stages = [(event.stage, event.status) for event in diagnostics.events]
    assert ("walk_forward.run", "started") in stages
    assert ("optimization.execute_many", "started") in stages
    assert ("optimization.fold.execute", "succeeded") in stages
    assert ("single.run", "succeeded") in stages


def test_build_market_data_service_wires_providers_verifier_and_store(tmp_path: Path) -> None:
    from backtest_engine.application.market_data import HistoricalMarketDataService
    from backtest_engine.infrastructure.data import (
        FilesystemHistoricalDataStore,
        IbHistoricalDataProvider,
        MarketDataValidator,
        Mt5HistoricalDataProvider,
    )

    diagnostics = InMemoryDiagnosticsSink()
    service = build_market_data_service(
        PlatformSettings(
            data=DataSettings(source_cache_root=tmp_path / "source-cache"),
        ),
        diagnostics=diagnostics,
    )

    assert isinstance(service, HistoricalMarketDataService)
    assert isinstance(service.store, FilesystemHistoricalDataStore)
    assert service.store.source_cache_root == tmp_path / "source-cache"
    assert set(service.providers.keys()) == {"ib", "mt5"}
    assert isinstance(service.providers["ib"], IbHistoricalDataProvider)
    assert isinstance(service.providers["mt5"], Mt5HistoricalDataProvider)
    assert isinstance(service.verifier, MarketDataValidator)
    assert service.providers["ib"].store is service.store
    assert service.providers["mt5"].store is service.store
    assert service.verifier.store is service.store
    assert service.diagnostics is diagnostics
