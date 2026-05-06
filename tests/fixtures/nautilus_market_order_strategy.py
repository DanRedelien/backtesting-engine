"""Test-only Nautilus strategy that submits one market order."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.trading.strategy import Strategy


class MarketOrderOnFirstBarStrategyConfig(StrategyConfig, kw_only=True, frozen=True):
    """Configuration for the deterministic one-order smoke strategy."""

    instrument_id: str
    bar_type: str
    side: Literal["BUY", "SELL"] = "BUY"
    quantity: str = "1"


class MarketOrderOnFirstBarStrategy(Strategy):  # type: ignore[misc]
    """Submit one market order after the first observed bar."""

    def __init__(self, config: MarketOrderOnFirstBarStrategyConfig) -> None:
        super().__init__(config)
        self._instrument_id = InstrumentId.from_str(config.instrument_id)
        self._bar_type = BarType.from_str(config.bar_type)
        self._instrument: Instrument | None = None
        self._submitted = False

    def on_start(self) -> None:
        self._instrument = self.cache.instrument(self._instrument_id)
        if self._instrument is None:
            self.log.error(f"Could not find instrument for {self.config.instrument_id}")
            self.stop()
            return
        self.subscribe_bars(self._bar_type)

    def on_bar(self, bar: Bar) -> None:
        del bar
        if self._submitted or self._instrument is None:
            return
        self._submitted = True
        self.submit_order(
            self.order_factory.market(
                instrument_id=self._instrument_id,
                order_side=_order_side(self.config.side),
                quantity=self._instrument.make_qty(Decimal(self.config.quantity)),
                time_in_force=TimeInForce.GTC,
            ),
        )


def _order_side(value: str) -> OrderSide:
    return OrderSide.BUY if value == "BUY" else OrderSide.SELL


__all__ = ["MarketOrderOnFirstBarStrategy", "MarketOrderOnFirstBarStrategyConfig"]
