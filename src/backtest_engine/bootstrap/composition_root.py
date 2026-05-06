"""Explicit dependency assembly for the rewrite."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from backtest_engine.analytics.read_models import (
    BundleDashboardReadModel,
    BundleReadModel,
    load_bundle_dashboard_read_model,
    load_bundle_read_model,
)
from backtest_engine.application.baselines.capture_baseline import (
    BaselineCaptureCommand,
    BaselineCaptureResult,
    capture_baseline,
)
from backtest_engine.application.batch.run_batch_backtests import (
    BatchRunCommand,
    BatchRunResult,
    run_batch_backtests,
)
from backtest_engine.application.backtests.dry_run_backtest import (
    BacktestDryRunCommand,
    BacktestDryRunDependencies,
    BacktestDryRunResult,
    dry_run_backtest,
)
from backtest_engine.bootstrap._execution_adapters import _PortfolioExecutor, _SingleExecutor
from backtest_engine.bootstrap._stage_events import emit_stage as _emit_stage
from backtest_engine.bootstrap._stage_events import run_details
from backtest_engine.application.optimization.run_walk_forward import (
    WalkForwardCommand,
    WalkForwardResult,
    run_walk_forward,
)
from backtest_engine.application.optimization.portfolio_weight_study import (
    PortfolioWeightStudyCommand,
    PortfolioWeightStudyDependencies,
    PortfolioWeightStudyRunResult,
    StudyArtifactStore,
    run_portfolio_weight_study,
)
from backtest_engine.application.optimization.run_walk_forward_batch import (
    WalkForwardBatchCommand,
    WalkForwardBatchResult,
    run_walk_forward_batch,
)
from backtest_engine.application.optimization.trial_executor import CanonicalTrialExecutor
from backtest_engine.application.optimization.trial_runtime import CanonicalTrialRuntime
from backtest_engine.application.portfolio.run_portfolio_backtest import (
    PortfolioRunCommand,
    PortfolioRunDependencies,
    PortfolioRunResult,
)
from backtest_engine.application.scenarios.run_scenario import (
    ScenarioRunCommand,
    run_scenario,
)
from backtest_engine.application.single.run_single_backtest import (
    SingleRunCommand,
    SingleRunDependencies,
    SingleRunResult,
)
from backtest_engine.config.runtime import BacktestRunSpec
from backtest_engine.config.settings import PlatformSettings, load_settings
from backtest_engine.core.protocols import Clock
from backtest_engine.infrastructure.artifacts.bundle_loader import BundleLoader
from backtest_engine.infrastructure.artifacts.artifact_store import ArtifactStore
from backtest_engine.domain.artifacts.bundles import ResultBundle
from backtest_engine.infrastructure.artifacts.filesystem_artifact_store import (
    FilesystemArtifactStore,
)
from backtest_engine.infrastructure.artifacts.filesystem_bundle_loader import (
    FilesystemBundleLoader,
)
from backtest_engine.infrastructure.data import (
    FilesystemHistoricalDataStore,
    FilesystemIbCacheStore,
    FilesystemParquetCacheStore,
    FilesystemParquetDatasetNormalizer,
    IbContractResolver,
    IbHistoricalCacheIngestor,
    IbHistoricalClient,
    MARKET_DATA_VALIDATOR_RULESET_VERSION,
)
from backtest_engine.infrastructure.nautilus import (
    BacktestNodeNautilusRunner,
    CanonicalNautilusRunSpecCompiler,
    FilesystemNautilusCatalogBuilder,
    FilesystemPortfolioProjector,
    NautilusReportWriter,
    NautilusRunSpecCompiler,
    PortfolioProjector,
    build_default_nautilus_strategy_resolver,
)
from backtest_engine.infrastructure.nautilus.runner import NautilusRunner
from backtest_engine.infrastructure.observability import (
    DiagnosticsSink,
    NullDiagnosticsSink,
    build_default_diagnostics_logger,
)
from backtest_engine.infrastructure.optimization.study_store import FilesystemStudyArtifactStore

if TYPE_CHECKING:
    from backtest_engine.application.market_data import HistoricalMarketDataService


class SystemClock:
    """Production clock assembled at the edge."""

    def now_utc(self) -> datetime:
        return datetime.now(timezone.utc)


@dataclass(frozen=True)
class InfrastructurePorts:
    """Concrete infrastructure ports assembled by bootstrap."""

    run_spec_compiler: NautilusRunSpecCompiler
    nautilus_runner: NautilusRunner
    artifact_store: ArtifactStore
    bundle_loader: BundleLoader
    portfolio_projector: PortfolioProjector
    study_artifact_store: StudyArtifactStore


@dataclass(frozen=True)
class ApplicationContainer:
    """Ready-to-call use-cases assembled from explicit dependencies."""

    settings: PlatformSettings
    single_dependencies: SingleRunDependencies
    portfolio_dependencies: PortfolioRunDependencies
    dry_run_dependencies: BacktestDryRunDependencies
    bundle_loader: BundleLoader
    study_dependencies: PortfolioWeightStudyDependencies
    diagnostics: DiagnosticsSink = NullDiagnosticsSink()

    def run_single_backtest(
        self,
        command: SingleRunCommand,
        run_spec: BacktestRunSpec,
    ) -> SingleRunResult:
        return self._single_executor().run(command=command, run_spec=run_spec)

    def run_portfolio_backtest(
        self,
        command: PortfolioRunCommand,
        run_spec: BacktestRunSpec,
    ) -> PortfolioRunResult:
        return self._portfolio_executor().run(command=command, run_spec=run_spec)

    def dry_run_backtest(
        self,
        command: BacktestDryRunCommand,
        run_spec: BacktestRunSpec,
    ) -> BacktestDryRunResult:
        _emit_stage(
            self.diagnostics,
            stage="backtest.dry_run",
            status="started",
            message="starting canonical backtest dry-run",
            requested_by=command.requested_by,
            run_id=run_spec.run_id,
            correlation_id=command.correlation_id,
            run_kind=run_spec.run_kind.value,
            details=run_details(run_spec),
        )
        try:
            result = dry_run_backtest(
                command=command,
                run_spec=run_spec,
                dependencies=self.dry_run_dependencies,
            )
        except Exception as exc:
            _emit_stage(
                self.diagnostics,
                stage="backtest.dry_run",
                status="failed",
                message="canonical backtest dry-run failed",
                requested_by=command.requested_by,
                run_id=run_spec.run_id,
                correlation_id=command.correlation_id,
                run_kind=run_spec.run_kind.value,
                details={**run_details(run_spec), "error_type": type(exc).__name__},
            )
            raise

        _emit_stage(
            self.diagnostics,
            stage="backtest.dry_run",
            status="succeeded",
            message="finished canonical backtest dry-run",
            requested_by=command.requested_by,
            run_id=run_spec.run_id,
            correlation_id=command.correlation_id,
            run_kind=run_spec.run_kind.value,
            details={
                **run_details(run_spec),
                "catalog_root": result.catalog_root,
                "data_count": result.data_count,
            },
        )
        return result

    def run_batch_backtests(self, command: BatchRunCommand) -> BatchRunResult:
        _emit_stage(
            self.diagnostics,
            stage="batch.run",
            status="started",
            message="starting canonical batch backtests",
            requested_by=command.requested_by,
            correlation_id=command.correlation_id,
            details={"run_count": len(command.run_specs)},
        )
        try:
            result = run_batch_backtests(
                command=command,
                single_executor=self._single_executor(),
                portfolio_executor=self._portfolio_executor(),
            )
        except Exception as exc:
            _emit_stage(
                self.diagnostics,
                stage="batch.run",
                status="failed",
                message="canonical batch backtests failed",
                requested_by=command.requested_by,
                correlation_id=command.correlation_id,
                details={"run_count": len(command.run_specs), "error_type": type(exc).__name__},
            )
            raise

        _emit_stage(
            self.diagnostics,
            stage="batch.run",
            status="succeeded",
            message="finished canonical batch backtests",
            requested_by=command.requested_by,
            correlation_id=command.correlation_id,
            details={
                "run_count": len(command.run_specs),
                "bundle_count": len(result.summary.bundle_uris),
            },
        )
        return result

    def run_walk_forward(self, command: WalkForwardCommand) -> WalkForwardResult:
        _emit_stage(
            self.diagnostics,
            stage="walk_forward.run",
            status="started",
            message="starting canonical walk-forward job",
            requested_by=command.requested_by,
            correlation_id=command.correlation_id,
            details={"fold_count": len(command.fold_run_specs), "metric_name": command.metric_name},
        )
        try:
            result = run_walk_forward(command=command, runtime=self._build_trial_runtime())
        except Exception as exc:
            _emit_stage(
                self.diagnostics,
                stage="walk_forward.run",
                status="failed",
                message="canonical walk-forward job failed",
                requested_by=command.requested_by,
                correlation_id=command.correlation_id,
                details={
                    "fold_count": len(command.fold_run_specs),
                    "metric_name": command.metric_name,
                    "error_type": type(exc).__name__,
                },
            )
            raise

        _emit_stage(
            self.diagnostics,
            stage="walk_forward.run",
            status="succeeded",
            message="finished canonical walk-forward job",
            requested_by=command.requested_by,
            run_id=result.best_run_id,
            correlation_id=command.correlation_id,
            details={"fold_count": len(command.fold_run_specs), "metric_name": command.metric_name},
        )
        return result

    def run_walk_forward_batch(
        self,
        command: WalkForwardBatchCommand,
    ) -> WalkForwardBatchResult:
        _emit_stage(
            self.diagnostics,
            stage="walk_forward.batch.run",
            status="started",
            message="starting canonical walk-forward batch",
            requested_by="operator",
            correlation_id=command.correlation_id,
            details={"job_count": len(command.jobs)},
        )
        try:
            result = run_walk_forward_batch(command=command, runtime=self._build_trial_runtime())
        except Exception as exc:
            _emit_stage(
                self.diagnostics,
                stage="walk_forward.batch.run",
                status="failed",
                message="canonical walk-forward batch failed",
                requested_by="operator",
                correlation_id=command.correlation_id,
                details={"job_count": len(command.jobs), "error_type": type(exc).__name__},
            )
            raise

        _emit_stage(
            self.diagnostics,
            stage="walk_forward.batch.run",
            status="succeeded",
            message="finished canonical walk-forward batch",
            requested_by="operator",
            correlation_id=command.correlation_id,
            details={"job_count": len(command.jobs)},
        )
        return result

    def run_portfolio_weight_study(
        self,
        command: PortfolioWeightStudyCommand,
    ) -> PortfolioWeightStudyRunResult:
        _emit_stage(
            self.diagnostics,
            stage="portfolio_weight_study.run",
            status="started",
            message="starting portfolio-weight study",
            requested_by=command.requested_by,
            correlation_id=command.correlation_id,
            details={"fold_count": len(command.study_spec.folds)},
        )
        try:
            result = run_portfolio_weight_study(
                command=command,
                dependencies=self.study_dependencies,
            )
        except Exception as exc:
            _emit_stage(
                self.diagnostics,
                stage="portfolio_weight_study.run",
                status="failed",
                message="portfolio-weight study failed",
                requested_by=command.requested_by,
                correlation_id=command.correlation_id,
                details={
                    "fold_count": len(command.study_spec.folds),
                    "error_type": type(exc).__name__,
                },
            )
            raise

        _emit_stage(
            self.diagnostics,
            stage="portfolio_weight_study.run",
            status="succeeded",
            message="finished portfolio-weight study",
            requested_by=command.requested_by,
            correlation_id=command.correlation_id,
            details={
                "fold_count": len(command.study_spec.folds),
                "study_id": result.study_id,
                "recommendation_id": result.recommendation_id,
            },
        )
        return result

    def run_scenario(self, command: ScenarioRunCommand) -> PortfolioRunResult:
        return run_scenario(command=command, executor=self._portfolio_executor())

    def capture_baseline(self, command: BaselineCaptureCommand) -> BaselineCaptureResult:
        return capture_baseline(
            command=command,
            single_executor=self._single_executor(),
            portfolio_executor=self._portfolio_executor(),
        )

    def load_bundle_read_model(self, bundle_path: Path) -> BundleReadModel:
        return load_bundle_read_model(bundle_path=bundle_path, loader=self.bundle_loader)

    def load_bundle_dashboard_read_model(self, bundle_path: Path) -> BundleDashboardReadModel:
        return load_bundle_dashboard_read_model(bundle_path=bundle_path, loader=self.bundle_loader)

    def load_bundle(self, bundle_path: Path) -> ResultBundle:
        return self.bundle_loader.load_bundle(bundle_path)

    def _single_executor(self) -> _SingleExecutor:
        return _SingleExecutor(self.single_dependencies, self.diagnostics)

    def _portfolio_executor(self) -> _PortfolioExecutor:
        return _PortfolioExecutor(self.portfolio_dependencies, self.diagnostics)

    def _build_trial_executor(self) -> CanonicalTrialExecutor:
        return CanonicalTrialExecutor(
            single_executor=self._single_executor(),
            portfolio_executor=self._portfolio_executor(),
        )

    def _build_trial_runtime(self) -> CanonicalTrialRuntime:
        return CanonicalTrialRuntime(
            executor=self._build_trial_executor(),
            max_parallel_trials=self.settings.optimization.max_parallel_trials,
            diagnostics=self.diagnostics,
        )


def build_application_container(
    settings: PlatformSettings,
    ports: InfrastructurePorts,
    clock: Clock | None = None,
    diagnostics: DiagnosticsSink | None = None,
) -> ApplicationContainer:
    """Assemble explicit use-case and read-model dependencies in one place."""

    active_clock = clock or SystemClock()
    active_diagnostics = diagnostics or build_default_diagnostics_logger()
    return ApplicationContainer(
        settings=settings,
        single_dependencies=SingleRunDependencies(
            runner=ports.nautilus_runner,
            artifact_store=ports.artifact_store,
            clock=active_clock,
        ),
        portfolio_dependencies=PortfolioRunDependencies(
            runner=ports.nautilus_runner,
            projector=ports.portfolio_projector,
            artifact_store=ports.artifact_store,
            clock=active_clock,
        ),
        dry_run_dependencies=BacktestDryRunDependencies(
            compiler=ports.run_spec_compiler,
        ),
        bundle_loader=ports.bundle_loader,
        study_dependencies=PortfolioWeightStudyDependencies(
            single_executor=_SingleExecutor(
                SingleRunDependencies(
                    runner=ports.nautilus_runner,
                    artifact_store=ports.artifact_store,
                    clock=active_clock,
                ),
                active_diagnostics,
            ),
            portfolio_executor=_PortfolioExecutor(
                PortfolioRunDependencies(
                    runner=ports.nautilus_runner,
                    projector=ports.portfolio_projector,
                    artifact_store=ports.artifact_store,
                    clock=active_clock,
                ),
                active_diagnostics,
            ),
            bundle_loader=ports.bundle_loader,
            artifact_store=ports.study_artifact_store,
            clock=active_clock,
        ),
        diagnostics=active_diagnostics,
    )


def build_infrastructure_ports(
    settings: PlatformSettings,
    *,
    run_spec_compiler: NautilusRunSpecCompiler,
    nautilus_runner: NautilusRunner,
    portfolio_projector: PortfolioProjector,
) -> InfrastructurePorts:
    """Assemble concrete infrastructure adapters owned by the rewrite."""

    return InfrastructurePorts(
        run_spec_compiler=run_spec_compiler,
        nautilus_runner=nautilus_runner,
        artifact_store=FilesystemArtifactStore(results_root=settings.runtime.results_root),
        bundle_loader=FilesystemBundleLoader(),
        portfolio_projector=portfolio_projector,
        study_artifact_store=FilesystemStudyArtifactStore(results_root=settings.runtime.results_root),
    )


def build_default_infrastructure_ports(
    settings: PlatformSettings,
    *,
    execution_costs_path: Path | None = None,
) -> InfrastructurePorts:
    """Assemble the default V2 Nautilus/data runtime stack."""

    compiler = _build_default_nautilus_run_spec_compiler(
        settings,
        execution_costs_path=execution_costs_path,
    )
    nautilus_runner = BacktestNodeNautilusRunner(
        compiler=compiler,
        report_writer=NautilusReportWriter(),
    )
    return build_infrastructure_ports(
        settings=settings,
        run_spec_compiler=compiler,
        nautilus_runner=nautilus_runner,
        portfolio_projector=FilesystemPortfolioProjector(),
    )


def _build_default_nautilus_run_spec_compiler(
    settings: PlatformSettings,
    *,
    execution_costs_path: Path | None = None,
) -> NautilusRunSpecCompiler:
    """Assemble the default compiler used by execution and dry-run flows."""

    dataset_materializer = _build_default_dataset_materializer(settings)
    catalog_builder = FilesystemNautilusCatalogBuilder(
        # Nautilus creates deeply nested parquet paths under this root. Keep the
        # segment short so Windows/pyarrow runs stay below legacy MAX_PATH limits.
        catalog_cache_root=settings.data.cache_root / "ntc",
    )
    return CanonicalNautilusRunSpecCompiler(
        runtime_settings=settings.runtime,
        dataset_materializer=dataset_materializer,
        catalog_builder=catalog_builder,
        strategy_resolver=build_default_nautilus_strategy_resolver(),
        execution_costs_path=execution_costs_path,
    )


def _build_default_dataset_materializer(
    settings: PlatformSettings,
) -> FilesystemParquetDatasetNormalizer:
    """Assemble the provider-aware normalized dataset materializer."""

    return FilesystemParquetDatasetNormalizer(
        cache_store=FilesystemParquetCacheStore(
            source_cache_root=settings.data.source_cache_root,
        ),
        normalized_root=settings.data.data_root / "datasets",
        market_data_store=FilesystemHistoricalDataStore(
            source_cache_root=settings.data.source_cache_root,
        ),
        validator_ruleset_version=MARKET_DATA_VALIDATOR_RULESET_VERSION,
    )


def build_http_container(
    settings: PlatformSettings | None = None,
    *,
    clock: Clock | None = None,
    diagnostics: DiagnosticsSink | None = None,
) -> ApplicationContainer:
    """Build the default application container used by HTTP delivery surfaces."""

    resolved_settings = settings or load_settings()
    return build_application_container(
        settings=resolved_settings,
        ports=build_default_infrastructure_ports(resolved_settings),
        clock=clock,
        diagnostics=diagnostics,
    )


def build_cli_container(
    settings: PlatformSettings | None = None,
    *,
    clock: Clock | None = None,
    diagnostics: DiagnosticsSink | None = None,
    execution_costs_path: Path | None = None,
) -> ApplicationContainer:
    """Build the default application container used by CLI delivery surfaces."""

    resolved_settings = settings or load_settings()
    return build_application_container(
        settings=resolved_settings,
        ports=build_default_infrastructure_ports(
            resolved_settings,
            execution_costs_path=execution_costs_path,
        ),
        clock=clock,
        diagnostics=diagnostics,
    )


def build_calibration_dataset_materializer(
    settings: PlatformSettings | None = None,
) -> FilesystemParquetDatasetNormalizer:
    """Build the normalized dataset materializer used by calibration CLI jobs."""

    resolved_settings = settings or load_settings()
    return _build_default_dataset_materializer(resolved_settings)


def build_ib_historical_ingestor(
    settings: PlatformSettings | None = None,
) -> IbHistoricalCacheIngestor:
    """Build the explicit IB source-cache ingestor for V2 infrastructure use."""

    resolved_settings = settings or load_settings()
    client = IbHistoricalClient(settings=resolved_settings.data.ib)
    return IbHistoricalCacheIngestor(
        client=client,
        contract_resolver=IbContractResolver(client=client),
        cache_store=FilesystemIbCacheStore(
            source_cache_root=resolved_settings.data.source_cache_root,
        ),
    )


def build_market_data_service(
    settings: PlatformSettings | None = None,
    *,
    diagnostics: DiagnosticsSink | None = None,
) -> "HistoricalMarketDataService":
    """Build the unified historical market-data service."""

    from backtest_engine.bootstrap._market_data_runtime import build_market_data_service as _build_service

    return _build_service(settings=settings, diagnostics=diagnostics)


__all__ = [
    "ApplicationContainer",
    "BacktestDryRunCommand",
    "BacktestDryRunResult",
    "InfrastructurePorts",
    "build_application_container",
    "build_cli_container",
    "build_calibration_dataset_materializer",
    "build_default_infrastructure_ports",
    "build_http_container",
    "build_ib_historical_ingestor",
    "build_market_data_service",
    "build_infrastructure_ports",
]
