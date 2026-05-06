from __future__ import annotations

from decimal import Decimal
from datetime import datetime, timezone

import pytest

from backtest_engine.config.execution_costs import DEFAULT_EXECUTION_COST_PROFILE_ID
from backtest_engine.config.runtime import (
    BacktestExecutionPolicy,
    BacktestRunSpec,
    ExecutionCostProfileRef,
    ExecutionVenueOverrides,
    ExecutionWindow,
)
from backtest_engine.core.enums import DatasetSource, RunKind
from backtest_engine.core.money import Money
from backtest_engine.domain.market.datasets import DatasetSpec
from backtest_engine.domain.strategy.specifications import (
    PortfolioStrategySpec,
    StrategyLegSpec,
    StrategySpec,
)


def _build_strategy(
    slot_id: str,
    strategy_id: str,
    weight_frac: float,
    *,
    legs: tuple[str, ...] = ("ES",),
) -> PortfolioStrategySpec:
    return PortfolioStrategySpec(
        slot_id=slot_id,
        weight_frac=weight_frac,
        strategy=StrategySpec(
            strategy_id=strategy_id,
            implementation_id="sma_pullback",
            policy_version="v1",
        ),
        legs=tuple(StrategyLegSpec(symbol=symbol) for symbol in legs),
    )


def _build_dataset() -> DatasetSpec:
    return DatasetSpec(
        source_system=DatasetSource.PARQUET,
        normalization_policy="nautilus_v1",
        schema_version="1",
        symbol_universe=("ES",),
        timeframe="30m",
        dataset_version="2026-04-03",
    )


def test_backtest_run_spec_hash_is_deterministic() -> None:
    run_spec_one = BacktestRunSpec(
        run_kind=RunKind.SINGLE,
        execution_window=ExecutionWindow(
            start_utc=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end_utc=datetime(2024, 2, 1, tzinfo=timezone.utc),
        ),
        dataset=_build_dataset(),
        strategies=(_build_strategy("slot-1", "sma_pullback", 1.0),),
        capital_base=Money(amount=Decimal("100000"), currency="USD"),
    )
    run_spec_two = BacktestRunSpec.model_validate(
        run_spec_one.model_dump(exclude_computed_fields=True),
    )

    assert run_spec_one.content_hash == run_spec_two.content_hash
    assert run_spec_one.run_id == run_spec_two.run_id


def test_valid_execution_policy_serializes_stably() -> None:
    policy = BacktestExecutionPolicy(
        execution_costs=ExecutionCostProfileRef(
            profile_id=DEFAULT_EXECUTION_COST_PROFILE_ID,
        ),
        venue_overrides=ExecutionVenueOverrides(
            oms_type="HEDGING",
            account_type="MARGIN",
            book_type="L1_MBP",
        ),
    )

    assert policy.model_dump(mode="json") == {
        "execution_costs": {
            "profile_id": DEFAULT_EXECUTION_COST_PROFILE_ID,
            "config_content_hash": None,
        },
        "venue_overrides": {
            "oms_type": "HEDGING",
            "account_type": "MARGIN",
            "book_type": "L1_MBP",
        },
    }


def test_execution_policy_rejects_unsupported_execution_cost_profile_id() -> None:
    with pytest.raises(ValueError, match="unsupported execution-cost profile_id"):
        ExecutionCostProfileRef(profile_id="experimental_costs")


def test_execution_policy_rejects_invalid_execution_cost_config_hash() -> None:
    with pytest.raises(ValueError, match="config_content_hash"):
        ExecutionCostProfileRef(
            profile_id=DEFAULT_EXECUTION_COST_PROFILE_ID,
            config_content_hash="not-a-sha",
        )


def test_execution_policy_rejects_empty_venue_overrides() -> None:
    with pytest.raises(ValueError, match="venue_overrides must set at least one override"):
        BacktestExecutionPolicy.model_validate(
            {
                "execution_costs": {"profile_id": DEFAULT_EXECUTION_COST_PROFILE_ID},
                "venue_overrides": {},
            },
        )


def test_execution_policy_allows_absent_null_and_partial_venue_overrides() -> None:
    absent_overrides = BacktestExecutionPolicy.model_validate(
        {"execution_costs": {"profile_id": DEFAULT_EXECUTION_COST_PROFILE_ID}},
    )
    null_overrides = BacktestExecutionPolicy.model_validate(
        {
            "execution_costs": {"profile_id": DEFAULT_EXECUTION_COST_PROFILE_ID},
            "venue_overrides": None,
        },
    )
    partial_overrides = BacktestExecutionPolicy.model_validate(
        {
            "execution_costs": {"profile_id": DEFAULT_EXECUTION_COST_PROFILE_ID},
            "venue_overrides": {"oms_type": "NETTING"},
        },
    )

    assert absent_overrides.venue_overrides is None
    assert null_overrides.venue_overrides is None
    assert partial_overrides.venue_overrides is not None
    assert partial_overrides.venue_overrides.oms_type == "NETTING"
    assert partial_overrides.venue_overrides.account_type is None
    assert partial_overrides.venue_overrides.book_type is None


def test_absent_and_explicit_none_execution_policy_hash_identically() -> None:
    implicit_legacy_spec = _build_single_run_spec()
    explicit_legacy_spec = _build_single_run_spec(execution_policy=None)

    assert implicit_legacy_spec.content_hash == explicit_legacy_spec.content_hash
    assert implicit_legacy_spec.run_id == explicit_legacy_spec.run_id


def test_no_policy_run_spec_keeps_legacy_content_hash() -> None:
    run_spec = _build_single_run_spec()

    assert (
        run_spec.content_hash == "810fa61e714de9d29bda514b625924e1275f85f35dbe2c472b8e46c55496f9bf"
    )
    assert run_spec.run_id == "run-810fa61e714d"


def test_non_none_execution_policy_changes_hash_and_run_id() -> None:
    legacy_spec = _build_single_run_spec()
    policy_spec = _build_single_run_spec(
        execution_policy=BacktestExecutionPolicy(
            execution_costs=ExecutionCostProfileRef(
                profile_id=DEFAULT_EXECUTION_COST_PROFILE_ID,
            ),
            venue_overrides=ExecutionVenueOverrides(book_type="L2_MBP"),
        ),
    )

    assert policy_spec.execution_policy is not None
    assert policy_spec.content_hash != legacy_spec.content_hash
    assert policy_spec.run_id != legacy_spec.run_id


def test_execution_cost_config_hash_participates_in_run_identity() -> None:
    spec_one = _build_single_run_spec(
        execution_policy=BacktestExecutionPolicy(
            execution_costs=ExecutionCostProfileRef(
                profile_id=DEFAULT_EXECUTION_COST_PROFILE_ID,
                config_content_hash="1" * 64,
            ),
        ),
    )
    spec_two = _build_single_run_spec(
        execution_policy=BacktestExecutionPolicy(
            execution_costs=ExecutionCostProfileRef(
                profile_id=DEFAULT_EXECUTION_COST_PROFILE_ID,
                config_content_hash="2" * 64,
            ),
        ),
    )

    assert spec_one.content_hash != spec_two.content_hash
    assert spec_one.run_id != spec_two.run_id


def test_single_run_spec_requires_exactly_one_strategy() -> None:
    with pytest.raises(ValueError, match="exactly one strategy"):
        BacktestRunSpec(
            run_kind=RunKind.SINGLE,
            execution_window=ExecutionWindow(
                start_utc=datetime(2024, 1, 1, tzinfo=timezone.utc),
                end_utc=datetime(2024, 2, 1, tzinfo=timezone.utc),
            ),
            dataset=_build_dataset(),
            strategies=(
                _build_strategy("slot-1", "sma_pullback", 0.5),
                _build_strategy("slot-2", "breakout", 0.5),
            ),
            capital_base=Money(amount=Decimal("100000"), currency="USD"),
        )


def _build_single_run_spec(
    *,
    execution_policy: BacktestExecutionPolicy | None = None,
) -> BacktestRunSpec:
    return BacktestRunSpec(
        run_kind=RunKind.SINGLE,
        execution_window=ExecutionWindow(
            start_utc=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end_utc=datetime(2024, 2, 1, tzinfo=timezone.utc),
        ),
        dataset=_build_dataset(),
        strategies=(_build_strategy("slot-1", "sma_pullback", 1.0),),
        capital_base=Money(amount=Decimal("100000"), currency="USD"),
        execution_policy=execution_policy,
    )


def test_single_run_spec_allows_one_multi_leg_strategy_slot() -> None:
    run_spec = BacktestRunSpec(
        run_kind=RunKind.SINGLE,
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
        strategies=(_build_strategy("slot-1", "spread", 1.0, legs=("ES", "NQ")),),
        capital_base=Money(amount=Decimal("100000"), currency="USD"),
    )

    assert tuple(leg.symbol for leg in run_spec.strategies[0].legs) == ("ES", "NQ")


def test_portfolio_strategy_spec_requires_at_least_one_leg() -> None:
    with pytest.raises(ValueError, match="at least one leg"):
        PortfolioStrategySpec(
            slot_id="slot-1",
            weight_frac=1.0,
            strategy=StrategySpec(
                strategy_id="sma_pullback",
                implementation_id="sma_pullback",
                policy_version="v1",
            ),
            legs=(),
        )


def test_portfolio_strategy_spec_rejects_duplicate_leg_symbols() -> None:
    with pytest.raises(ValueError, match="must not repeat symbols"):
        _build_strategy("slot-1", "spread", 1.0, legs=("ES", "ES"))


def test_backtest_run_spec_rejects_legs_outside_dataset_symbol_universe() -> None:
    with pytest.raises(ValueError, match="dataset symbol_universe"):
        BacktestRunSpec(
            run_kind=RunKind.PORTFOLIO,
            execution_window=ExecutionWindow(
                start_utc=datetime(2024, 1, 1, tzinfo=timezone.utc),
                end_utc=datetime(2024, 2, 1, tzinfo=timezone.utc),
            ),
            dataset=_build_dataset(),
            strategies=(_build_strategy("slot-1", "spread", 1.0, legs=("ES", "NQ")),),
            capital_base=Money(amount=Decimal("100000"), currency="USD"),
        )
