"""Trading calendar contracts and session-aware gap policies.

Builtin profiles (``CRYPTO_24_7``, ``FX_24_5``, ``CFD_BROKER_SESSION``,
``CME_INDEX_FUTURES``) are frozen at module level.  To extend with
exchange-specific profiles (e.g. ``EUREX_BOND_FUTURES``), pass an
``extra_profiles`` mapping to :func:`resolve_trading_calendar` at the
call site rather than mutating module state.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from types import MappingProxyType
from zoneinfo import ZoneInfo

from pandas.tseries.holiday import USFederalHolidayCalendar
from pydantic import BaseModel, ConfigDict, Field

from backtest_engine.core.types import NonEmptyStr


class TradingMaintenanceWindow(BaseModel):
    """One recurring local maintenance break."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    start_local: NonEmptyStr
    end_local: NonEmptyStr
    weekdays: tuple[int, ...] = ()


class TradingCalendarSpec(BaseModel):
    """A named trading calendar and timezone pairing."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    calendar_id: NonEmptyStr
    timezone_name: NonEmptyStr
    session_template: NonEmptyStr
    maintenance_gap_minutes: int = Field(default=0, ge=0)
    weekend_trading_enabled: bool = False
    sunday_open_local: NonEmptyStr | None = None
    friday_close_local: NonEmptyStr | None = None
    maintenance_windows: tuple[TradingMaintenanceWindow, ...] = ()
    holiday_calendar: NonEmptyStr | None = None


CalendarFactory = Callable[[str, str | None], TradingCalendarSpec]


def _crypto_24_7(calendar_id: str, timezone_name: str | None) -> TradingCalendarSpec:
    return TradingCalendarSpec(
        calendar_id=calendar_id,
        timezone_name=timezone_name or "UTC",
        session_template="CRYPTO_24_7",
        weekend_trading_enabled=True,
    )


def _fx_24_5(calendar_id: str, _timezone_name: str | None) -> TradingCalendarSpec:
    return TradingCalendarSpec(
        calendar_id=calendar_id,
        timezone_name="America/New_York",
        session_template="FX_24_5",
        sunday_open_local="17:00",
        friday_close_local="17:00",
    )


def _cfd_broker_session(calendar_id: str, timezone_name: str | None) -> TradingCalendarSpec:
    return TradingCalendarSpec(
        calendar_id=calendar_id,
        timezone_name=timezone_name or "UTC",
        session_template="CFD_BROKER_SESSION",
        sunday_open_local="17:00",
        friday_close_local="17:00",
        maintenance_gap_minutes=60,
        maintenance_windows=(
            TradingMaintenanceWindow(
                start_local="00:00",
                end_local="01:00",
                weekdays=(0, 1, 2, 3, 4),
            ),
        ),
    )


def _cme_index_futures(calendar_id: str, _timezone_name: str | None) -> TradingCalendarSpec:
    return TradingCalendarSpec(
        calendar_id=calendar_id,
        timezone_name="America/Chicago",
        session_template="CME_INDEX_FUTURES",
        sunday_open_local="17:00",
        friday_close_local="16:00",
        maintenance_gap_minutes=60,
        maintenance_windows=(
            TradingMaintenanceWindow(
                start_local="16:00",
                end_local="17:00",
                weekdays=(0, 1, 2, 3),
            ),
        ),
        holiday_calendar="US_FEDERAL",
    )


BUILTIN_CALENDAR_PROFILES: Mapping[str, CalendarFactory] = MappingProxyType({
    "CRYPTO_24_7": _crypto_24_7,
    "FX_24_5": _fx_24_5,
    "CFD_BROKER_SESSION": _cfd_broker_session,
    "CME_INDEX_FUTURES": _cme_index_futures,
})


def resolve_trading_calendar(
    calendar_id: str,
    *,
    timezone_name: str | None = None,
    extra_profiles: Mapping[str, CalendarFactory] | None = None,
) -> TradingCalendarSpec:
    """Resolve one named calendar profile into a concrete gap policy.

    Looks up ``calendar_id`` first in *extra_profiles* (if provided),
    then in the frozen :data:`BUILTIN_CALENDAR_PROFILES`.  Raises
    :class:`ValueError` when neither contains the requested ID.
    """

    if extra_profiles is not None:
        factory = extra_profiles.get(calendar_id)
        if factory is not None:
            return factory(calendar_id, timezone_name)
    factory = BUILTIN_CALENDAR_PROFILES.get(calendar_id)
    if factory is None:
        raise ValueError(f"unknown trading calendar '{calendar_id}'")
    return factory(calendar_id, timezone_name)


def gap_is_expected(
    previous_utc: datetime,
    current_utc: datetime,
    *,
    timeframe_minutes: int,
    calendar: TradingCalendarSpec,
) -> bool:
    """Return whether a missing interval is fully explained by market closure."""

    if current_utc <= previous_utc:
        return False
    if calendar.session_template == "CRYPTO_24_7":
        return False
    probe_step = timedelta(minutes=max(1, min(timeframe_minutes, 30)))
    probe = previous_utc + probe_step
    while probe < current_utc:
        if is_market_open(probe, calendar):
            return False
        probe += probe_step
    return True


def is_market_open(timestamp_utc: datetime, calendar: TradingCalendarSpec) -> bool:
    """Return whether the calendar expects trading to be open at one UTC timestamp."""

    local_dt = timestamp_utc.astimezone(ZoneInfo(calendar.timezone_name))
    if calendar.holiday_calendar == "US_FEDERAL" and local_dt.date() in _us_federal_holidays(local_dt.year):
        return False
    if calendar.session_template == "CRYPTO_24_7":
        return not _is_within_maintenance_window(local_dt, calendar)
    if local_dt.weekday() == 5:
        return False
    if local_dt.weekday() == 6:
        sunday_open = _parse_local_time(calendar.sunday_open_local)
        if sunday_open is None:
            return False
        return local_dt.timetz().replace(tzinfo=None) >= sunday_open and not _is_within_maintenance_window(
            local_dt,
            calendar,
        )
    friday_close = _parse_local_time(calendar.friday_close_local)
    if local_dt.weekday() == 4 and friday_close is not None:
        if local_dt.timetz().replace(tzinfo=None) >= friday_close:
            return False
    return not _is_within_maintenance_window(local_dt, calendar)


def _is_within_maintenance_window(local_dt: datetime, calendar: TradingCalendarSpec) -> bool:
    local_time = local_dt.timetz().replace(tzinfo=None)
    for window in calendar.maintenance_windows:
        if window.weekdays and local_dt.weekday() not in window.weekdays:
            continue
        start = _parse_local_time(window.start_local)
        end = _parse_local_time(window.end_local)
        if start is None or end is None:
            continue
        if start <= end and start <= local_time < end:
            return True
        if start > end and (local_time >= start or local_time < end):
            return True
    return False


def _parse_local_time(raw_value: str | None) -> time | None:
    if raw_value is None:
        return None
    hours, minutes = raw_value.split(":", maxsplit=1)
    return time(hour=int(hours), minute=int(minutes))


@lru_cache(maxsize=None)
def _us_federal_holidays(year: int) -> frozenset[date]:
    holiday_range = USFederalHolidayCalendar().holidays(
        start=datetime(year, 1, 1),
        end=datetime(year, 12, 31),
    )
    return frozenset(item.date() for item in holiday_range)


__all__ = [
    "BUILTIN_CALENDAR_PROFILES",
    "CalendarFactory",
    "TradingCalendarSpec",
    "TradingMaintenanceWindow",
    "gap_is_expected",
    "is_market_open",
    "resolve_trading_calendar",
]
