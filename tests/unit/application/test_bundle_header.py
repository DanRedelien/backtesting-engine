from __future__ import annotations

from decimal import Decimal
from datetime import datetime, timezone

from backtest_engine.application._bundle_header import build_bundle_header_from_run_spec
from backtest_engine.config.runtime import BacktestRunSpec, ExecutionWindow
from backtest_engine.core.enums import DatasetSource, RunKind
from backtest_engine.core.money import Money
from backtest_engine.domain.market.datasets import DatasetSpec
from backtest_engine.domain.strategy.specifications import (
    PortfolioStrategySpec,
    StrategyLegSpec,
    StrategySpec,
)


def _build_run_spec() -> BacktestRunSpec:
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


def test_build_bundle_header_from_run_spec_builds_shared_manifest_and_provenance() -> None:
    run_spec = _build_run_spec()
    created_at_utc = datetime(2026, 4, 3, tzinfo=timezone.utc)

    header = build_bundle_header_from_run_spec(run_spec=run_spec, created_at_utc=created_at_utc)

    assert header.manifest.run_id == run_spec.run_id
    assert header.manifest.run_spec_hash == run_spec.content_hash
    assert header.manifest.config_hash == run_spec.content_hash
    assert header.provenance.run_spec_hash == run_spec.content_hash
    assert header.provenance.created_at_utc == created_at_utc
