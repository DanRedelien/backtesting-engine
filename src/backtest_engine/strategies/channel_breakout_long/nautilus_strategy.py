"""Nautilus wrapper for the channel-breakout strategy cartridge."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from nautilus_trader.config import PositiveFloat, PositiveInt, StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide, TimeInForce, TriggerType
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.model.objects import Quantity
from nautilus_trader.trading.strategy import Strategy

from backtest_engine.core.enums import OrderSide as DomainOrderSide
from backtest_engine.core.enums import OrderType, SignalDirection
from backtest_engine.domain.execution.orders import OrderIntent
from backtest_engine.strategies.channel_breakout_long.parameters import ChannelBreakoutLongParameters
from backtest_engine.strategies.channel_breakout_long.policy import (
    ChannelBreakoutLongBar,
    ChannelBreakoutLongState,
    evaluate_channel_breakout_long,
)


class ChannelBreakoutLongStrategyConfig(StrategyConfig, kw_only=True, frozen=True):
    """Configuration for the channel-breakout Nautilus wrapper."""

    instrument_id: str
    bar_type: str
    symbol: str
    strategy_id: str = ""
    unit_trade_size: PositiveFloat = 1.0
    slot_multiplier: float = 1.0
    length: PositiveInt = 50
    ema_period: PositiveInt = 200
    entry_buffer_ticks: PositiveInt = 1
    trade_direction: Literal["both", "long", "short"] = "long"
    use_shock_filter: bool = True
    shock_atr_window: PositiveInt = 14
    shock_max_gap_atr: PositiveFloat = 1.25
    shock_max_range_atr: PositiveFloat = 3.0
    shock_max_close_change_atr: PositiveFloat = 2.0
    unsubscribe_data_on_stop: bool = True
    close_positions_on_stop: bool = True


class ChannelBreakoutLongStrategy(Strategy):
    """Translate Nautilus bars into the channel-breakout policy."""

    def __init__(self, config: ChannelBreakoutLongStrategyConfig) -> None:
        strategy_id = _validate_strategy_id(config.strategy_id)
        if float(config.slot_multiplier) < 0.0:
            raise ValueError("slot_multiplier must be non-negative")
        super().__init__(config)
        self.instrument: Instrument | None = None
        self._instrument_id = InstrumentId.from_str(config.instrument_id)
        self._bar_type = BarType.from_str(config.bar_type)
        self._tick_size: float | None = None
        self._slot_multiplier = float(config.slot_multiplier)
        self._policy_parameters = ChannelBreakoutLongParameters(
            strategy_id=strategy_id,
            symbol=config.symbol,
            trade_size=float(config.unit_trade_size),
            length=int(config.length),
            ema_period=int(config.ema_period),
            entry_buffer_ticks=int(config.entry_buffer_ticks),
            trade_direction=config.trade_direction,
            use_shock_filter=config.use_shock_filter,
            shock_atr_window=int(config.shock_atr_window),
            shock_max_gap_atr=float(config.shock_max_gap_atr),
            shock_max_range_atr=float(config.shock_max_range_atr),
            shock_max_close_change_atr=float(config.shock_max_close_change_atr),
        )
        self._state = ChannelBreakoutLongState()

    def on_start(self) -> None:
        self.instrument = self.cache.instrument(self._instrument_id)
        if self.instrument is None:
            self.log.error(f"Could not find instrument for {self.config.instrument_id}")
            self.stop()
            return
        self._tick_size = float(Decimal(str(self.instrument.price_increment)))
        self.subscribe_bars(self._bar_type)

    def on_bar(self, bar: Bar) -> None:
        if bar.is_single_price():
            return
        if self._slot_multiplier <= 0.0:
            return
        if self.instrument is None or self._tick_size is None:
            raise RuntimeError("instrument and tick size must be loaded before on_bar")

        self._cancel_open_strategy_orders()
        position_side = self._resolve_position_side()
        decision = evaluate_channel_breakout_long(
            parameters=self._policy_parameters,
            state=self._state,
            bar=ChannelBreakoutLongBar(
                open_price=float(bar.open),
                high_price=float(bar.high),
                low_price=float(bar.low),
                close_price=float(bar.close),
            ),
            position_side=position_side,
            tick_size=self._tick_size,
        )
        self._state = decision.next_state
        for intent in decision.order_intents:
            self._submit_intent(intent, reduce_only=position_side is not SignalDirection.FLAT)

    def on_stop(self) -> None:
        self._cancel_open_strategy_orders()
        if self.config.close_positions_on_stop:
            self.close_all_positions(
                instrument_id=self._instrument_id,
                reduce_only=True,
            )
        if self.config.unsubscribe_data_on_stop:
            self.unsubscribe_bars(self._bar_type)

    def on_reset(self) -> None:
        self._state = ChannelBreakoutLongState()

    def _cancel_open_strategy_orders(self) -> None:
        open_orders = tuple(
            self.cache.orders_open(
                instrument_id=self._instrument_id,
                strategy_id=self.id,
            )
        )
        for order in open_orders:
            self.cancel_order(order)

    def _resolve_position_side(self) -> SignalDirection:
        if self.portfolio.is_net_long(self._instrument_id):
            return SignalDirection.LONG
        if self.portfolio.is_net_short(self._instrument_id):
            return SignalDirection.SHORT
        return SignalDirection.FLAT

    def _submit_intent(self, intent: OrderIntent, *, reduce_only: bool) -> None:
        quantity = self._create_order_qty()
        if quantity is None:
            return
        if intent.order_type is OrderType.MARKET:
            self.submit_order(
                self.order_factory.market(
                    instrument_id=self._instrument_id,
                    order_side=_to_nautilus_side(intent.side),
                    quantity=quantity,
                    time_in_force=TimeInForce.IOC,
                    reduce_only=reduce_only,
                )
            )
            return

        instrument = self.instrument
        if instrument is None:
            raise RuntimeError("instrument must be loaded before order submission")
        if intent.order_type is OrderType.LIMIT:
            if intent.limit_price is None:
                raise RuntimeError("limit order intent requires limit_price")
            self.submit_order(
                self.order_factory.limit(
                    instrument_id=self._instrument_id,
                    order_side=_to_nautilus_side(intent.side),
                    quantity=quantity,
                    price=instrument.make_price(intent.limit_price),
                    time_in_force=TimeInForce.IOC,
                    reduce_only=reduce_only,
                )
            )
            return
        if intent.order_type is OrderType.STOP:
            if intent.stop_price is None:
                raise RuntimeError("stop order intent requires stop_price")
            self.submit_order(
                self.order_factory.stop_market(
                    instrument_id=self._instrument_id,
                    order_side=_to_nautilus_side(intent.side),
                    quantity=quantity,
                    trigger_price=instrument.make_price(intent.stop_price),
                    trigger_type=TriggerType.DEFAULT,
                    time_in_force=TimeInForce.IOC,
                    reduce_only=reduce_only,
                )
            )
            return
        if intent.order_type is OrderType.STOP_LIMIT:
            if intent.stop_price is None or intent.limit_price is None:
                raise RuntimeError("stop-limit order intent requires stop_price and limit_price")
            self.submit_order(
                self.order_factory.stop_limit(
                    instrument_id=self._instrument_id,
                    order_side=_to_nautilus_side(intent.side),
                    quantity=quantity,
                    price=instrument.make_price(intent.limit_price),
                    trigger_price=instrument.make_price(intent.stop_price),
                    trigger_type=TriggerType.DEFAULT,
                    time_in_force=TimeInForce.IOC,
                    reduce_only=reduce_only,
                )
            )
            return
        raise RuntimeError(f"unsupported order intent for channel_breakout_long: {intent.order_type}")

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


__all__ = ["ChannelBreakoutLongStrategy", "ChannelBreakoutLongStrategyConfig"]
