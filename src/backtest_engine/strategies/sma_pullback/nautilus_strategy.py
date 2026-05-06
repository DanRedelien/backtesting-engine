"""Nautilus wrapper for the SMA pullback strategy cartridge."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from nautilus_trader.config import PositiveFloat, PositiveInt, StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.model.objects import Quantity
from nautilus_trader.trading.strategy import Strategy

from backtest_engine.core.enums import OrderSide as DomainOrderSide
from backtest_engine.strategies.sma_pullback.parameters import SmaPullbackParameters
from backtest_engine.strategies.sma_pullback.policy import (
    SmaPullbackBar,
    SmaPullbackState,
    evaluate_sma_pullback,
)


class SmaPullbackStrategyConfig(StrategyConfig, kw_only=True, frozen=True):
    """Configuration for the SMA pullback Nautilus wrapper."""

    instrument_id: str
    bar_type: str
    symbol: str
    strategy_id: str = ""
    unit_trade_size: PositiveFloat = 1.0
    slot_multiplier: float = 1.0
    fast_sma_window: PositiveInt = 50
    slow_sma_window: PositiveInt = 200
    atr_window: PositiveInt = 14
    atr_sl_mult: PositiveFloat = 2.0
    rr_ratio: PositiveFloat = 3.0
    trade_direction: Literal["both", "long", "short"] = "both"
    unsubscribe_data_on_stop: bool = True
    close_positions_on_stop: bool = True


class SmaPullbackStrategy(Strategy):
    """Translate Nautilus bars into the SMA pullback policy."""

    def __init__(self, config: SmaPullbackStrategyConfig) -> None:
        strategy_id = _validate_strategy_id(config.strategy_id)
        if float(config.slot_multiplier) < 0.0:
            raise ValueError("slot_multiplier must be non-negative")
        super().__init__(config)
        self.instrument: Instrument | None = None
        self._instrument_id = InstrumentId.from_str(config.instrument_id)
        self._bar_type = BarType.from_str(config.bar_type)
        self._slot_multiplier = float(config.slot_multiplier)
        self._policy_parameters = SmaPullbackParameters(
            strategy_id=strategy_id,
            symbol=config.symbol,
            trade_size=float(config.unit_trade_size),
            fast_sma_window=int(config.fast_sma_window),
            slow_sma_window=int(config.slow_sma_window),
            atr_window=int(config.atr_window),
            atr_sl_mult=float(config.atr_sl_mult),
            rr_ratio=float(config.rr_ratio),
            trade_direction=config.trade_direction,
        )
        self._state = SmaPullbackState()

    def on_start(self) -> None:
        self.instrument = self.cache.instrument(self._instrument_id)
        if self.instrument is None:
            self.log.error(f"Could not find instrument for {self.config.instrument_id}")
            self.stop()
            return
        self.subscribe_bars(self._bar_type)

    def on_bar(self, bar: Bar) -> None:
        if bar.is_single_price():
            return
        if self._slot_multiplier <= 0.0:
            return

        previous_position = self._state.position
        decision = evaluate_sma_pullback(
            parameters=self._policy_parameters,
            state=self._state,
            bar=SmaPullbackBar(
                open_price=float(bar.open),
                high_price=float(bar.high),
                low_price=float(bar.low),
                close_price=float(bar.close),
            ),
        )
        self._state = decision.next_state
        if not decision.order_intents:
            return

        if previous_position is not None and decision.next_state.position is None:
            self.close_all_positions(instrument_id=self._instrument_id, reduce_only=True)
            return

        for intent in decision.order_intents:
            quantity = self._create_order_qty()
            if quantity is None:
                continue
            self.submit_order(
                self.order_factory.market(
                    instrument_id=self._instrument_id,
                    order_side=_to_nautilus_side(intent.side),
                    quantity=quantity,
                    time_in_force=TimeInForce.GTC,
                )
            )

    def on_stop(self) -> None:
        self.cancel_all_orders(self._instrument_id)
        if self.config.close_positions_on_stop:
            self.close_all_positions(
                instrument_id=self._instrument_id,
                reduce_only=True,
            )
        if self.config.unsubscribe_data_on_stop:
            self.unsubscribe_bars(self._bar_type)

    def on_reset(self) -> None:
        self._state = SmaPullbackState()

    def _create_order_qty(self) -> Quantity | None:
        if self.instrument is None:
            raise RuntimeError("instrument must be loaded before order creation")
        effective_trade_size = float(self.config.unit_trade_size) * self._slot_multiplier
        if effective_trade_size <= 0.0:
            return None
        return self.instrument.make_qty(Decimal(str(effective_trade_size)))


def _to_nautilus_side(side: DomainOrderSide) -> OrderSide:
    return OrderSide.BUY if side is DomainOrderSide.BUY else OrderSide.SELL


def _validate_strategy_id(strategy_id: str) -> str:
    if not strategy_id:
        raise ValueError("strategy_id must be provided")
    return strategy_id


__all__ = ["SmaPullbackStrategy", "SmaPullbackStrategyConfig"]
