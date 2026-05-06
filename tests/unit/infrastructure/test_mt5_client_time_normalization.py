from __future__ import annotations

import pandas as pd

from backtest_engine.config.data import Mt5DataSettings
from backtest_engine.infrastructure.data.mt5.client import Mt5HistoricalClient


def test_mt5_client_normalizes_broker_timezone_to_utc() -> None:
    client = Mt5HistoricalClient(settings=Mt5DataSettings(broker_timezone_name="Europe/Riga"))
    frame = client._to_frame(  # noqa: SLF001
        [
            {
                "time": 1717372800,
                "open": 1.0,
                "high": 1.2,
                "low": 0.9,
                "close": 1.1,
                "tick_volume": 10,
                "real_volume": 0,
            }
        ]
    )

    assert frame.index[0].tz is not None
    assert frame.index[0].tzname() == "UTC"
    assert frame.index[0] == pd.Timestamp("2024-06-02T21:00:00Z")
    assert frame.loc[pd.Timestamp("2024-06-02T21:00:00Z"), "open"] == 1.0
    assert frame.loc[pd.Timestamp("2024-06-02T21:00:00Z"), "high"] == 1.2
    assert frame.loc[pd.Timestamp("2024-06-02T21:00:00Z"), "low"] == 0.9
    assert frame.loc[pd.Timestamp("2024-06-02T21:00:00Z"), "close"] == 1.1
    assert frame.loc[pd.Timestamp("2024-06-02T21:00:00Z"), "volume"] == 0.0
    assert not frame[["open", "high", "low", "close", "volume"]].isna().any().any()


def test_mt5_client_shifts_nonexistent_broker_midnight_forward() -> None:
    client = Mt5HistoricalClient(settings=Mt5DataSettings(broker_timezone_name="Europe/Riga"))
    frame = client._to_frame(  # noqa: SLF001
        [
            {
                "time": 418003200,
                "open": 1.0,
                "high": 1.2,
                "low": 0.9,
                "close": 1.1,
                "tick_volume": 10,
                "real_volume": 0,
            }
        ]
    )

    assert frame.index[0] == pd.Timestamp("1983-03-31T21:00:00Z")


def test_mt5_client_preserves_values_under_datetime_index() -> None:
    client = Mt5HistoricalClient(settings=Mt5DataSettings(broker_timezone_name="Europe/Riga"))
    frame = client._to_frame(  # noqa: SLF001
        [
            {
                "time": 1717372800,
                "open": 1.1,
                "high": 1.2,
                "low": 1.0,
                "close": 1.15,
                "tick_volume": 12,
                "spread": 3,
            },
            {
                "time": 1717373700,
                "open": 1.2,
                "high": 1.3,
                "low": 1.1,
                "close": 1.25,
                "tick_volume": 13,
                "spread": 4,
            },
        ]
    )

    assert tuple(frame["open"]) == (1.1, 1.2)
    assert tuple(frame["high"]) == (1.2, 1.3)
    assert tuple(frame["low"]) == (1.0, 1.1)
    assert tuple(frame["close"]) == (1.15, 1.25)
    assert tuple(frame["volume"]) == (12.0, 13.0)
    assert tuple(frame["spread"]) == (3.0, 4.0)
    assert not frame.isna().any().any()


def test_mt5_client_preserves_rate_time_as_event_time_without_close_shift() -> None:
    client = Mt5HistoricalClient(settings=Mt5DataSettings(broker_timezone_name="Europe/Riga"))

    frame = client._to_frame(  # noqa: SLF001
        [
            {
                "time": 1717372800,
                "open": 1.1,
                "high": 1.2,
                "low": 1.0,
                "close": 1.15,
                "tick_volume": 12,
            },
            {
                "time": 1717373700,
                "open": 1.2,
                "high": 1.3,
                "low": 1.1,
                "close": 1.25,
                "tick_volume": 13,
            },
        ]
    )

    expected_event_times = pd.DatetimeIndex(
        [
            pd.Timestamp("2024-06-02T21:00:00Z"),
            pd.Timestamp("2024-06-02T21:15:00Z"),
        ],
    )
    close_shifted_times = expected_event_times + pd.Timedelta(minutes=15)
    assert tuple(frame.index) == tuple(expected_event_times), (
        "MT5 rate timestamps must remain provider event times here. "
        "If this fails, a close-time shift was added in Mt5HistoricalClient; "
        "check for double-shift risk before also shifting in normalizer/catalog code."
    )
    assert tuple(frame.index) != tuple(close_shifted_times), (
        "MT5 client unexpectedly emitted close-shifted timestamps. "
        "The current timestamp contract expects no shift in this layer."
    )
