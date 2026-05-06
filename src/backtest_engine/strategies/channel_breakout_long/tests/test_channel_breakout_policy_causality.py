# mypy: disable-error-code=no-untyped-def
from __future__ import annotations

from decimal import Decimal

from backtest_engine.core.enums import OrderSide, SignalDirection
from backtest_engine.strategies.channel_breakout_long.parameters import (
    ChannelBreakoutLongParameters,
)
from backtest_engine.strategies.channel_breakout_long.policy import (
    ChannelBreakoutLongBar,
    ChannelBreakoutLongState,
    evaluate_channel_breakout_long,
)


def _build_parameters() -> ChannelBreakoutLongParameters:
    return ChannelBreakoutLongParameters(
        strategy_id="channel-es",
        symbol="ES",
        trade_size=1.0,
        length=3,
        ema_period=3,
        entry_buffer_ticks=2,
        trade_direction="both",
        use_shock_filter=False,
    )


def test_breakout_long_stop_uses_prior_high_history_not_current_bar_high() -> None:
    parameters = _build_parameters()
    state = ChannelBreakoutLongState(
        high_history=(100.0, 101.0, 102.0),
        low_history=(97.0, 98.0, 99.0),
        previous_close=101.0,
        ema_value=100.0,
        atr_value=1.0,
    )

    decision = evaluate_channel_breakout_long(
        parameters=parameters,
        state=state,
        bar=ChannelBreakoutLongBar(
            open_price=103.0,
            high_price=999.0,
            low_price=102.0,
            close_price=110.0,
        ),
        position_side=SignalDirection.FLAT,
        tick_size=0.25,
    )

    [intent] = decision.order_intents
    assert intent.side is OrderSide.BUY
    assert intent.stop_price == Decimal("102.5")
    assert decision.next_state.high_history == (101.0, 102.0, 999.0)


def test_breakout_short_stop_uses_prior_low_history_not_current_bar_low() -> None:
    parameters = _build_parameters()
    state = ChannelBreakoutLongState(
        high_history=(101.0, 102.0, 103.0),
        low_history=(100.0, 99.0, 98.0),
        previous_close=99.0,
        ema_value=100.0,
        atr_value=1.0,
    )

    decision = evaluate_channel_breakout_long(
        parameters=parameters,
        state=state,
        bar=ChannelBreakoutLongBar(
            open_price=97.0,
            high_price=98.0,
            low_price=1.0,
            close_price=90.0,
        ),
        position_side=SignalDirection.FLAT,
        tick_size=0.25,
    )

    [intent] = decision.order_intents
    assert intent.side is OrderSide.SELL
    assert intent.stop_price == Decimal("97.5")
    assert decision.next_state.low_history == (99.0, 98.0, 1.0)
