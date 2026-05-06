"""Pure channel-breakout policy contracts and evaluation logic."""

from __future__ import annotations

from dataclasses import dataclass

from backtest_engine.core.enums import OrderSide, OrderType, SignalDirection
from backtest_engine.domain.execution.orders import OrderIntent
from backtest_engine.strategies.channel_breakout_long.parameters import ChannelBreakoutLongParameters


@dataclass(frozen=True)
class ChannelBreakoutLongBar:
    """Normalized bar input consumed by the pure policy."""

    open_price: float
    high_price: float
    low_price: float
    close_price: float


@dataclass(frozen=True)
class ChannelBreakoutLongState:
    """Immutable rolling policy state for one strategy instance."""

    high_history: tuple[float, ...] = ()
    low_history: tuple[float, ...] = ()
    previous_close: float | None = None
    ema_value: float | None = None
    atr_value: float | None = None


@dataclass(frozen=True)
class ChannelBreakoutLongDecision:
    """The next immutable state plus any order intents emitted for this bar."""

    order_intents: tuple[OrderIntent, ...]
    next_state: ChannelBreakoutLongState


def evaluate_channel_breakout_long(
    parameters: ChannelBreakoutLongParameters,
    state: ChannelBreakoutLongState,
    bar: ChannelBreakoutLongBar,
    *,
    position_side: SignalDirection,
    tick_size: float,
) -> ChannelBreakoutLongDecision:
    """Evaluate one completed bar and return the next policy state."""

    if tick_size <= 0.0:
        raise ValueError("tick_size must be positive")

    ema_value = _update_ema(
        current_ema=state.ema_value,
        ema_period=parameters.ema_period,
        close_price=bar.close_price,
    )
    atr_value = _update_atr(
        previous_close=state.previous_close,
        current_atr=state.atr_value,
        atr_window=parameters.shock_atr_window,
        high_price=bar.high_price,
        low_price=bar.low_price,
        close_price=bar.close_price,
    )
    next_state = ChannelBreakoutLongState(
        high_history=_append_value(state.high_history, bar.high_price, max_length=parameters.length),
        low_history=_append_value(state.low_history, bar.low_price, max_length=parameters.length),
        previous_close=bar.close_price,
        ema_value=ema_value,
        atr_value=atr_value,
    )

    buffer_price = tick_size * float(parameters.entry_buffer_ticks)
    long_stop = _build_long_stop(state.high_history, buffer_price=buffer_price, length=parameters.length)
    short_stop = _build_short_stop(state.low_history, buffer_price=buffer_price, length=parameters.length)

    if position_side is SignalDirection.LONG and short_stop is not None:
        return ChannelBreakoutLongDecision(
            order_intents=(_build_stop_order(parameters, OrderSide.SELL, short_stop),),
            next_state=next_state,
        )
    if position_side is SignalDirection.SHORT and long_stop is not None:
        return ChannelBreakoutLongDecision(
            order_intents=(_build_stop_order(parameters, OrderSide.BUY, long_stop),),
            next_state=next_state,
        )

    if position_side is not SignalDirection.FLAT:
        return ChannelBreakoutLongDecision(order_intents=(), next_state=next_state)

    shock_allowed = _shock_filter_allows_entry(parameters=parameters, state=state, bar=bar)
    long_raw = long_stop is not None and bar.close_price > ema_value and shock_allowed
    short_raw = short_stop is not None and bar.close_price < ema_value and shock_allowed
    long_ok, short_ok = _gate_trade_direction(parameters.trade_direction, long_raw=long_raw, short_raw=short_raw)

    if long_ok and long_stop is not None:
        return ChannelBreakoutLongDecision(
            order_intents=(_build_stop_order(parameters, OrderSide.BUY, long_stop),),
            next_state=next_state,
        )
    if short_ok and short_stop is not None:
        return ChannelBreakoutLongDecision(
            order_intents=(_build_stop_order(parameters, OrderSide.SELL, short_stop),),
            next_state=next_state,
        )
    return ChannelBreakoutLongDecision(order_intents=(), next_state=next_state)


def _append_value(values: tuple[float, ...], value: float, max_length: int) -> tuple[float, ...]:
    updated = values + (value,)
    return updated[-max_length:]


def _update_ema(*, current_ema: float | None, ema_period: int, close_price: float) -> float:
    if current_ema is None:
        return float(close_price)
    alpha = 2.0 / (float(ema_period) + 1.0)
    return (alpha * float(close_price)) + ((1.0 - alpha) * float(current_ema))


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


def _build_long_stop(
    high_history: tuple[float, ...],
    *,
    buffer_price: float,
    length: int,
) -> float | None:
    if len(high_history) < length:
        return None
    return float(max(high_history)) + buffer_price


def _build_short_stop(
    low_history: tuple[float, ...],
    *,
    buffer_price: float,
    length: int,
) -> float | None:
    if len(low_history) < length:
        return None
    return float(min(low_history)) - buffer_price


def _shock_filter_allows_entry(
    *,
    parameters: ChannelBreakoutLongParameters,
    state: ChannelBreakoutLongState,
    bar: ChannelBreakoutLongBar,
) -> bool:
    if not parameters.use_shock_filter:
        return True
    if state.previous_close is None or state.atr_value is None or state.atr_value <= 0.0:
        return True

    atr_reference = float(state.atr_value)
    gap_atr = abs(bar.open_price - state.previous_close) / atr_reference
    range_atr = abs(bar.high_price - bar.low_price) / atr_reference
    close_change_atr = abs(bar.close_price - state.previous_close) / atr_reference
    return (
        gap_atr <= parameters.shock_max_gap_atr
        and range_atr <= parameters.shock_max_range_atr
        and close_change_atr <= parameters.shock_max_close_change_atr
    )


def _gate_trade_direction(
    trade_direction: str,
    *,
    long_raw: bool,
    short_raw: bool,
) -> tuple[bool, bool]:
    if trade_direction == "long":
        return long_raw, False
    if trade_direction == "short":
        return False, short_raw
    return long_raw, short_raw


def _build_stop_order(
    parameters: ChannelBreakoutLongParameters,
    side: OrderSide,
    stop_price: float,
) -> OrderIntent:
    return OrderIntent(
        strategy_id=parameters.strategy_id,
        symbol=parameters.symbol,
        side=side,
        order_type=OrderType.STOP,
        quantity=parameters.trade_size,
        stop_price=stop_price,
    )


__all__ = [
    "ChannelBreakoutLongBar",
    "ChannelBreakoutLongDecision",
    "ChannelBreakoutLongState",
    "evaluate_channel_breakout_long",
]
