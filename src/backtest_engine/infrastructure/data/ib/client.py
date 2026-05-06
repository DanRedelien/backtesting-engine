"""Thin IB client wrapper kept entirely inside infrastructure."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Protocol, cast

import pandas as pd

from backtest_engine.config.data import IbDataSettings
from backtest_engine.core.errors import InfrastructureError
from backtest_engine.core.time import ensure_utc
from backtest_engine.core.types import NonEmptyStr, Symbol
from backtest_engine.infrastructure.data.ib.contracts import IbResolvedContract, parse_ib_expiry
from backtest_engine.infrastructure.data.ib.timeframes import IbTimeframe


class IbGateway(Protocol):
    """Minimal IB gateway contract used by the infrastructure adapter."""

    def connect(
        self,
        *,
        host: str,
        port: int,
        clientId: int,
        timeout: float,
    ) -> object:
        """Open a gateway session."""
        ...

    def disconnect(self) -> object:
        """Close the gateway session."""
        ...

    def reqContractDetails(self, contract_request: object) -> object:
        """Return contract discovery results."""
        ...

    def reqHistoricalData(
        self,
        contract_handle: object,
        *,
        endDateTime: datetime,
        durationStr: str,
        barSizeSetting: str,
        whatToShow: str,
        useRTH: bool,
        formatDate: int,
    ) -> object:
        """Return historical bars from IB."""
        ...


GatewayFactory = Callable[[], IbGateway]
FutureFactory = Callable[[str, str], object]
BarsToFrame = Callable[[object], pd.DataFrame]


@dataclass
class IbHistoricalClient:
    """Own IB connection lifecycle and convert vendor responses to DataFrames."""

    settings: IbDataSettings
    gateway_factory: GatewayFactory | None = None
    future_factory: FutureFactory | None = None
    bars_to_frame: BarsToFrame | None = None
    _gateway: IbGateway | None = field(default=None, init=False, repr=False)
    _connected: bool = field(default=False, init=False, repr=False)
    _last_request_time: float = field(default=0.0, init=False, repr=False)

    def connect(self) -> None:
        """Open one IB session if the client is not already connected."""

        if self._connected:
            return

        gateway = self._gateway or self._build_gateway()
        try:
            gateway.connect(
                host=self.settings.host,
                port=self.settings.port,
                clientId=self.settings.client_id,
                timeout=self.settings.timeout_sec,
            )
        except Exception as exc:
            raise InfrastructureError(
                "failed to connect to IB gateway",
                host=self.settings.host,
                port=self.settings.port,
            ) from exc

        self._gateway = gateway
        self._connected = True

    def disconnect(self) -> None:
        """Close the current IB session when one is open."""

        if not self._connected or self._gateway is None:
            return

        try:
            self._gateway.disconnect()
        except Exception as exc:
            raise InfrastructureError("failed to disconnect from IB gateway") from exc
        finally:
            self._connected = False

    def list_contracts(
        self,
        *,
        symbol: Symbol,
        ib_symbol: NonEmptyStr,
        exchange: NonEmptyStr,
    ) -> tuple[IbResolvedContract, ...]:
        """Resolve one full futures contract chain from IB contract details."""

        gateway = self._require_gateway()
        contract_request = self._build_future(symbol=ib_symbol, exchange=exchange)
        try:
            setattr(contract_request, "includeExpired", True)
            details = gateway.reqContractDetails(contract_request)
        except Exception as exc:
            raise InfrastructureError(
                "failed to resolve IB contract chain",
                symbol=symbol,
                exchange=exchange,
            ) from exc

        resolved: list[IbResolvedContract] = []
        for detail in cast(Any, details) or []:
            contract = getattr(detail, "contract", None)
            local_symbol = str(getattr(contract, "localSymbol", "") or "").strip()
            expiry_raw = str(getattr(contract, "lastTradeDateOrContractMonth", "") or "").strip()
            if contract is None or not local_symbol or not expiry_raw:
                continue
            resolved.append(
                IbResolvedContract(
                    symbol=symbol,
                    exchange=exchange,
                    local_symbol=local_symbol,
                    expiry_utc=parse_ib_expiry(expiry_raw),
                    contract_handle=contract,
                )
            )
        return tuple(resolved)

    def fetch_chunk(
        self,
        contract: IbResolvedContract,
        *,
        end_utc: datetime,
        timeframe: IbTimeframe,
        duration: str,
    ) -> pd.DataFrame:
        """Fetch one historical chunk and normalize the frame into UTC order."""

        gateway = self._require_gateway()
        self._wait_for_pacing()

        try:
            bars = gateway.reqHistoricalData(
                contract.contract_handle,
                endDateTime=ensure_utc(end_utc),
                durationStr=duration,
                barSizeSetting=timeframe.ib_bar_size,
                whatToShow="TRADES",
                useRTH=self.settings.use_rth,
                formatDate=1,
            )
        except Exception as exc:
            raise InfrastructureError(
                "failed to fetch IB historical bars",
                symbol=contract.symbol,
                local_symbol=contract.local_symbol,
                timeframe=timeframe.file_suffix,
            ) from exc

        return _normalize_bars_frame(self._coerce_bars_to_frame(bars))

    def _wait_for_pacing(self) -> None:
        elapsed = time.time() - self._last_request_time
        if elapsed < self.settings.pacing_delay_sec:
            time.sleep(self.settings.pacing_delay_sec - elapsed)
        self._last_request_time = time.time()

    def _build_gateway(self) -> IbGateway:
        if self.gateway_factory is not None:
            return self.gateway_factory()
        try:
            from ib_insync import IB
        except ImportError as exc:
            raise InfrastructureError(
                "ib_insync is required for live IB ingestion",
                install_extra="ib",
            ) from exc
        return cast(Callable[[], IbGateway], IB)()

    def _build_future(self, *, symbol: str, exchange: str) -> object:
        if self.future_factory is not None:
            return self.future_factory(symbol, exchange)
        try:
            from ib_insync import Future
        except ImportError as exc:
            raise InfrastructureError(
                "ib_insync is required for live IB contract discovery",
                install_extra="ib",
            ) from exc
        return Future(symbol, exchange=exchange)

    def _coerce_bars_to_frame(self, bars: object) -> pd.DataFrame:
        if isinstance(bars, pd.DataFrame):
            return bars.copy()
        if self.bars_to_frame is not None:
            return self.bars_to_frame(bars)
        try:
            from ib_insync import util
        except ImportError as exc:
            raise InfrastructureError(
                "ib_insync is required for IB bar conversion",
                install_extra="ib",
            ) from exc
        return cast(pd.DataFrame, util.df(bars))

    def _require_gateway(self) -> IbGateway:
        if self._gateway is None or not self._connected:
            raise InfrastructureError("IB client is not connected")
        return self._gateway


def _normalize_bars_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame

    working = frame.copy()
    if "date" in working.columns:
        working["date"] = pd.to_datetime(working["date"], utc=True)
        working = working.set_index("date")
    elif not isinstance(working.index, pd.DatetimeIndex):
        working.index = pd.to_datetime(working.index, utc=True)
    elif working.index.tz is None:
        working.index = working.index.tz_localize("UTC")
    else:
        working.index = working.index.tz_convert("UTC")

    return working.sort_index()


__all__ = ["IbHistoricalClient"]
