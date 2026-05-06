"""Pure SMA pullback policy contracts and evaluation logic."""

from __future__ import annotations

from dataclasses import dataclass

from backtest_engine.core.enums import OrderSide, OrderType, SignalDirection
from backtest_engine.domain.execution.orders import OrderIntent
from backtest_engine.strategies.sma_pullback.parameters import SmaPullbackParameters


@dataclass(frozen=True)
class SmaPullbackBar:
    """Normalized bar input consumed by the pure policy."""

    open_price: float
    high_price: float
    low_price: float
    close_price: float


@dataclass(frozen=True)
class SmaPullbackPosition:
    """One open position tracked by the pure policy."""

    side: SignalDirection
    stop_loss: float
    take_profit: float


@dataclass(frozen=True)
class SmaPullbackState:
    """Immutable rolling policy state for one strategy instance."""

    close_history: tuple[float, ...] = ()
    previous_close: float | None = None
    atr_value: float | None = None
    position: SmaPullbackPosition | None = None


@dataclass(frozen=True)
class SmaPullbackDecision:
    """The next immutable state plus any order intents emitted for this bar."""

    order_intents: tuple[OrderIntent, ...]
    next_state: SmaPullbackState


def evaluate_sma_pullback(
    parameters: SmaPullbackParameters,
    state: SmaPullbackState,
    bar: SmaPullbackBar,
) -> SmaPullbackDecision:
    """Evaluate one completed bar and return the next policy state."""

    atr_value = _update_atr(
        previous_close=state.previous_close,
        current_atr=state.atr_value,
        atr_window=parameters.atr_window,
        high_price=bar.high_price,
        low_price=bar.low_price,
        close_price=bar.close_price,
    )
    close_history = _append_close(
        history=state.close_history,
        close_price=bar.close_price,
        max_length=parameters.slow_sma_window,
    )
    base_state = SmaPullbackState(
        close_history=close_history,
        previous_close=bar.close_price,
        atr_value=atr_value,
        position=state.position,
    )

    exit_intent = _build_exit_intent(
        parameters=parameters,
        position=state.position,
        bar=bar,
    )
    if exit_intent is not None:
        return SmaPullbackDecision(
            order_intents=(exit_intent,),
            next_state=SmaPullbackState(
                close_history=close_history,
                previous_close=bar.close_price,
                atr_value=atr_value,
                position=None,
            ),
        )

    if len(close_history) < parameters.slow_sma_window or atr_value is None:
        return SmaPullbackDecision(order_intents=(), next_state=base_state)
    if state.position is not None:
        return SmaPullbackDecision(order_intents=(), next_state=base_state)

    signal = _resolve_entry_signal(
        parameters=parameters,
        close_history=close_history,
        bar=bar,
    )
    if signal is None:
        return SmaPullbackDecision(order_intents=(), next_state=base_state)

    sl_distance = atr_value * parameters.atr_sl_mult
    if signal is SignalDirection.LONG:
        position = SmaPullbackPosition(
            side=SignalDirection.LONG,
            stop_loss=bar.close_price - sl_distance,
            take_profit=bar.close_price + (sl_distance * parameters.rr_ratio),
        )
        order_intent = _build_order_intent(parameters, OrderSide.BUY)
    else:
        position = SmaPullbackPosition(
            side=SignalDirection.SHORT,
            stop_loss=bar.close_price + sl_distance,
            take_profit=bar.close_price - (sl_distance * parameters.rr_ratio),
        )
        order_intent = _build_order_intent(parameters, OrderSide.SELL)

    return SmaPullbackDecision(
        order_intents=(order_intent,),
        next_state=SmaPullbackState(
            close_history=close_history,
            previous_close=bar.close_price,
            atr_value=atr_value,
            position=position,
        ),
    )


def _append_close(history: tuple[float, ...], close_price: float, max_length: int) -> tuple[float, ...]:
    updated = history + (close_price,)
    return updated[-max_length:]


def _update_atr(
    *,
    previous_close: float | None,
    current_atr: float | None,
    atr_window: int,
    high_price: float,
    low_price: float,
    close_price: float,
) -> float:
    true_range = high_price - low_price
    if previous_close is not None:
        true_range = max(
            high_price - low_price,
            abs(high_price - previous_close),
            abs(low_price - previous_close),
        )
    if current_atr is None:
        return float(true_range)
    alpha = 2.0 / (float(atr_window) + 1.0)
    return (alpha * float(true_range)) + ((1.0 - alpha) * float(current_atr))


def _build_exit_intent(
    *,
    parameters: SmaPullbackParameters,
    position: SmaPullbackPosition | None,
    bar: SmaPullbackBar,
) -> OrderIntent | None:
    if position is None:
        return None
    if position.side is SignalDirection.LONG:
        if bar.low_price <= position.stop_loss or bar.high_price >= position.take_profit:
            return _build_order_intent(parameters, OrderSide.SELL)
        return None
    if bar.high_price >= position.stop_loss or bar.low_price <= position.take_profit:
        return _build_order_intent(parameters, OrderSide.BUY)
    return None


def _resolve_entry_signal(
    *,
    parameters: SmaPullbackParameters,
    close_history: tuple[float, ...],
    bar: SmaPullbackBar,
) -> SignalDirection | None:
    fast_sma = _window_mean(close_history, parameters.fast_sma_window)
    slow_sma = _window_mean(close_history, parameters.slow_sma_window)
    touches_fast_sma = bar.low_price <= fast_sma <= bar.high_price
    if not touches_fast_sma:
        return None
    if bar.close_price > slow_sma and parameters.trade_direction != "short":
        return SignalDirection.LONG
    if bar.close_price < slow_sma and parameters.trade_direction != "long":
        return SignalDirection.SHORT
    return None


def _window_mean(values: tuple[float, ...], window: int) -> float:
    window_values = values[-window:]
    return float(sum(window_values)) / float(window)


def _build_order_intent(
    parameters: SmaPullbackParameters,
    side: OrderSide,
) -> OrderIntent:
    return OrderIntent(
        strategy_id=parameters.strategy_id,
        symbol=parameters.symbol,
        side=side,
        order_type=OrderType.MARKET,
        quantity=parameters.trade_size,
    )


__all__ = [
    "SmaPullbackBar",
    "SmaPullbackDecision",
    "SmaPullbackPosition",
    "SmaPullbackState",
    "evaluate_sma_pullback",
]
