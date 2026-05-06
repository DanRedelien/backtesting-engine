"""Test-only Nautilus strategy for bar replay causality characterization."""

from __future__ import annotations

import json
from pathlib import Path

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.trading.strategy import Strategy


class ObservingBarReplayStrategyConfig(StrategyConfig, kw_only=True, frozen=True):
    """Configuration for the test-only bar replay observer."""

    bar_type: str
    expected_ts_event_ns: list[int]
    output_path: str


class ObservingBarReplayStrategy(Strategy):  # type: ignore[misc]
    """Record bar observations without placing orders."""

    def __init__(self, config: ObservingBarReplayStrategyConfig) -> None:
        super().__init__(config)
        self._observed_ts_event_ns: list[int] = []
        self._records: list[dict[str, int | bool]] = []

    def on_start(self) -> None:
        self.subscribe_bars(BarType.from_str(self.config.bar_type))

    def on_bar(self, bar: Bar) -> None:
        observation_index = len(self._observed_ts_event_ns)
        expected = self.config.expected_ts_event_ns
        next_ts_event_ns = (
            expected[observation_index + 1]
            if observation_index + 1 < len(expected)
            else None
        )
        self._records.append(
            {
                "observation_index": observation_index,
                "ts_event_ns": int(bar.ts_event),
                "observed_count_before": observation_index,
                "next_bar_seen_before": (
                    next_ts_event_ns in self._observed_ts_event_ns
                    if next_ts_event_ns is not None
                    else False
                ),
            }
        )
        self._observed_ts_event_ns.append(int(bar.ts_event))

    def on_stop(self) -> None:
        output_path = Path(self.config.output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(
                {
                    "observed_ts_event_ns": self._observed_ts_event_ns,
                    "records": self._records,
                },
                indent=2,
            ),
            encoding="utf-8",
        )


__all__ = ["ObservingBarReplayStrategy", "ObservingBarReplayStrategyConfig"]
