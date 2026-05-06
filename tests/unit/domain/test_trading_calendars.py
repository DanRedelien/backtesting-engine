from __future__ import annotations

import pytest

from backtest_engine.domain.market.calendars import (
    BUILTIN_CALENDAR_PROFILES,
    TradingCalendarSpec,
    resolve_trading_calendar,
)


def test_builtin_profiles_resolve() -> None:
    for calendar_id in ("CRYPTO_24_7", "FX_24_5", "CFD_BROKER_SESSION", "CME_INDEX_FUTURES"):
        spec = resolve_trading_calendar(calendar_id)
        assert isinstance(spec, TradingCalendarSpec)
        assert spec.calendar_id == calendar_id


def test_unknown_calendar_raises_value_error() -> None:
    with pytest.raises(ValueError, match="unknown trading calendar"):
        resolve_trading_calendar("NONEXISTENT")


def test_extra_profiles_override_builtins() -> None:
    """Extension point: callers pass extra_profiles explicitly, no global mutation."""

    def _custom_crypto(calendar_id: str, timezone_name: str | None) -> TradingCalendarSpec:
        return TradingCalendarSpec(
            calendar_id=calendar_id,
            timezone_name=timezone_name or "UTC",
            session_template="CUSTOM_CRYPTO",
            weekend_trading_enabled=True,
        )

    spec = resolve_trading_calendar(
        "CRYPTO_24_7",
        timezone_name="Asia/Tokyo",
        extra_profiles={"CRYPTO_24_7": _custom_crypto},
    )
    assert spec.session_template == "CUSTOM_CRYPTO"
    assert spec.timezone_name == "Asia/Tokyo"

    default_spec = resolve_trading_calendar("CRYPTO_24_7", timezone_name="Asia/Tokyo")
    assert default_spec.session_template == "CRYPTO_24_7"


def test_extra_profiles_add_new_calendar() -> None:
    """Extension point: custom exchange-specific profiles without touching builtins."""

    def _eurex_bond_futures(calendar_id: str, timezone_name: str | None) -> TradingCalendarSpec:
        return TradingCalendarSpec(
            calendar_id=calendar_id,
            timezone_name=timezone_name or "Europe/Berlin",
            session_template="EUREX_BOND_FUTURES",
        )

    spec = resolve_trading_calendar(
        "EUREX_BOND_FUTURES",
        extra_profiles={"EUREX_BOND_FUTURES": _eurex_bond_futures},
    )
    assert spec.calendar_id == "EUREX_BOND_FUTURES"
    assert spec.timezone_name == "Europe/Berlin"


def test_builtin_profiles_are_frozen() -> None:
    with pytest.raises(TypeError):
        BUILTIN_CALENDAR_PROFILES["NEW"] = lambda cid, tz: None  # type: ignore[index]


def test_builtin_profile_ids() -> None:
    assert set(BUILTIN_CALENDAR_PROFILES) == {"CRYPTO_24_7", "FX_24_5", "CFD_BROKER_SESSION", "CME_INDEX_FUTURES"}


def test_cme_index_futures_uses_chicago_timezone() -> None:
    spec = resolve_trading_calendar("CME_INDEX_FUTURES")
    assert spec.timezone_name == "America/Chicago"
    assert spec.holiday_calendar == "US_FEDERAL"
    assert len(spec.maintenance_windows) == 1


def test_crypto_accepts_custom_timezone() -> None:
    spec = resolve_trading_calendar("CRYPTO_24_7", timezone_name="Asia/Tokyo")
    assert spec.timezone_name == "Asia/Tokyo"
    assert spec.weekend_trading_enabled is True
