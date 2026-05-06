"""Lazy MT5 transport client used by the historical-data provider."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from types import ModuleType
from typing import Any, Callable, cast
from zoneinfo import ZoneInfo

import pandas as pd

from backtest_engine.config.data import Mt5DataSettings
from backtest_engine.core.errors import InfrastructureError
from backtest_engine.core.time import ensure_utc
from backtest_engine.infrastructure.data.errors import ProviderUnavailableError
from backtest_engine.infrastructure.data.mt5.timeframes import mt5_timeframe_attr

GatewayLoader = Callable[[], ModuleType]


@dataclass
class Mt5HistoricalClient:
    """Own MT5 module lifecycle and normalize returned bars into UTC."""

    settings: Mt5DataSettings
    gateway_loader: GatewayLoader | None = None
    _gateway: ModuleType | None = field(default=None, init=False, repr=False)
    _broker_tz: ZoneInfo | None = field(init=False, repr=False)

    def __post_init__(self) -> None:
        tz_name = self.settings.broker_timezone_name
        self._broker_tz = ZoneInfo(tz_name) if tz_name is not None else None

    def connect(self) -> None:
        if self._gateway is not None:
            return
        if os.name != "nt":
            raise ProviderUnavailableError(
                "MT5 historical ingestion is only supported on Windows",
                platform=os.name,
            )
        gateway = self._load_gateway()
        kwargs: dict[str, int | str] = {"timeout": self.settings.timeout_ms}
        if self.settings.terminal_path is not None:
            kwargs["path"] = str(self.settings.terminal_path)
        if not gateway.initialize(**kwargs):
            raise ProviderUnavailableError(
                "failed to initialize the MT5 terminal",
                last_error=str(gateway.last_error()),
            )
        self._gateway = gateway

    def disconnect(self) -> None:
        if self._gateway is None:
            return
        self._gateway.shutdown()
        self._gateway = None

    def fetch_with_poll(
        self,
        *,
        provider_symbol: str,
        timeframe: str,
        start_utc: datetime,
        end_utc: datetime,
    ) -> pd.DataFrame:
        gateway = self._require_gateway()
        start_edge = ensure_utc(start_utc)
        end_edge = ensure_utc(end_utc)
        frame = pd.DataFrame()
        for _ in range(self.settings.max_poll_attempts):
            rates = gateway.copy_rates_range(
                provider_symbol,
                getattr(gateway, mt5_timeframe_attr(timeframe)),
                start_edge,
                end_edge,
            )
            frame = self._to_frame(rates)
            if (
                not frame.empty
                and frame.index.min() <= start_edge
                and frame.index.max() >= end_edge
            ):
                return frame
            time.sleep(self.settings.poll_delay_sec)
        return frame

    def session_metadata(self) -> dict[str, str | int | float | bool | None]:
        gateway = self._require_gateway()
        terminal_info = gateway.terminal_info()
        account_info = gateway.account_info()
        return {
            "terminal_company": getattr(terminal_info, "company", None),
            "terminal_name": getattr(terminal_info, "name", None),
            "terminal_build": getattr(terminal_info, "build", None),
            "account_server": getattr(account_info, "server", None),
            "account_login": getattr(account_info, "login", None),
            "broker_timezone_name": self.settings.broker_timezone_name,
            "timestamp_semantics": "broker_local_epoch_seconds_normalized_to_utc",
        }

    def _to_frame(self, rates: object) -> pd.DataFrame:
        if rates is None:
            return pd.DataFrame()
        frame: pd.DataFrame = pd.DataFrame(cast(Any, rates))
        if frame.empty:
            return frame.copy()
        raw_time = pd.to_datetime(frame["time"], unit="s")
        localized = _normalize_mt5_broker_times(raw_time, broker_tz=self._broker_tz)
        if "real_volume" in frame.columns:
            volume_source = frame["real_volume"]
        elif "tick_volume" in frame.columns:
            volume_source = frame["tick_volume"]
        else:
            volume_source = pd.Series(0, index=frame.index)
        normalized = pd.DataFrame(
            {
                "open": frame["open"].astype(float).to_numpy(),
                "high": frame["high"].astype(float).to_numpy(),
                "low": frame["low"].astype(float).to_numpy(),
                "close": frame["close"].astype(float).to_numpy(),
                "volume": volume_source.astype(float).to_numpy(),
            },
            index=pd.DatetimeIndex(localized),
        )
        if "spread" in frame.columns:
            normalized["spread"] = frame["spread"].astype(float).to_numpy()
        return normalized.sort_index()

    def _load_gateway(self) -> ModuleType:
        if self.gateway_loader is not None:
            return self.gateway_loader()
        try:
            import MetaTrader5 as gateway
        except ImportError as exc:
            raise ProviderUnavailableError(
                "MetaTrader5 is required for MT5 historical ingestion",
                install_extra="mt5",
            ) from exc
        return cast(ModuleType, gateway)

    def _require_gateway(self) -> ModuleType:
        if self._gateway is None:
            raise InfrastructureError("MT5 client is not connected")
        return self._gateway


def _normalize_mt5_broker_times(
    raw_time: pd.Series,
    *,
    broker_tz: ZoneInfo | None,
) -> pd.Series:
    """Normalize MT5 broker-local epoch seconds into UTC-aware timestamps.

    Older broker timezones can contain midnight DST jumps. MT5 still exposes
    monotonically increasing local-epoch seconds, so we resolve nonexistent
    wall-clock instants by shifting them to the first valid local timestamp and
    choose the post-transition offset for ambiguous fall-back instants.
    """

    if broker_tz is None:
        return cast(pd.Series, raw_time.dt.tz_localize("UTC"))
    return cast(
        pd.Series,
        raw_time.dt.tz_localize(
            broker_tz,
            ambiguous=False,
            nonexistent="shift_forward",
        ).dt.tz_convert("UTC"),
    )


__all__ = ["Mt5HistoricalClient"]
