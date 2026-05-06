"""Pure weighted-spread statarb policy contracts and evaluation logic."""

from __future__ import annotations

from dataclasses import dataclass

from backtest_engine.strategies.statarb_weighted_spread.parameters import (
    StatarbWeightedSpreadParameters,
    TradeDirection,
)


@dataclass(frozen=True)
class StatarbWeightedSpreadState:
    """Immutable rolling policy state for one weighted-spread strategy instance."""

    anchor_prices: tuple[float, ...] | None = None
    spread_history: tuple[float, ...] = ()
    active_regime: int = 0


@dataclass(frozen=True)
class StatarbWeightedSpreadDecision:
    """The next immutable state plus the desired regime after one synchronized snapshot."""

    desired_regime: int
    next_state: StatarbWeightedSpreadState


def evaluate_statarb_weighted_spread(
    parameters: StatarbWeightedSpreadParameters,
    state: StatarbWeightedSpreadState,
    close_prices: tuple[float, ...],
) -> StatarbWeightedSpreadDecision:
    """Evaluate one synchronized close snapshot and return the next policy state."""

    if len(close_prices) != len(parameters.leg_symbols):
        raise ValueError("close_prices length must match leg_symbols length")
    if any(price <= 0.0 for price in close_prices):
        raise ValueError("close_prices must be positive")

    anchor_prices = state.anchor_prices or close_prices
    spread = _compute_spread(
        anchor_prices=anchor_prices,
        close_prices=close_prices,
        spread_weights=parameters.spread_weights,
    )
    spread_history = _append_spread(
        state.spread_history,
        spread=spread,
        max_length=parameters.zscore_window,
    )
    desired_regime = state.active_regime

    if len(spread_history) == parameters.zscore_window:
        zscore = _compute_zscore(spread_history, spread=spread)
        if zscore is not None:
            desired_regime = _resolve_desired_regime(
                current_regime=state.active_regime,
                zscore=zscore,
                entry_zscore=parameters.entry_zscore,
                exit_zscore=parameters.exit_zscore,
                trade_direction=parameters.trade_direction,
            )

    next_state = StatarbWeightedSpreadState(
        anchor_prices=anchor_prices,
        spread_history=spread_history,
        active_regime=desired_regime,
    )
    return StatarbWeightedSpreadDecision(
        desired_regime=desired_regime,
        next_state=next_state,
    )


def _compute_spread(
    *,
    anchor_prices: tuple[float, ...],
    close_prices: tuple[float, ...],
    spread_weights: tuple[float, ...],
) -> float:
    return float(
        sum(
            weight * (close_price / anchor_price)
            for anchor_price, close_price, weight in zip(
                anchor_prices,
                close_prices,
                spread_weights,
            )
        )
    )


def _append_spread(
    spread_history: tuple[float, ...],
    *,
    spread: float,
    max_length: int,
) -> tuple[float, ...]:
    updated = spread_history + (spread,)
    return updated[-max_length:]


def _compute_zscore(spread_history: tuple[float, ...], *, spread: float) -> float | None:
    mean = float(sum(spread_history)) / float(len(spread_history))
    variance = float(sum((value - mean) ** 2 for value in spread_history)) / float(len(spread_history))
    std = float(variance**0.5)
    if std <= 0.0:
        return None
    return float((spread - mean) / std)


def _resolve_desired_regime(
    *,
    current_regime: int,
    zscore: float,
    entry_zscore: float,
    exit_zscore: float,
    trade_direction: TradeDirection,
) -> int:
    if current_regime == 0:
        if zscore >= entry_zscore and trade_direction != "long_spread_only":
            return -1
        if zscore <= -entry_zscore and trade_direction != "short_spread_only":
            return 1
        return 0

    if abs(zscore) <= exit_zscore:
        return 0

    if current_regime > 0 and zscore >= entry_zscore:
        return 0
    if current_regime < 0 and zscore <= -entry_zscore:
        return 0
    return current_regime


__all__ = [
    "StatarbWeightedSpreadDecision",
    "StatarbWeightedSpreadState",
    "evaluate_statarb_weighted_spread",
]
