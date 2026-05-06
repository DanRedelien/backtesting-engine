"""Nautilus wrapper for the weighted-spread statarb cartridge."""

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

from backtest_engine.strategies.statarb_weighted_spread.parameters import (
    StatarbWeightedSpreadParameters,
)
from backtest_engine.strategies.statarb_weighted_spread.policy import (
    StatarbWeightedSpreadState,
    evaluate_statarb_weighted_spread,
)


class StatarbWeightedSpreadStrategyConfig(StrategyConfig, kw_only=True, frozen=True):
    """Configuration for the weighted-spread statarb Nautilus wrapper."""

    instrument_ids: list[str]
    bar_types: list[str]
    leg_symbols: list[str]
    unit_trade_sizes: list[PositiveFloat]
    spread_weights: list[float]
    zscore_window: PositiveInt
    entry_zscore: PositiveFloat
    exit_zscore: float
    strategy_id: str = ""
    trade_direction: Literal["both", "long_spread_only", "short_spread_only"] = "both"
    slot_multiplier: float = 1.0
    unsubscribe_data_on_stop: bool = True
    close_positions_on_stop: bool = True


class StatarbWeightedSpreadStrategy(Strategy):
    """Translate synchronized multi-leg bars into weighted-spread regime trades."""

    def __init__(self, config: StatarbWeightedSpreadStrategyConfig) -> None:
        strategy_id = _validate_strategy_id(config.strategy_id)
        if float(config.slot_multiplier) < 0.0:
            raise ValueError("slot_multiplier must be non-negative")
        if len(config.instrument_ids) < 2:
            raise ValueError("statarb_weighted_spread requires at least two instrument_ids")
        leg_count = len(config.instrument_ids)
        if len(config.bar_types) != leg_count:
            raise ValueError("bar_types length must match instrument_ids length")
        if len(config.leg_symbols) != leg_count:
            raise ValueError("leg_symbols length must match instrument_ids length")
        if len(config.unit_trade_sizes) != leg_count:
            raise ValueError("unit_trade_sizes length must match instrument_ids length")
        if len(config.spread_weights) != leg_count:
            raise ValueError("spread_weights length must match instrument_ids length")

        super().__init__(config)
        self._instrument_ids = tuple(InstrumentId.from_str(value) for value in config.instrument_ids)
        self._bar_types = tuple(BarType.from_str(value) for value in config.bar_types)
        self._instruments: dict[str, Instrument] = {}
        self._latest_close_by_instrument_id: dict[str, float] = {}
        self._latest_ts_by_instrument_id: dict[str, int] = {}
        self._last_processed_ts_event: int | None = None
        self._desync_observation_count = 0
        self._invalid_due_to_desync = False
        self._slot_multiplier = float(config.slot_multiplier)
        self._policy_parameters = StatarbWeightedSpreadParameters(
            strategy_id=strategy_id,
            leg_symbols=tuple(config.leg_symbols),
            trade_sizes=tuple(float(value) for value in config.unit_trade_sizes),
            spread_weights=tuple(float(value) for value in config.spread_weights),
            zscore_window=int(config.zscore_window),
            entry_zscore=float(config.entry_zscore),
            exit_zscore=float(config.exit_zscore),
            trade_direction=config.trade_direction,
        )
        self._state = StatarbWeightedSpreadState()

    def on_start(self) -> None:
        for instrument_id, bar_type in zip(self._instrument_ids, self._bar_types):
            instrument = self.cache.instrument(instrument_id)
            if instrument is None:
                self.log.error(f"Could not find instrument for {instrument_id}")
                self.stop()
                return
            self._instruments[instrument_id.value] = instrument
            self.subscribe_bars(bar_type)

    def on_bar(self, bar: Bar) -> None:
        if bar.is_single_price():
            return

        instrument_key = bar.bar_type.instrument_id.value
        self._latest_close_by_instrument_id[instrument_key] = float(bar.close)
        self._latest_ts_by_instrument_id[instrument_key] = int(bar.ts_event)
        if len(self._latest_close_by_instrument_id) != len(self._instrument_ids):
            return

        current_ts_values = set(self._latest_ts_by_instrument_id.values())
        if len(current_ts_values) != 1:
            self._desync_observation_count += 1
            if self._desync_observation_count > len(self._instrument_ids):
                self._invalidate_sleeve("leg timestamp desync")
            return

        current_ts_event = next(iter(current_ts_values))
        self._desync_observation_count = 0
        if self._invalid_due_to_desync:
            self._invalid_due_to_desync = False
        if self._last_processed_ts_event == current_ts_event:
            return
        self._last_processed_ts_event = current_ts_event

        decision = evaluate_statarb_weighted_spread(
            parameters=self._policy_parameters,
            state=self._state,
            close_prices=tuple(
                self._latest_close_by_instrument_id[instrument_id.value]
                for instrument_id in self._instrument_ids
            ),
        )
        self._state = decision.next_state
        self._sync_target_positions(decision.desired_regime)

    def on_stop(self) -> None:
        for instrument_id, bar_type in zip(self._instrument_ids, self._bar_types):
            self.cancel_all_orders(instrument_id)
            if self.config.close_positions_on_stop:
                self.close_all_positions(
                    instrument_id=instrument_id,
                    reduce_only=True,
                )
            if self.config.unsubscribe_data_on_stop:
                self.unsubscribe_bars(bar_type)

    def on_reset(self) -> None:
        self._latest_close_by_instrument_id.clear()
        self._latest_ts_by_instrument_id.clear()
        self._last_processed_ts_event = None
        self._desync_observation_count = 0
        self._invalid_due_to_desync = False
        self._state = StatarbWeightedSpreadState()

    def _sync_target_positions(self, desired_regime: int) -> None:
        if self._slot_multiplier <= 0.0:
            return
        for instrument_id, trade_size, spread_weight in zip(
            self._instrument_ids,
            self._policy_parameters.trade_sizes,
            self._policy_parameters.spread_weights,
        ):
            instrument_key = instrument_id.value
            current_qty = float(self.portfolio.net_position(instrument_id))
            target_qty = _target_qty_for_leg(
                desired_regime=desired_regime,
                trade_size=trade_size,
                spread_weight=spread_weight,
                slot_multiplier=self._slot_multiplier,
            )
            delta_qty = target_qty - current_qty
            if abs(delta_qty) <= 1e-9:
                continue

            reduce_only = (
                current_qty != 0.0
                and target_qty * current_qty > 0.0
                and abs(target_qty) < abs(current_qty)
            )
            self.submit_order(
                self.order_factory.market(
                    instrument_id=instrument_id,
                    order_side=OrderSide.BUY if delta_qty > 0.0 else OrderSide.SELL,
                    quantity=self._create_order_qty(instrument_key, abs(delta_qty)),
                    time_in_force=TimeInForce.GTC,
                    reduce_only=reduce_only,
                )
            )

    def _create_order_qty(self, instrument_id: str, quantity: float) -> Quantity:
        instrument = self._instruments[instrument_id]
        return instrument.make_qty(Decimal(str(quantity)))

    def _invalidate_sleeve(self, reason: str) -> None:
        if self._invalid_due_to_desync:
            return
        self.log.warning(f"Invalidating statarb sleeve: {reason}")
        self._invalid_due_to_desync = True
        self._latest_close_by_instrument_id.clear()
        self._latest_ts_by_instrument_id.clear()
        self._last_processed_ts_event = None
        self._desync_observation_count = 0
        self._state = StatarbWeightedSpreadState()
        for instrument_id in self._instrument_ids:
            self.cancel_all_orders(instrument_id)
            self.close_all_positions(
                instrument_id=instrument_id,
                reduce_only=True,
            )


def _target_qty_for_leg(
    *,
    desired_regime: int,
    trade_size: float,
    spread_weight: float,
    slot_multiplier: float,
) -> float:
    if desired_regime == 0 or spread_weight == 0.0:
        return 0.0
    direction = 1.0 if desired_regime * spread_weight > 0.0 else -1.0
    return float(trade_size) * float(slot_multiplier) * direction


def _validate_strategy_id(strategy_id: str) -> str:
    if not strategy_id:
        raise ValueError("strategy_id must be provided")
    return strategy_id


__all__ = ["StatarbWeightedSpreadStrategy", "StatarbWeightedSpreadStrategyConfig"]
