from __future__ import annotations

from decimal import Decimal
from datetime import datetime, timezone
from pathlib import Path

from backtest_engine.application.baselines.capture_baseline import (
    BaselineCaptureCommand,
    BaselineCaptureResult,
)
from backtest_engine.application.batch.run_batch_backtests import BatchRunCommand, BatchRunResult
from backtest_engine.application.batch.summarize_batch_results import BatchSummary
from backtest_engine.application.optimization.run_walk_forward import (
    WalkForwardCommand,
    WalkForwardResult,
)
from backtest_engine.application.optimization.run_walk_forward_batch import (
    WalkForwardBatchCommand,
    WalkForwardBatchResult,
)
from backtest_engine.application.portfolio.run_portfolio_backtest import (
    PortfolioRunCommand,
    PortfolioRunResult,
)
from backtest_engine.application.single.run_single_backtest import (
    SingleRunCommand,
    SingleRunResult,
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
from backtest_engine.interfaces.cli import (
    BaselineCaptureCliCommand,
    BatchBacktestsCliCommand,
    ConfirmedFoldsCliCommand,
    LatestRecommendationCliCommand,
    PortfolioBacktestCliCommand,
    RecommendationCliCommand,
    SingleBacktestCliCommand,
    StudyChampionCliCommand,
    StudySummaryCliCommand,
    WalkForwardBatchCliCommand,
    WalkForwardCliCommand,
    capture_baseline_cli,
    read_confirmed_folds_cli,
    read_latest_recommendation_cli,
    read_recommendation_cli,
    read_study_champion_cli,
    read_study_summary_cli,
    run_batch_backtests_cli,
    run_portfolio_backtest_cli,
    run_single_backtest_cli,
    run_walk_forward_batch_cli,
    run_walk_forward_cli,
)
from backtest_engine.analytics.read_models import (
    ConfirmedFoldCollectionReadModel,
    LiveAllocationRecommendationReadModel,
    RecommendationStatus,
    StudyChampionReadModel,
    StudySummaryReadModel,
    StudyVerdict,
)


def _build_run_spec(run_kind: RunKind, strategy_id: str, symbol: str) -> BacktestRunSpec:
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
            symbol_universe=(symbol,),
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
                legs=(StrategyLegSpec(symbol=symbol),),
            ),
        ),
        capital_base=Money(amount=Decimal("100000"), currency="USD"),
    )


class FakeSingleCliRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[SingleRunCommand, BacktestRunSpec]] = []

    def run_single_backtest(
        self,
        command: SingleRunCommand,
        run_spec: BacktestRunSpec,
    ) -> SingleRunResult:
        self.calls.append((command, run_spec))
        return SingleRunResult(
            run_id=run_spec.run_id,
            bundle_id="bundle-single-cli",
            bundle_uri="results/bundle-single-cli",
            runtime_root=f"var/runtime/nautilus/{run_spec.run_id}",
            metric_values={"net_profit": 100.0},
        )


class FakePortfolioCliRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[PortfolioRunCommand, BacktestRunSpec]] = []

    def run_portfolio_backtest(
        self,
        command: PortfolioRunCommand,
        run_spec: BacktestRunSpec,
    ) -> PortfolioRunResult:
        self.calls.append((command, run_spec))
        return PortfolioRunResult(
            run_id=run_spec.run_id,
            bundle_id="bundle-portfolio-cli",
            bundle_uri="results/bundle-portfolio-cli",
            runtime_root=f"var/runtime/nautilus/{run_spec.run_id}",
            allocation_count=1,
            position_count=2,
            metric_values={"net_profit": 250.0},
        )


class FakeBatchCliRunner:
    def __init__(self) -> None:
        self.calls: list[BatchRunCommand] = []

    def run_batch_backtests(self, command: BatchRunCommand) -> BatchRunResult:
        self.calls.append(command)
        return BatchRunResult(
            results=tuple(),
            summary=BatchSummary(
                total_runs=len(command.run_specs),
                succeeded_runs=len(command.run_specs),
                single_runs=sum(spec.run_kind is RunKind.SINGLE for spec in command.run_specs),
                portfolio_runs=sum(spec.run_kind is RunKind.PORTFOLIO for spec in command.run_specs),
                bundle_uris=tuple(),
            ),
        )


class FakeWalkForwardCliRunner:
    def __init__(self) -> None:
        self.calls: list[WalkForwardCommand] = []

    def run_walk_forward(self, command: WalkForwardCommand) -> WalkForwardResult:
        self.calls.append(command)
        return WalkForwardResult(fold_results=tuple(), best_run_id=None)


class FakeWalkForwardBatchCliRunner:
    def __init__(self) -> None:
        self.calls: list[WalkForwardBatchCommand] = []

    def run_walk_forward_batch(
        self,
        command: WalkForwardBatchCommand,
    ) -> WalkForwardBatchResult:
        self.calls.append(command)
        return WalkForwardBatchResult(job_results=tuple())


class FakeBaselineCliRunner:
    def __init__(self) -> None:
        self.calls: list[BaselineCaptureCommand] = []

    def capture_baseline(self, command: BaselineCaptureCommand) -> BaselineCaptureResult:
        self.calls.append(command)
        return BaselineCaptureResult(
            label=command.label,
            run_id=command.run_spec.run_id,
            bundle_uri="results/baseline-cli",
        )


class FakeStudySummaryCliRunner:
    def __init__(self) -> None:
        self.calls: list[Path] = []

    def load_study_summary(self, artifact_path: Path) -> StudySummaryReadModel:
        self.calls.append(artifact_path)
        return StudySummaryReadModel(
            schema_version=1,
            study_id="study-001",
            artifact_path=artifact_path,
            created_at_utc=datetime(2026, 4, 11, tzinfo=timezone.utc),
            objective_metric="sharpe",
            verdict=StudyVerdict.PASS,
            fold_count=5,
            trial_count=120,
            median_oos_score=0.24,
            median_oos_sharpe=0.36,
            pass_folds=3,
            warning_folds=1,
            fail_folds=1,
            champion_weights={"slot-1": 0.6, "slot-2": 0.4},
            source_bundle_uris=("results/bundle-1",),
            summary={"note": "cli"},
        )


class FakeRecommendationCliRunner:
    def __init__(self) -> None:
        self.calls: list[Path] = []

    def load_recommendation(
        self,
        artifact_path: Path,
    ) -> LiveAllocationRecommendationReadModel:
        self.calls.append(artifact_path)
        return LiveAllocationRecommendationReadModel(
            schema_version=1,
            recommendation_id="recommendation-001",
            study_id="study-001",
            artifact_path=artifact_path,
            as_of_utc=datetime(2026, 4, 11, 11, tzinfo=timezone.utc),
            source_window_start_utc=datetime(2026, 4, 1, tzinfo=timezone.utc),
            source_window_end_utc=datetime(2026, 4, 10, tzinfo=timezone.utc),
            status=RecommendationStatus.PUBLISHED,
            target_portfolio_vol_frac=0.15,
            weight_step_frac=0.01,
            max_sleeve_weight_frac=1.0,
            top_k_confirm=5,
            champion_weights={"slot-1": 0.6, "slot-2": 0.4},
            summary={"note": "cli"},
        )


class FakeConfirmedFoldsCliRunner:
    def __init__(self) -> None:
        self.calls: list[Path] = []

    def load_confirmed_folds(self, artifact_path: Path) -> ConfirmedFoldCollectionReadModel:
        self.calls.append(artifact_path)
        return ConfirmedFoldCollectionReadModel(
            schema_version=1,
            study_id="study-001",
            artifact_path=artifact_path,
            folds=(),
        )


class FakeStudyChampionCliRunner:
    def __init__(self) -> None:
        self.calls: list[Path] = []

    def load_study_champion(self, artifact_path: Path) -> StudyChampionReadModel:
        self.calls.append(artifact_path)
        return StudyChampionReadModel(
            schema_version=1,
            study_id="study-001",
            artifact_path=artifact_path,
            created_at_utc=datetime(2026, 4, 11, tzinfo=timezone.utc),
            verdict=StudyVerdict.PASS,
            champion_weights={"slot-1": 0.6, "slot-2": 0.4},
            source_fold_id="fold-001",
            source_candidate_id="candidate-001",
            summary={"note": "cli"},
        )


class FakeLatestRecommendationCliRunner:
    def __init__(self) -> None:
        self.calls: list[Path] = []

    def load_latest_recommendation(
        self,
        results_root: Path,
    ) -> LiveAllocationRecommendationReadModel:
        self.calls.append(results_root)
        return LiveAllocationRecommendationReadModel(
            schema_version=1,
            recommendation_id="recommendation-latest",
            study_id="study-001",
            artifact_path=results_root / "recommendations" / "latest.json",
            as_of_utc=datetime(2026, 4, 11, 11, tzinfo=timezone.utc),
            source_window_start_utc=datetime(2026, 4, 1, tzinfo=timezone.utc),
            source_window_end_utc=datetime(2026, 4, 10, tzinfo=timezone.utc),
            status=RecommendationStatus.BLOCKED,
            target_portfolio_vol_frac=0.15,
            weight_step_frac=0.01,
            max_sleeve_weight_frac=1.0,
            top_k_confirm=5,
            champion_weights={"slot-1": 0.6, "slot-2": 0.4},
            summary={"publication_blockers": ["runtime_policy_parity_pending"]},
        )


def test_run_single_backtest_cli_delegates_to_the_canonical_use_case() -> None:
    runner = FakeSingleCliRunner()
    run_spec = _build_run_spec(RunKind.SINGLE, "sma_pullback", "ES")

    result = run_single_backtest_cli(
        command=SingleBacktestCliCommand(
            run_spec=run_spec,
            correlation_id="cli-correlation",
            bundle_label="review-bundle",
        ),
        runner=runner,
    )

    delegated_command, delegated_spec = runner.calls[0]
    assert delegated_command.requested_by == "cli"
    assert delegated_command.correlation_id == "cli-correlation"
    assert delegated_command.bundle_label == "review-bundle"
    assert delegated_spec == run_spec
    assert result.bundle_id == "bundle-single-cli"


def test_run_portfolio_backtest_cli_delegates_to_the_canonical_use_case() -> None:
    runner = FakePortfolioCliRunner()
    run_spec = _build_run_spec(RunKind.PORTFOLIO, "breakout", "NQ")

    result = run_portfolio_backtest_cli(
        command=PortfolioBacktestCliCommand(
            run_spec=run_spec,
            requested_by="portfolio-cli",
            correlation_id="portfolio-correlation",
        ),
        runner=runner,
    )

    delegated_command, delegated_spec = runner.calls[0]
    assert delegated_command.requested_by == "portfolio-cli"
    assert delegated_command.correlation_id == "portfolio-correlation"
    assert delegated_spec == run_spec
    assert result.position_count == 2


def test_run_batch_backtests_cli_delegates_to_the_canonical_use_case() -> None:
    runner = FakeBatchCliRunner()
    single_spec = _build_run_spec(RunKind.SINGLE, "sma_pullback", "ES")
    portfolio_spec = _build_run_spec(RunKind.PORTFOLIO, "breakout", "NQ")

    result = run_batch_backtests_cli(
        command=BatchBacktestsCliCommand(
            correlation_id="batch-correlation",
            run_specs=(single_spec, portfolio_spec),
        ),
        runner=runner,
    )

    delegated_command = runner.calls[0]
    assert delegated_command.requested_by == "cli"
    assert delegated_command.correlation_id == "batch-correlation"
    assert delegated_command.run_specs == (single_spec, portfolio_spec)
    assert result.summary.total_runs == 2


def test_run_walk_forward_cli_delegates_to_the_canonical_use_case() -> None:
    runner = FakeWalkForwardCliRunner()
    single_spec = _build_run_spec(RunKind.SINGLE, "sma_pullback", "ES")

    result = run_walk_forward_cli(
        command=WalkForwardCliCommand(
            requested_by="wfo-cli",
            correlation_id="wfo-correlation",
            metric_name="sharpe",
            fold_run_specs=(single_spec,),
        ),
        runner=runner,
    )

    delegated_command = runner.calls[0]
    assert delegated_command.requested_by == "wfo-cli"
    assert delegated_command.correlation_id == "wfo-correlation"
    assert delegated_command.metric_name == "sharpe"
    assert delegated_command.fold_run_specs == (single_spec,)
    assert result.best_run_id is None


def test_run_walk_forward_batch_cli_delegates_to_the_canonical_use_case() -> None:
    runner = FakeWalkForwardBatchCliRunner()
    first_spec = _build_run_spec(RunKind.SINGLE, "sma_pullback", "ES")
    second_spec = _build_run_spec(RunKind.PORTFOLIO, "breakout", "NQ")

    result = run_walk_forward_batch_cli(
        command=WalkForwardBatchCliCommand(
            correlation_id="wfo-batch-correlation",
            jobs=(
                WalkForwardCliCommand(metric_name="net_profit", fold_run_specs=(first_spec,)),
                WalkForwardCliCommand(
                    requested_by="wfo-batch-cli",
                    correlation_id="job-correlation",
                    metric_name="sharpe",
                    fold_run_specs=(second_spec,),
                ),
            )
        ),
        runner=runner,
    )

    delegated_command = runner.calls[0]
    assert delegated_command.correlation_id == "wfo-batch-correlation"
    assert len(delegated_command.jobs) == 2
    assert delegated_command.jobs[0].requested_by == "cli"
    assert delegated_command.jobs[0].correlation_id is None
    assert delegated_command.jobs[0].fold_run_specs == (first_spec,)
    assert delegated_command.jobs[1].requested_by == "wfo-batch-cli"
    assert delegated_command.jobs[1].correlation_id == "job-correlation"
    assert delegated_command.jobs[1].metric_name == "sharpe"
    assert delegated_command.jobs[1].fold_run_specs == (second_spec,)
    assert result.job_results == tuple()


def test_capture_baseline_cli_delegates_to_the_canonical_use_case() -> None:
    runner = FakeBaselineCliRunner()
    run_spec = _build_run_spec(RunKind.PORTFOLIO, "breakout", "NQ")

    result = capture_baseline_cli(
        command=BaselineCaptureCliCommand(
            label="phase-g-baseline",
            run_spec=run_spec,
        ),
        runner=runner,
    )

    delegated_command = runner.calls[0]
    assert delegated_command.label == "phase-g-baseline"
    assert delegated_command.requested_by == "cli"
    assert delegated_command.run_spec == run_spec
    assert result.bundle_uri == "results/baseline-cli"


def test_read_study_summary_cli_delegates_to_the_canonical_read_model_path() -> None:
    runner = FakeStudySummaryCliRunner()
    command = StudySummaryCliCommand(artifact_path=Path("results/studies/study-001/study.json"))

    result = read_study_summary_cli(command=command, runner=runner)

    assert runner.calls == [command.artifact_path]
    assert result.study_id == "study-001"
    assert result.verdict is StudyVerdict.PASS


def test_read_recommendation_cli_delegates_to_the_canonical_read_model_path() -> None:
    runner = FakeRecommendationCliRunner()
    command = RecommendationCliCommand(
        artifact_path=Path("results/recommendations/recommendation-001/recommendation.json")
    )

    result = read_recommendation_cli(command=command, runner=runner)

    assert runner.calls == [command.artifact_path]
    assert result.recommendation_id == "recommendation-001"
    assert result.status is RecommendationStatus.PUBLISHED


def test_read_confirmed_folds_cli_delegates_to_the_canonical_read_model_path() -> None:
    runner = FakeConfirmedFoldsCliRunner()
    command = ConfirmedFoldsCliCommand(artifact_path=Path("results/studies/study-001/folds.json"))

    result = read_confirmed_folds_cli(command=command, runner=runner)

    assert runner.calls == [command.artifact_path]
    assert result.study_id == "study-001"


def test_read_study_champion_cli_delegates_to_the_canonical_read_model_path() -> None:
    runner = FakeStudyChampionCliRunner()
    command = StudyChampionCliCommand(artifact_path=Path("results/studies/study-001/champion.json"))

    result = read_study_champion_cli(command=command, runner=runner)

    assert runner.calls == [command.artifact_path]
    assert result.source_candidate_id == "candidate-001"


def test_read_latest_recommendation_cli_delegates_to_the_canonical_read_model_path() -> None:
    runner = FakeLatestRecommendationCliRunner()
    command = LatestRecommendationCliCommand(results_root=Path("results"))

    result = read_latest_recommendation_cli(command=command, runner=runner)

    assert runner.calls == [command.results_root]
    assert result.recommendation_id == "recommendation-latest"
    assert result.status is RecommendationStatus.BLOCKED
