from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from backtest_engine.core.enums import DatasetSource
from backtest_engine.infrastructure.data import (
    FilesystemHistoricalDataStore,
    MARKET_DATA_VALIDATOR_RULESET_VERSION,
    MarketDataValidator,
)
from backtest_engine.infrastructure.data.progress import (
    compute_requested_coverage_progress,
    describe_coverage_gap,
    estimate_eta_sec,
    is_coverage_sufficient,
)

from _market_data_pipeline_support import build_frame, build_manifest


def test_compute_requested_coverage_progress_measures_window_overlap() -> None:
    progress = compute_requested_coverage_progress(
        requested_start_utc=datetime(2024, 1, 1, tzinfo=timezone.utc),
        requested_end_utc=datetime(2024, 1, 11, tzinfo=timezone.utc),
        actual_start_utc=datetime(2024, 1, 3, tzinfo=timezone.utc),
        actual_end_utc=datetime(2024, 1, 8, tzinfo=timezone.utc),
    )

    assert progress == pytest.approx(0.5)


def test_estimate_eta_sec_scales_from_elapsed_progress() -> None:
    eta_sec = estimate_eta_sec(elapsed_sec=30.0, progress_frac=0.5)

    assert eta_sec == pytest.approx(30.0)


def test_coverage_sufficient_accepts_small_end_gap() -> None:
    assert is_coverage_sufficient(
        actual_start_utc=datetime(2025, 6, 1, tzinfo=timezone.utc),
        actual_end_utc=datetime(2026, 4, 10, 21, 0, tzinfo=timezone.utc),
        requested_start_utc=datetime(2025, 6, 1, tzinfo=timezone.utc),
        requested_end_utc=datetime(2026, 4, 11, 23, 59, 59, tzinfo=timezone.utc),
    )


def test_coverage_sufficient_accepts_expected_fx_weekend_start_gap() -> None:
    assert is_coverage_sufficient(
        actual_start_utc=datetime(2025, 6, 1, 21, 0, tzinfo=timezone.utc),
        actual_end_utc=datetime(2025, 6, 2, 0, 0, tzinfo=timezone.utc),
        requested_start_utc=datetime(2025, 6, 1, 0, 0, tzinfo=timezone.utc),
        requested_end_utc=datetime(2025, 6, 2, 0, 0, tzinfo=timezone.utc),
        timeframe="15m",
        calendar_id="FX_24_5",
        timezone_name="Europe/Riga",
    )


def test_coverage_sufficient_rejects_large_start_gap() -> None:
    assert not is_coverage_sufficient(
        actual_start_utc=datetime(2024, 12, 9, tzinfo=timezone.utc),
        actual_end_utc=datetime(2026, 4, 10, tzinfo=timezone.utc),
        requested_start_utc=datetime(2020, 6, 1, tzinfo=timezone.utc),
        requested_end_utc=datetime(2026, 4, 10, tzinfo=timezone.utc),
    )


def test_coverage_sufficient_rejects_large_end_gap() -> None:
    assert not is_coverage_sufficient(
        actual_start_utc=datetime(2025, 1, 1, tzinfo=timezone.utc),
        actual_end_utc=datetime(2025, 6, 1, tzinfo=timezone.utc),
        requested_start_utc=datetime(2025, 1, 1, tzinfo=timezone.utc),
        requested_end_utc=datetime(2025, 6, 15, tzinfo=timezone.utc),
    )


def test_describe_coverage_gap_shows_both_ends() -> None:
    description = describe_coverage_gap(
        actual_start_utc=datetime(2024, 12, 9, tzinfo=timezone.utc),
        actual_end_utc=datetime(2026, 4, 10, tzinfo=timezone.utc),
        requested_start_utc=datetime(2020, 6, 1, tzinfo=timezone.utc),
        requested_end_utc=datetime(2026, 4, 15, tzinfo=timezone.utc),
    )

    assert "start gap" in description
    assert "end gap" in description


def test_market_data_validator_accepts_tolerated_recent_end_gap_for_coarse_timeframe(tmp_path: Path) -> None:
    store = FilesystemHistoricalDataStore(source_cache_root=tmp_path)
    frame = pd.DataFrame(
        {
            "open": [42000.0, 42010.0],
            "high": [42020.0, 42030.0],
            "low": [41990.0, 42000.0],
            "close": [42010.0, 42020.0],
            "volume": [10.0, 12.0],
        },
        index=pd.to_datetime(["2026-04-09T18:00:00Z", "2026-04-09T22:00:00Z"], utc=True),
    )
    store.save_source_slice(
        manifest=build_manifest(
            store,
            provider_id="ib",
            source_system=DatasetSource.IB,
            canonical_symbol="YM",
            timeframe="4h",
            instrument_metadata={"tick_size": 1.0, "instrument_type": "FUTURES"},
        ).model_copy(
            update={
                "requested_start_utc": datetime(2026, 4, 9, 18, 0, tzinfo=timezone.utc),
                "requested_end_utc": datetime(2026, 4, 9, 23, 59, 59, 999999, tzinfo=timezone.utc),
                "actual_start_utc": datetime(2026, 4, 9, 18, 0, tzinfo=timezone.utc),
                "actual_end_utc": datetime(2026, 4, 9, 22, 0, tzinfo=timezone.utc),
            }
        ),
        frame=frame,
    )

    validation = MarketDataValidator(store=store).validate_slice(
        provider_id="ib",
        canonical_symbol="YM",
        timeframe="4h",
    )

    assert validation.verification_verdict == "PASS"
    assert all(issue.code != "requested_end_not_covered" for issue in validation.issues)


def test_market_data_validator_accepts_fx_slice_when_requested_start_is_during_weekend_closure(
    tmp_path: Path,
) -> None:
    store = FilesystemHistoricalDataStore(source_cache_root=tmp_path)
    frame = pd.DataFrame(
        {
            "open": [1.1010, 1.1015],
            "high": [1.1020, 1.1025],
            "low": [1.1005, 1.1010],
            "close": [1.1015, 1.1020],
            "volume": [10.0, 11.0],
        },
        index=pd.to_datetime(["2025-06-01T21:00:00Z", "2025-06-01T21:15:00Z"], utc=True),
    )
    store.save_source_slice(
        manifest=build_manifest(
            store,
            provider_id="mt5",
            source_system=DatasetSource.MT5,
            canonical_symbol="EURUSD",
            timeframe="15m",
            instrument_metadata={"tick_size": 0.00001, "instrument_type": "CURRENCY_PAIR"},
        ).model_copy(
            update={
                "requested_start_utc": datetime(2025, 6, 1, 0, 0, tzinfo=timezone.utc),
                "requested_end_utc": datetime(2025, 6, 1, 21, 15, tzinfo=timezone.utc),
                "actual_start_utc": datetime(2025, 6, 1, 21, 0, tzinfo=timezone.utc),
                "actual_end_utc": datetime(2025, 6, 1, 21, 15, tzinfo=timezone.utc),
            }
        ),
        frame=frame,
    )

    validation = MarketDataValidator(store=store).validate_slice(
        provider_id="mt5",
        canonical_symbol="EURUSD",
        timeframe="15m",
    )

    assert validation.verification_verdict == "PASS"
    assert all(issue.code != "requested_start_not_covered" for issue in validation.issues)


def test_path_integrity_check_uses_normalized_canonical_comparison(tmp_path: Path) -> None:
    store = FilesystemHistoricalDataStore(source_cache_root=tmp_path)
    manifest = store.save_source_slice(
        manifest=build_manifest(
            store,
            provider_id="mt5",
            source_system=DatasetSource.MT5,
            canonical_symbol="EURUSD",
            timeframe="30m",
        ),
        frame=build_frame(),
    )
    canonical = store.canonical_bars_path("mt5", "EURUSD", "30m")
    normalized_variant = canonical.parent / "." / canonical.name
    rewritten = manifest.model_copy(update={"bars_path": normalized_variant})
    store.source_manifest_path("mt5", "EURUSD", "30m").write_text(
        rewritten.model_dump_json(indent=2),
        encoding="utf-8",
    )

    validation = MarketDataValidator(store=store).validate_slice(
        provider_id="mt5",
        canonical_symbol="EURUSD",
        timeframe="30m",
    )

    assert all(issue.code != "non_canonical_bars_path" for issue in validation.issues)


def test_source_path_matches_legacy_repo_relative_manifest_path(tmp_path: Path) -> None:
    source_root = tmp_path / "data" / "cache"
    store = FilesystemHistoricalDataStore(source_cache_root=source_root)

    assert store.source_path_matches_canonical(
        provider_id="mt5",
        canonical_symbol="EURUSD",
        timeframe="30m",
        bars_path=Path("data/cache/mt5/EURUSD/30m/bars.parquet"),
    )


def test_saved_source_manifest_uses_absolute_canonical_bars_path(tmp_path: Path) -> None:
    source_root = tmp_path / "data" / "cache"
    store = FilesystemHistoricalDataStore(source_cache_root=source_root)
    saved = store.save_source_slice(
        manifest=build_manifest(
            store,
            provider_id="mt5",
            source_system=DatasetSource.MT5,
            canonical_symbol="EURUSD",
            timeframe="30m",
        ),
        frame=build_frame(),
    )

    assert saved.bars_path.is_absolute()
    assert saved.bars_path == store.canonical_bars_path("mt5", "EURUSD", "30m")


def test_saved_source_manifest_recomputes_actual_window_and_row_count_from_saved_frame(tmp_path: Path) -> None:
    store = FilesystemHistoricalDataStore(source_cache_root=tmp_path)
    frame = pd.DataFrame(
        {
            "open": [1.1010, 1.1015, 1.1020],
            "high": [1.1020, 1.1025, 1.1030],
            "low": [1.1005, 1.1010, 1.1015],
            "close": [1.1015, 1.1020, 1.1025],
            "volume": [10.0, 11.0, 12.0],
        },
        index=pd.to_datetime(
            [
                "2025-06-01T21:30:00Z",
                "2025-06-01T21:00:00Z",
                "2025-06-01T21:15:00Z",
            ],
            utc=True,
        ),
    )

    saved = store.save_source_slice(
        manifest=build_manifest(
            store,
            provider_id="mt5",
            source_system=DatasetSource.MT5,
            canonical_symbol="EURUSD",
            timeframe="15m",
        ).model_copy(
            update={
                "actual_start_utc": datetime(2024, 1, 1, tzinfo=timezone.utc),
                "actual_end_utc": datetime(2024, 1, 2, tzinfo=timezone.utc),
                "row_count": 999,
            }
        ),
        frame=frame,
    )

    assert saved.actual_start_utc == datetime(2025, 6, 1, 21, 0, tzinfo=timezone.utc)
    assert saved.actual_end_utc == datetime(2025, 6, 1, 21, 30, tzinfo=timezone.utc)
    assert saved.row_count == 3


def test_has_complete_verified_slice_accepts_expected_start_gap_after_pass_validation(
    tmp_path: Path,
) -> None:
    store = FilesystemHistoricalDataStore(source_cache_root=tmp_path)
    requested_start = datetime(2025, 6, 1, 0, 0, tzinfo=timezone.utc)
    requested_end = datetime(2025, 6, 1, 21, 15, tzinfo=timezone.utc)
    frame = pd.DataFrame(
        {
            "open": [1.1010, 1.1015],
            "high": [1.1020, 1.1025],
            "low": [1.1005, 1.1010],
            "close": [1.1015, 1.1020],
            "volume": [10.0, 11.0],
        },
        index=pd.to_datetime(["2025-06-01T21:00:00Z", "2025-06-01T21:15:00Z"], utc=True),
    )
    store.save_source_slice(
        manifest=build_manifest(
            store,
            provider_id="mt5",
            source_system=DatasetSource.MT5,
            canonical_symbol="EURUSD",
            timeframe="15m",
            instrument_metadata={"tick_size": 0.00001, "instrument_type": "CURRENCY_PAIR"},
        ).model_copy(
            update={
                "requested_start_utc": requested_start,
                "requested_end_utc": requested_end,
                "actual_start_utc": datetime(2024, 1, 1, tzinfo=timezone.utc),
                "actual_end_utc": datetime(2024, 1, 2, tzinfo=timezone.utc),
            }
        ),
        frame=frame,
    )

    validation = MarketDataValidator(store=store).validate_slice(
        provider_id="mt5",
        canonical_symbol="EURUSD",
        timeframe="15m",
    )

    assert validation.verification_verdict == "PASS"
    assert (
        store.has_complete_verified_slice(
            provider_id="mt5",
            canonical_symbol="EURUSD",
            timeframe="15m",
            requested_start_utc=requested_start,
            requested_end_utc=requested_end,
            validator_ruleset_version=MARKET_DATA_VALIDATOR_RULESET_VERSION,
        )
        is True
    )


def test_has_complete_verified_slice_accepts_tolerated_end_gap_after_pass_validation(
    tmp_path: Path,
) -> None:
    store = FilesystemHistoricalDataStore(source_cache_root=tmp_path)
    requested_start = datetime(2026, 4, 9, 18, 0, tzinfo=timezone.utc)
    requested_end = datetime(2026, 4, 9, 23, 59, 59, 999999, tzinfo=timezone.utc)
    frame = pd.DataFrame(
        {
            "open": [42000.0, 42010.0],
            "high": [42020.0, 42030.0],
            "low": [41990.0, 42000.0],
            "close": [42010.0, 42020.0],
            "volume": [10.0, 12.0],
        },
        index=pd.to_datetime(["2026-04-09T18:00:00Z", "2026-04-09T22:00:00Z"], utc=True),
    )
    store.save_source_slice(
        manifest=build_manifest(
            store,
            provider_id="ib",
            source_system=DatasetSource.IB,
            canonical_symbol="YM",
            timeframe="4h",
            instrument_metadata={"tick_size": 1.0, "instrument_type": "FUTURES"},
        ).model_copy(
            update={
                "requested_start_utc": requested_start,
                "requested_end_utc": requested_end,
                "actual_start_utc": datetime(2024, 1, 1, tzinfo=timezone.utc),
                "actual_end_utc": datetime(2024, 1, 2, tzinfo=timezone.utc),
            }
        ),
        frame=frame,
    )

    validation = MarketDataValidator(store=store).validate_slice(
        provider_id="ib",
        canonical_symbol="YM",
        timeframe="4h",
    )

    assert validation.verification_verdict == "PASS"
    assert (
        store.has_complete_verified_slice(
            provider_id="ib",
            canonical_symbol="YM",
            timeframe="4h",
            requested_start_utc=requested_start,
            requested_end_utc=requested_end,
            validator_ruleset_version=MARKET_DATA_VALIDATOR_RULESET_VERSION,
        )
        is True
    )
