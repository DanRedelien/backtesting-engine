"""Test-only Nautilus fill model for order timestamp characterization."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nautilus_trader.backtest.models.fill import FillModel
from nautilus_trader.common.config import NautilusConfig


class TimestampObservingFillModelConfig(NautilusConfig, frozen=True):
    """Configuration for timestamp observation during fill simulation."""

    output_path: str


class TimestampObservingFillModel(FillModel):  # type: ignore[misc]
    """Record order timestamp fields when Nautilus asks the fill model for a book."""

    def __init__(self, config: TimestampObservingFillModelConfig | None = None) -> None:
        super().__init__(
            prob_fill_on_limit=1.0,
            prob_fill_on_stop=1.0,
            prob_slippage=0.0,
        )
        if config is None:
            raise ValueError("TimestampObservingFillModel requires config")
        self._output_path = Path(config.output_path)

    def get_orderbook_for_fill_simulation(
        self,
        instrument: Any,
        order: Any,
        best_bid: Any,
        best_ask: Any,
    ) -> None:
        del instrument, best_bid, best_ask
        record = {
            "order_type": str(order.order_type),
            "ts_init": _timestamp_value(order, "ts_init"),
            "ts_submitted": _timestamp_value(order, "ts_submitted"),
            "ts_accepted": _timestamp_value(order, "ts_accepted"),
            "ts_last": _timestamp_value(order, "ts_last"),
            "selected_market_timestamp_utc": _unix_ns_to_iso_utc(
                _timestamp_value(order, "ts_init"),
            ),
        }
        self._append_record(record)
        return None

    def _append_record(self, record: dict[str, int | str | None]) -> None:
        self._output_path.parent.mkdir(parents=True, exist_ok=True)
        records: list[dict[str, int | str | None]] = []
        if self._output_path.exists():
            records = json.loads(self._output_path.read_text(encoding="utf-8"))
        records.append(record)
        self._output_path.write_text(json.dumps(records, indent=2), encoding="utf-8")


def _timestamp_value(order: Any, attribute_name: str) -> int | None:
    value = getattr(order, attribute_name, None)
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _unix_ns_to_iso_utc(value: int | None) -> str | None:
    if value is None or value <= 0:
        return None
    seconds, nanoseconds = divmod(value, 1_000_000_000)
    timestamp = datetime.fromtimestamp(seconds, tz=UTC).replace(
        microsecond=nanoseconds // 1_000,
    )
    return timestamp.isoformat().replace("+00:00", "Z")


__all__ = ["TimestampObservingFillModel", "TimestampObservingFillModelConfig"]
