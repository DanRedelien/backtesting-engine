from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backtest_engine.core.time import ensure_utc


def test_ensure_utc_normalizes_aware_timestamp() -> None:
    local_time = datetime(2026, 4, 3, 12, 0, tzinfo=timezone(timedelta(hours=2)))

    normalized = ensure_utc(local_time)

    assert normalized == datetime(2026, 4, 3, 10, 0, tzinfo=timezone.utc)


def test_ensure_utc_rejects_naive_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        ensure_utc(datetime(2026, 4, 3, 12, 0))
