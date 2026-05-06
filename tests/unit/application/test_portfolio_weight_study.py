# mypy: disable-error-code=no-untyped-def
from __future__ import annotations

from decimal import Decimal
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from backtest_engine.analytics.read_models import (
    RecommendationStatus,
    StudyVerdict,
    load_live_allocation_recommendation_read_model,
    load_study_summary_read_model,
)
from backtest_engine.application.optimization.portfolio_weight_study import (
    PortfolioWeightStudyCommand,
    PortfolioWeightStudyControlSpec,
    PortfolioWeightStudyDependencies,
    PortfolioWeightStudyFoldSpec,
    PortfolioWeightStudySpec,
    PortfolioWeightStudyThresholds,
    run_portfolio_weight_study,
)
from backtest_engine.application.portfolio.run_portfolio_backtest import PortfolioRunResult
from backtest_engine.application.single.run_single_backtest import SingleRunResult
from backtest_engine.config.runtime import (
    BacktestRunSpec,
    ExecutionWindow,
    PortfolioExecutionPolicy,
)
from backtest_engine.core.enums import DatasetSource, RunKind, RuntimeBoundary
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
from backtest_engine.infrastructure.optimization.study_store import FilesystemStudyArtifactStore


def _build_portfolio_run_spec(
    *,
    start_utc: datetime,
    end_utc: datetime,
    weight_a: float = 0.5,
    weight_b: float = 0.5,
) -> BacktestRunSpec:
    return BacktestRunSpec(
        run_kind=RunKind.PORTFOLIO,
        execution_window=ExecutionWindow(start_utc=start_utc, end_utc=end_utc),
        dataset=DatasetSpec(
            source_system=DatasetSource.PARQUET,
            normalization_policy="nautilus_v1",
            schema_version="1",
            symbol_universe=("ES", "NQ"),
            timeframe="30m",
            dataset_version="2026-04-11",
        ),
        strategies=(
            PortfolioStrategySpec(
                slot_id="slot-a",
                weight_frac=weight_a,
                strategy=StrategySpec(
                    strategy_id="sleeve-a",
                    implementation_id="sma_pullback",
                    policy_version="v1",
                    parameters={"trade_size": 1.0},
                ),
                legs=(StrategyLegSpec(symbol="ES"),),
            ),
            PortfolioStrategySpec(
                slot_id="slot-b",
                weight_frac=weight_b,
                strategy=StrategySpec(
                    strategy_id="sleeve-b",
                    implementation_id="channel_breakout_long",
                    policy_version="v1",
                    parameters={"trade_size": 1.0},
                ),
                legs=(StrategyLegSpec(symbol="NQ"),),
            ),
        ),
        capital_base=Money(amount=Decimal("100000"), currency="USD"),
        portfolio_policy=PortfolioExecutionPolicy(
            target_portfolio_vol_frac=0.15,
            vol_lookback_bars=5,
        ),
    )


class FakeClock:
    def __init__(self, now_utc: datetime) -> None:
        self._now_utc = now_utc

    def now_utc(self) -> datetime:
        return self._now_utc


class FakeBundleLoader:
    def __init__(self) -> None:
        self._bundles: dict[Path, ResultBundle] = {}

    def add_bundle(self, bundle_uri: str, bundle: ResultBundle) -> None:
        self._bundles[Path(bundle_uri)] = bundle

    def load_bundle(self, path: Path) -> ResultBundle:
        return self._bundles[path]


class FakeSingleExecutor:
    def __init__(self, tmp_path: Path, bundle_loader: FakeBundleLoader) -> None:
        self._tmp_path = tmp_path
        self._bundle_loader = bundle_loader

    def run(self, command, run_spec: BacktestRunSpec) -> SingleRunResult:
        strategy = run_spec.strategies[0]
        returns = (
            [0.012, 0.009, 0.011, 0.008, 0.013, 0.01, 0.012, 0.009, 0.011, 0.008, 0.013, 0.01]
            if strategy.slot_id == "slot-a"
            else [0.003, -0.001, 0.002, 0.0, 0.004, -0.002, 0.003, -0.001, 0.002, 0.0, 0.004, -0.002]
        )
        returns_path = self._tmp_path / f"{run_spec.run_id}-returns.parquet"
        pd.DataFrame(
            {
                "timestamp_utc": pd.date_range(
                    start=run_spec.execution_window.start_utc,
                    periods=len(returns),
                    freq="1D",
                    tz="UTC",
                ),
                "return_after_costs": returns,
            }
        ).to_parquet(returns_path)
        bundle_uri = f"results/{run_spec.run_id}"
        self._bundle_loader.add_bundle(bundle_uri, _build_bundle(run_spec, returns_path))
        return SingleRunResult(
            run_id=run_spec.run_id,
            bundle_id=f"bundle-{run_spec.run_id[-12:]}",
            bundle_uri=bundle_uri,
            runtime_root=f"var/runtime/nautilus/{run_spec.run_id}",
            metric_values={"sharpe_after_costs": 1.0},
        )


class FakePortfolioExecutor:
    def run(self, command, run_spec: BacktestRunSpec) -> PortfolioRunResult:
        weight_a = float(run_spec.strategies[0].weight_frac)
        weight_b = float(run_spec.strategies[1].weight_frac)
        sharpe_after_costs = 0.2 + (0.5 * weight_a) + (0.1 * weight_b)
        net_return = 0.03 + (0.08 * weight_a) + (0.02 * weight_b)
        return PortfolioRunResult(
            run_id=run_spec.run_id,
            bundle_id=f"bundle-{run_spec.run_id[-12:]}",
            bundle_uri=f"results/{run_spec.run_id}",
            runtime_root=f"var/runtime/nautilus/{run_spec.run_id}",
            allocation_count=len(run_spec.strategies),
            position_count=2,
            metric_values={
                "sharpe_after_costs": sharpe_after_costs,
                "net_return": net_return,
                "max_drawdown": 0.05,
                "trade_count": 10.0,
            },
        )


def _build_bundle(run_spec: BacktestRunSpec, returns_path: Path) -> ResultBundle:
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
            created_at_utc=run_spec.execution_window.end_utc,
        ),
        run_spec=run_spec,
        artifact_locations={
            "runtime_root": f"var/runtime/nautilus/{run_spec.run_id}",
            "returns_report": returns_path.as_posix(),
        },
        summary={"net_return": 0.1},
    )


def _build_study_spec() -> PortfolioWeightStudySpec:
    fold = PortfolioWeightStudyFoldSpec(
        fold_id="fold-001",
        in_sample_run_spec=_build_portfolio_run_spec(
            start_utc=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end_utc=datetime(2024, 1, 15, tzinfo=timezone.utc),
        ),
        out_of_sample_run_spec=_build_portfolio_run_spec(
            start_utc=datetime(2024, 1, 15, tzinfo=timezone.utc),
            end_utc=datetime(2024, 1, 22, tzinfo=timezone.utc),
        ),
    )
    return PortfolioWeightStudySpec(
        folds=(fold,),
        control=PortfolioWeightStudyControlSpec(
            min_effective_oos_bars=5,
            weight_step_frac=0.5,
            top_k_confirm=2,
            verdict_thresholds=PortfolioWeightStudyThresholds(
                quality_sharpe_floor=0.2,
                min_quality_profitable_folds=1,
                min_consecutive_quality_profitable_folds=1,
                min_trades_per_fold=7,
                max_recommendation_age_days=365,
            ),
        ),
        seed=11,
    )


def test_run_portfolio_weight_study_persists_typed_artifacts(tmp_path: Path) -> None:
    bundle_loader = FakeBundleLoader()
    study_spec = _build_study_spec()
    result = run_portfolio_weight_study(
        command=PortfolioWeightStudyCommand(study_spec=study_spec, requested_by="test"),
        dependencies=PortfolioWeightStudyDependencies(
            single_executor=FakeSingleExecutor(tmp_path, bundle_loader),
            portfolio_executor=FakePortfolioExecutor(),
            bundle_loader=bundle_loader,
            artifact_store=FilesystemStudyArtifactStore(results_root=tmp_path / "results"),
            clock=FakeClock(datetime(2024, 1, 23, tzinfo=timezone.utc)),
        ),
    )

    study = load_study_summary_read_model(Path(result.study_uri))
    recommendation = load_live_allocation_recommendation_read_model(Path(result.recommendation_uri))

    assert result.verdict is StudyVerdict.PASS
    assert result.recommendation_status is RecommendationStatus.BLOCKED
    assert Path(result.study_uri).is_file()
    assert Path(result.champion_uri).is_file()
    assert Path(result.recommendation_uri).is_file()
    assert Path(result.latest_recommendation_uri).is_file()
    assert Path((tmp_path / "results" / "studies" / study.study_id / "folds.json")).is_file()
    assert Path((tmp_path / "results" / "studies" / study.study_id / "trials.parquet")).is_file()
    assert study.verdict is StudyVerdict.PASS
    assert recommendation.status is RecommendationStatus.BLOCKED
    publication_blockers = recommendation.summary["publication_blockers"]
    assert isinstance(publication_blockers, list)
    assert "runtime_policy_parity_pending" in publication_blockers
    assert recommendation.champion_weights["slot-a"] >= recommendation.champion_weights["slot-b"]


def test_run_portfolio_weight_study_blocks_stale_recommendations(tmp_path: Path) -> None:
    bundle_loader = FakeBundleLoader()
    study_spec = _build_study_spec().model_copy(
        update={
            "control": _build_study_spec().control.model_copy(
                update={
                    "verdict_thresholds": PortfolioWeightStudyThresholds(
                        quality_sharpe_floor=0.2,
                        min_quality_profitable_folds=1,
                        min_consecutive_quality_profitable_folds=1,
                        min_trades_per_fold=7,
                        max_recommendation_age_days=1,
                    )
                }
            )
        }
    )
    result = run_portfolio_weight_study(
        command=PortfolioWeightStudyCommand(study_spec=study_spec, requested_by="test"),
        dependencies=PortfolioWeightStudyDependencies(
            single_executor=FakeSingleExecutor(tmp_path, bundle_loader),
            portfolio_executor=FakePortfolioExecutor(),
            bundle_loader=bundle_loader,
            artifact_store=FilesystemStudyArtifactStore(results_root=tmp_path / "results"),
            clock=FakeClock(datetime(2024, 2, 10, tzinfo=timezone.utc)),
        ),
    )

    recommendation = load_live_allocation_recommendation_read_model(Path(result.recommendation_uri))

    assert result.verdict is StudyVerdict.PASS
    assert result.recommendation_status is RecommendationStatus.BLOCKED
    assert recommendation.status is RecommendationStatus.BLOCKED
