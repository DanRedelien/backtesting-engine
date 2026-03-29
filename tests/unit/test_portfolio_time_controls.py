"""Tests for portfolio-engine trading window and EOD time controls."""

from datetime import datetime

import pandas as pd

from src.backtest_engine.portfolio_layer.domain.contracts import PortfolioConfig, StrategySlot
from src.backtest_engine.portfolio_layer.engine.engine import PortfolioBacktestEngine
from src.backtest_engine.settings import BacktestSettings
from src.strategies.base import BaseStrategy


class PortfolioSessionEntryStrategy(BaseStrategy):
    """Emits a single long entry intent and keeps invested state until EOD close."""

    def __init__(self, engine) -> None:
        super().__init__(engine)
        self.calls = 0

    def on_bar(self, bar) -> list:
        self.calls += 1
        if not getattr(self, "_invested", False):
            self._invested = True
            self._position_side = "LONG"
            return [self.market_order("BUY", 1, reason="SIGNAL")]
        return []


def test_portfolio_engine_enforces_trading_window_and_eod_close() -> None:
    """Strategy runs only in session; open positions are flattened at EOD time."""
    index = pd.DatetimeIndex(
        [
            datetime(2025, 1, 1, 9, 0),
            datetime(2025, 1, 1, 9, 30),
            datetime(2025, 1, 1, 10, 0),
            datetime(2025, 1, 1, 10, 30),
        ]
    )
    data = pd.DataFrame(
        {
            "open": [100.0, 101.0, 102.0, 103.0],
            "high": [100.0, 101.0, 102.0, 103.0],
            "low": [100.0, 101.0, 102.0, 103.0],
            "close": [100.0, 101.0, 102.0, 103.0],
            "volume": [1.0, 1.0, 1.0, 1.0],
        },
        index=index,
    )

    slot = StrategySlot(
        strategy_class=PortfolioSessionEntryStrategy,
        symbols=["NQ"],
        weight=1.0,
        timeframe="30m",
    )
    config = PortfolioConfig(
        slots=[slot],
        initial_capital=10_000.0,
        rebalance_frequency="intrabar",
        target_portfolio_vol=0.10,
    )
    settings = BacktestSettings(
        commission_rate=0.0,
        spread_ticks=0,
        use_trading_hours=True,
        trade_start_time="09:30",
        trade_end_time="10:00",
        eod_close_time="10:30",
    )
    settings.instrument_specs = {"NQ": {"tick_size": 1.0, "multiplier": 1.0}}

    engine = PortfolioBacktestEngine(config=config, settings=settings)
    engine._data_map = {(0, "NQ"): data}
    engine.run()

    assert engine.book.get_position(0, "NQ") == 0.0
    slot_trades = engine._slot_trades[0]
    assert len(slot_trades) == 1
    assert slot_trades[0].entry_time == datetime(2025, 1, 1, 10, 0)
    assert slot_trades[0].exit_time == datetime(2025, 1, 1, 10, 30)
    assert any(tr.exit_reason == "EOD_CLOSE" for tr in slot_trades)
