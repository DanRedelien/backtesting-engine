# mypy: disable-error-code=no-untyped-def
from __future__ import annotations

import pytest

from backtest_engine.strategies.statarb_weighted_spread.parameters import (
    StatarbWeightedSpreadParameters,
)
from backtest_engine.strategies.statarb_weighted_spread.policy import (
    StatarbWeightedSpreadDecision,
    StatarbWeightedSpreadState,
    evaluate_statarb_weighted_spread,
)


def _build_parameters(
    *,
    leg_symbols: tuple[str, ...] = ("ES", "NQ"),
    trade_sizes: tuple[float, ...] = (1.0, 1.0),
    spread_weights: tuple[float, ...] = (1.0, -1.0),
    zscore_window: int = 3,
    entry_zscore: float = 1.0,
    exit_zscore: float = 0.2,
    trade_direction: str = "both",
) -> StatarbWeightedSpreadParameters:
    return StatarbWeightedSpreadParameters(
        strategy_id="statarb-es-nq",
        leg_symbols=leg_symbols,
        trade_sizes=trade_sizes,
        spread_weights=spread_weights,
        zscore_window=zscore_window,
        entry_zscore=entry_zscore,
        exit_zscore=exit_zscore,
        trade_direction=trade_direction,
    )


def _evaluate_snapshots(
    parameters: StatarbWeightedSpreadParameters,
    state: StatarbWeightedSpreadState,
    snapshots: tuple[tuple[float, ...], ...],
) -> tuple[StatarbWeightedSpreadDecision, StatarbWeightedSpreadState]:
    if not snapshots:
        raise AssertionError("snapshots must not be empty")

    decision = evaluate_statarb_weighted_spread(parameters, state, snapshots[0])
    state = decision.next_state
    for snapshot in snapshots[1:]:
        decision = evaluate_statarb_weighted_spread(parameters, state, snapshot)
        state = decision.next_state
    return decision, state


def test_parameters_reject_invalid_shapes() -> None:
    with pytest.raises(ValueError, match="at least two legs"):
        _build_parameters(leg_symbols=("ES",), trade_sizes=(1.0,), spread_weights=(1.0,))
    with pytest.raises(ValueError, match="trade_sizes length"):
        _build_parameters(trade_sizes=(1.0,))
    with pytest.raises(ValueError, match="spread_weights length"):
        _build_parameters(spread_weights=(1.0,))
    with pytest.raises(ValueError, match="must be positive"):
        _build_parameters(trade_sizes=(1.0, 0.0))
    with pytest.raises(ValueError, match="must be less than entry_zscore"):
        _build_parameters(exit_zscore=1.0)
    with pytest.raises(ValueError, match="must not all be zero"):
        _build_parameters(spread_weights=(0.0, 0.0))


def test_evaluator_requires_sufficient_history() -> None:
    parameters = _build_parameters(zscore_window=4)
    decision, state = _evaluate_snapshots(
        parameters,
        StatarbWeightedSpreadState(),
        ((100.0, 100.0), (101.0, 100.0), (102.0, 100.0)),
    )

    assert decision.desired_regime == 0
    assert state.active_regime == 0


def test_evaluator_returns_flat_when_spread_std_is_zero() -> None:
    parameters = _build_parameters()
    decision, state = _evaluate_snapshots(
        parameters,
        StatarbWeightedSpreadState(),
        ((100.0, 100.0), (100.0, 100.0), (100.0, 100.0)),
    )

    assert decision.desired_regime == 0
    assert state.active_regime == 0


def test_evaluator_enters_short_spread_on_positive_zscore() -> None:
    parameters = _build_parameters()
    decision, state = _evaluate_snapshots(
        parameters,
        StatarbWeightedSpreadState(),
        ((100.0, 100.0), (101.0, 100.0), (102.0, 100.0)),
    )

    assert decision.desired_regime == -1
    assert state.active_regime == -1


def test_evaluator_enters_long_spread_on_negative_zscore() -> None:
    parameters = _build_parameters()
    decision, state = _evaluate_snapshots(
        parameters,
        StatarbWeightedSpreadState(),
        ((100.0, 100.0), (99.0, 100.0), (98.0, 100.0)),
    )

    assert decision.desired_regime == 1
    assert state.active_regime == 1


def test_evaluator_flattens_on_exit_threshold() -> None:
    parameters = _build_parameters(exit_zscore=0.8)
    _, state = _evaluate_snapshots(
        parameters,
        StatarbWeightedSpreadState(),
        ((100.0, 100.0), (101.0, 100.0), (102.0, 100.0)),
    )

    assert state.active_regime == -1

    decision = evaluate_statarb_weighted_spread(parameters, state, (101.0, 100.0))
    state = decision.next_state

    assert decision.desired_regime == 0
    assert state.active_regime == 0


def test_evaluator_flattens_before_opposite_regime_entry() -> None:
    parameters = _build_parameters()
    _, state = _evaluate_snapshots(
        parameters,
        StatarbWeightedSpreadState(),
        ((100.0, 100.0), (101.0, 100.0), (102.0, 100.0)),
    )

    assert state.active_regime == -1

    decision = evaluate_statarb_weighted_spread(parameters, state, (99.0, 100.0))
    state = decision.next_state
    assert decision.desired_regime == 0
    assert state.active_regime == 0

    decision = evaluate_statarb_weighted_spread(parameters, state, (97.0, 100.0))
    assert decision.desired_regime == 1


def test_evaluator_respects_long_spread_only_gating() -> None:
    parameters = _build_parameters(trade_direction="long_spread_only")
    decision, state = _evaluate_snapshots(
        parameters,
        StatarbWeightedSpreadState(),
        ((100.0, 100.0), (101.0, 100.0), (102.0, 100.0)),
    )

    assert decision.desired_regime == 0

    decision = evaluate_statarb_weighted_spread(parameters, state, (99.0, 100.0))
    assert decision.desired_regime == 1


def test_evaluator_respects_short_spread_only_gating() -> None:
    parameters = _build_parameters(trade_direction="short_spread_only")
    decision, state = _evaluate_snapshots(
        parameters,
        StatarbWeightedSpreadState(),
        ((100.0, 100.0), (99.0, 100.0), (98.0, 100.0)),
    )

    assert decision.desired_regime == 0

    decision = evaluate_statarb_weighted_spread(parameters, state, (101.0, 100.0))
    assert decision.desired_regime == -1


def test_evaluator_supports_internal_n_leg_math_without_extra_branching() -> None:
    parameters = _build_parameters(
        leg_symbols=("ES", "NQ", "YM"),
        trade_sizes=(1.0, 1.0, 1.0),
        spread_weights=(1.0, -0.5, -0.5),
    )
    decision, _ = _evaluate_snapshots(
        parameters,
        StatarbWeightedSpreadState(),
        (
            (100.0, 100.0, 100.0),
            (101.0, 100.0, 100.0),
            (102.0, 100.0, 100.0),
        ),
    )

    assert decision.desired_regime == -1


def test_evaluator_decisions_are_immutable_and_require_new_snapshot_evaluation() -> None:
    parameters = _build_parameters()
    _, state = _evaluate_snapshots(
        parameters,
        StatarbWeightedSpreadState(),
        ((100.0, 100.0), (101.0, 100.0)),
    )

    entry_decision = evaluate_statarb_weighted_spread(parameters, state, (102.0, 100.0))
    entry_state = entry_decision.next_state

    future_decision = evaluate_statarb_weighted_spread(parameters, entry_state, (99.0, 100.0))

    assert entry_decision.desired_regime == -1
    assert entry_decision.next_state == entry_state
    assert entry_state.active_regime == -1
    assert future_decision.desired_regime == 0
    assert future_decision.next_state is not entry_state
