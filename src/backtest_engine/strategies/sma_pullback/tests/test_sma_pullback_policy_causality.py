# mypy: disable-error-code=no-untyped-def
from __future__ import annotations

from backtest_engine.core.enums import OrderSide, SignalDirection
from backtest_engine.strategies.sma_pullback.parameters import SmaPullbackParameters
from backtest_engine.strategies.sma_pullback.policy import (
    SmaPullbackBar,
    SmaPullbackPosition,
    SmaPullbackState,
    evaluate_sma_pullback,
)


def _build_parameters() -> SmaPullbackParameters:
    return SmaPullbackParameters(
        strategy_id="sma-es",
        symbol="ES",
        trade_size=1.0,
        fast_sma_window=2,
        slow_sma_window=3,
        atr_window=2,
        atr_sl_mult=2.0,
        rr_ratio=3.0,
        trade_direction="long",
    )


def test_completed_bar_entry_uses_current_ohlc_as_intrabar_assumption() -> None:
    """Characterize current completed-bar behavior; this is not tick-level realism."""

    decision = evaluate_sma_pullback(
        parameters=_build_parameters(),
        state=SmaPullbackState(
            close_history=(10.0, 12.0),
            previous_close=12.0,
            atr_value=1.0,
            position=None,
        ),
        bar=SmaPullbackBar(
            open_price=13.0,
            high_price=16.5,
            low_price=15.5,
            close_price=20.0,
        ),
    )

    [intent] = decision.order_intents
    assert intent.side is OrderSide.BUY
    assert decision.next_state.close_history == (10.0, 12.0, 20.0)
    assert decision.next_state.position is not None
    assert decision.next_state.position.side is SignalDirection.LONG


def test_completed_bar_exit_uses_current_high_low_as_intrabar_assumption() -> None:
    """A same-bar high/low threshold hit is characterized, not claimed realistic."""

    decision = evaluate_sma_pullback(
        parameters=_build_parameters(),
        state=SmaPullbackState(
            close_history=(100.0, 101.0, 102.0),
            previous_close=102.0,
            atr_value=1.0,
            position=SmaPullbackPosition(
                side=SignalDirection.LONG,
                stop_loss=95.0,
                take_profit=110.0,
            ),
        ),
        bar=SmaPullbackBar(
            open_price=103.0,
            high_price=111.0,
            low_price=99.0,
            close_price=100.0,
        ),
    )

    [intent] = decision.order_intents
    assert intent.side is OrderSide.SELL
    assert decision.next_state.position is None
