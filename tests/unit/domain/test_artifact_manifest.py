from __future__ import annotations

from decimal import Decimal
import pytest

from backtest_engine.core.enums import RuntimeBoundary
from backtest_engine.core.money import Money
from backtest_engine.domain.artifacts.manifests import ArtifactManifest


def test_artifact_manifest_rejects_divergent_config_hash() -> None:
    with pytest.raises(ValueError):
        ArtifactManifest(
            run_id="run_manifest_test",
            run_spec_hash="abc123def456",
            runtime_boundary=RuntimeBoundary.NAUTILUS,
            dataset_id="dataset-es-30m",
            config_hash="different654321",
            symbol_universe=("ES",),
            strategy_ids=("sma_pullback",),
            capital_base=Money(amount=Decimal("100000"), currency="USD"),
            semantic_policy_version="v1",
        )
