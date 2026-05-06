from __future__ import annotations

from decimal import Decimal
from datetime import datetime, timezone
from pathlib import Path

from backtest_engine.analytics.read_models import BundleReadModel
from backtest_engine.core.enums import RunKind, RuntimeBoundary
from backtest_engine.core.money import Money
from backtest_engine.interfaces.terminal_ui.read_bundle_summary import (
    BundleSummaryRequest,
    read_bundle_summary,
)


class FakeBundleSummaryService:
    def __init__(self) -> None:
        self.paths: list[Path] = []

    def load_bundle_read_model(self, bundle_path: Path) -> BundleReadModel:
        self.paths.append(bundle_path)
        return BundleReadModel(
            bundle_id="bundle-terminal-test",
            run_id="run_terminal_test",
            dataset_id="dataset-es-30m",
            run_kind=RunKind.SINGLE,
            runtime_boundary=RuntimeBoundary.NAUTILUS,
            strategy_ids=("sma_pullback",),
            symbol_universe=("ES",),
            capital_base=Money(amount=Decimal("100000"), currency="USD"),
            semantic_policy_version="v1",
            created_at_utc=datetime(2026, 4, 3, tzinfo=timezone.utc),
            metric_values={"net_profit": 325.0},
            artifact_locations={"runtime_root": "var/runtime/nautilus/run_terminal_test"},
        )


def test_read_bundle_summary_delegates_to_the_bundle_service() -> None:
    service = FakeBundleSummaryService()
    command = BundleSummaryRequest(bundle_path=Path("results/bundle-terminal-test.json"))

    result = read_bundle_summary(command=command, service=service)

    assert service.paths == [command.bundle_path]
    assert result.bundle_id == "bundle-terminal-test"
    assert result.metric_values == {"net_profit": 325.0}
