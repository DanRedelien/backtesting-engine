from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from backtest_engine.core.enums import DatasetSource
from backtest_engine.infrastructure.data import (
    FilesystemHistoricalDataStore,
    MarketDataValidator,
    RollAdjustmentEvent,
    VerificationFailedError,
)
from backtest_engine.infrastructure.data.verification_checks import check_return_anomalies
from backtest_engine.infrastructure.data.market_data_contracts import ValidationCheckResult
from backtest_engine.infrastructure.data.verification_results import (
    CheckOutcome,
    build_issue,
    build_score_summary,
)

from _market_data_pipeline_support import build_frame, build_manifest, save_roll_adjusted_slice


def test_market_data_validator_returns_pass_with_warning_issue(tmp_path: Path) -> None:
    store = FilesystemHistoricalDataStore(source_cache_root=tmp_path)
    frame = pd.DataFrame(
        {
            "open": [1.001, 1.011],
            "high": [1.101, 1.111],
            "low": [0.901, 0.911],
            "close": [1.051, 1.061],
            "volume": [10.0, 10.0],
        },
        index=pd.to_datetime(["2024-01-01T00:00:00Z", "2024-01-01T00:30:00Z"], utc=True),
    )
    manifest = store.save_source_slice(
        manifest=build_manifest(
            store,
            provider_id="mt5",
            source_system=DatasetSource.MT5,
            canonical_symbol="XAUUSD",
            timeframe="30m",
            instrument_metadata={"tick_size": 0.01, "instrument_type": "CFD"},
        ),
        frame=frame,
    )

    validation = MarketDataValidator(store=store).validate_slice(
        provider_id="mt5",
        canonical_symbol="XAUUSD",
        timeframe="30m",
    )

    assert validation.source_fingerprint == manifest.source_fingerprint
    assert validation.verification_verdict == "PASS"
    assert validation.warning_count >= 1
    tick_alignment = next(item for item in validation.check_results if item.check_code == "tick_alignment")
    assert tick_alignment.check_status == "WARN"
    assert validation.score_summary is not None
    assert validation.score_summary.warning_check_count >= 1


def test_market_data_validator_keeps_fail_verdict_even_when_overall_score_is_high(tmp_path: Path) -> None:
    store = FilesystemHistoricalDataStore(source_cache_root=tmp_path)
    frame = pd.DataFrame(
        {
            "open": [1.0, 1.1],
            "low": [0.9, 1.0],
            "close": [1.05, 1.15],
            "volume": [10.0, 11.0],
        },
        index=pd.to_datetime(["2024-01-01T00:00:00Z", "2024-01-01T00:30:00Z"], utc=True),
    )
    store.save_source_slice(
        manifest=build_manifest(
            store,
            provider_id="mt5",
            source_system=DatasetSource.MT5,
            canonical_symbol="EURUSD",
            timeframe="30m",
        ),
        frame=frame,
    )

    with pytest.raises(VerificationFailedError):
        MarketDataValidator(store=store).validate_slice(
            provider_id="mt5",
            canonical_symbol="EURUSD",
            timeframe="30m",
        )

    manifest = store.load_validation_manifest("mt5", "EURUSD", "30m")
    assert manifest is not None
    assert manifest.verification_verdict == "FAIL"
    assert manifest.score_summary is not None
    assert manifest.score_summary.overall_score_pct is not None
    assert manifest.score_summary.overall_score_pct > 0.0


def test_market_data_validator_persists_fail_manifest_for_missing_required_columns(tmp_path: Path) -> None:
    store = FilesystemHistoricalDataStore(source_cache_root=tmp_path)
    frame = pd.DataFrame(
        {
            "open": [1.0, 1.1],
            "low": [0.9, 1.0],
            "close": [1.05, 1.15],
            "volume": [10.0, 11.0],
        },
        index=pd.to_datetime(["2024-01-01T00:00:00Z", "2024-01-01T00:30:00Z"], utc=True),
    )
    store.save_source_slice(
        manifest=build_manifest(
            store,
            provider_id="mt5",
            source_system=DatasetSource.MT5,
            canonical_symbol="EURUSD",
            timeframe="30m",
        ),
        frame=frame,
    )

    with pytest.raises(VerificationFailedError):
        MarketDataValidator(store=store).validate_slice(
            provider_id="mt5",
            canonical_symbol="EURUSD",
            timeframe="30m",
        )

    manifest = store.load_validation_manifest("mt5", "EURUSD", "30m")
    assert manifest is not None
    assert manifest.verification_verdict == "FAIL"
    assert any(issue.code == "missing_required_columns" for issue in manifest.issues)


def test_market_data_validator_fails_non_finite_ohlcv_values(tmp_path: Path) -> None:
    store = FilesystemHistoricalDataStore(source_cache_root=tmp_path)
    frame = pd.DataFrame(
        {
            "open": [1.0, float("nan")],
            "high": [1.2, 1.3],
            "low": [0.9, 1.0],
            "close": [1.1, 1.2],
            "volume": [10.0, float("inf")],
        },
        index=pd.to_datetime(["2024-01-01T00:00:00Z", "2024-01-01T00:30:00Z"], utc=True),
    )
    store.save_source_slice(
        manifest=build_manifest(
            store,
            provider_id="mt5",
            source_system=DatasetSource.MT5,
            canonical_symbol="EURUSD",
            timeframe="30m",
        ),
        frame=frame,
    )

    with pytest.raises(VerificationFailedError):
        MarketDataValidator(store=store).validate_slice(
            provider_id="mt5",
            canonical_symbol="EURUSD",
            timeframe="30m",
        )

    manifest = store.load_validation_manifest("mt5", "EURUSD", "30m")
    assert manifest is not None
    assert manifest.verification_verdict == "FAIL"
    assert any(issue.code == "non_finite_ohlcv" for issue in manifest.issues)
    finite_check = next(item for item in manifest.check_results if item.check_code == "finite_ohlcv")
    assert finite_check.check_status == "BAD"


def test_market_data_validator_treats_invalid_calendar_policy_as_typed_failure(tmp_path: Path) -> None:
    store = FilesystemHistoricalDataStore(source_cache_root=tmp_path)
    store.save_source_slice(
        manifest=build_manifest(
            store,
            provider_id="mt5",
            source_system=DatasetSource.MT5,
            canonical_symbol="EURUSD",
            timeframe="30m",
        ).model_copy(update={"calendar_id": "UNKNOWN_CALENDAR"}),
        frame=build_frame(),
    )

    with pytest.raises(VerificationFailedError):
        MarketDataValidator(store=store).validate_slice(
            provider_id="mt5",
            canonical_symbol="EURUSD",
            timeframe="30m",
        )

    manifest = store.load_validation_manifest("mt5", "EURUSD", "30m")
    assert manifest is not None
    assert any(issue.code == "invalid_calendar_policy" for issue in manifest.issues)


def test_roll_audit_mismatch_fails_verification(tmp_path: Path) -> None:
    store = FilesystemHistoricalDataStore(source_cache_root=tmp_path)
    adjusted = pd.DataFrame(
        {
            "open": [100.0, 100.0],
            "high": [101.0, 101.0],
            "low": [99.0, 99.0],
            "close": [100.5, 100.5],
            "volume": [1.0, 1.0],
            "contract": ["OLD", "NEW"],
        },
        index=pd.to_datetime(["2024-03-07T00:00:00Z", "2024-03-14T00:00:00Z"], utc=True),
    )
    raw_contract_frames = {
        "OLD": pd.DataFrame(
            {"open": [80.0], "high": [81.0], "low": [79.0], "close": [80.5], "volume": [1.0]},
            index=pd.to_datetime(["2024-03-07T00:00:00Z"], utc=True),
        ),
        "NEW": pd.DataFrame(
            {"open": [90.0], "high": [91.0], "low": [89.0], "close": [90.5], "volume": [1.0]},
            index=pd.to_datetime(["2024-03-14T00:00:00Z"], utc=True),
        ),
    }
    save_roll_adjusted_slice(
        store,
        canonical_symbol="ES",
        timeframe="1h",
        adjusted_frame=adjusted,
        raw_contract_frames=raw_contract_frames,
        events=(
            RollAdjustmentEvent(
                roll_time_utc=raw_contract_frames["NEW"].index.min().to_pydatetime(),
                outgoing_contract="OLD",
                incoming_contract="NEW",
                outgoing_close_raw=80.5,
                incoming_open_raw=90.0,
                additive_adjustment=99.0,
                cumulative_adjustment=99.0,
            ),
        ),
    )

    with pytest.raises(VerificationFailedError):
        MarketDataValidator(store=store).validate_slice(
            provider_id="ib",
            canonical_symbol="ES",
            timeframe="1h",
        )


def test_cme_maintenance_gap_does_not_emit_suspicious_gap_warning(tmp_path: Path) -> None:
    store = FilesystemHistoricalDataStore(source_cache_root=tmp_path)
    frame = pd.DataFrame(
        {
            "open": [5000.0, 5000.25],
            "high": [5000.25, 5000.5],
            "low": [4999.75, 5000.0],
            "close": [5000.0, 5000.25],
            "volume": [10.0, 11.0],
        },
        index=pd.to_datetime(["2024-01-08T21:55:00Z", "2024-01-08T23:00:00Z"], utc=True),
    )
    store.save_source_slice(
        manifest=build_manifest(
            store,
            provider_id="ib",
            source_system=DatasetSource.IB,
            canonical_symbol="ES",
            timeframe="5m",
            frame=frame,
            instrument_metadata={"tick_size": 0.25, "instrument_type": "FUTURES"},
        ),
        frame=frame,
    )

    validation = MarketDataValidator(store=store).validate_slice(
        provider_id="ib",
        canonical_symbol="ES",
        timeframe="5m",
    )

    assert validation.verification_verdict == "PASS"
    assert all(issue.code != "suspicious_gaps" for issue in validation.issues)


def test_futures_tick_alignment_failure_is_persisted(tmp_path: Path) -> None:
    store = FilesystemHistoricalDataStore(source_cache_root=tmp_path)
    frame = pd.DataFrame(
        {
            "open": [5000.1, 5000.35],
            "high": [5000.35, 5000.6],
            "low": [4999.85, 5000.1],
            "close": [5000.2, 5000.45],
            "volume": [10.0, 11.0],
        },
        index=pd.to_datetime(["2024-01-08T21:55:00Z", "2024-01-08T22:00:00Z"], utc=True),
    )
    store.save_source_slice(
        manifest=build_manifest(
            store,
            provider_id="ib",
            source_system=DatasetSource.IB,
            canonical_symbol="ES",
            timeframe="5m",
            frame=frame,
            instrument_metadata={"tick_size": 0.25, "instrument_type": "FUTURES"},
        ),
        frame=frame,
    )

    with pytest.raises(VerificationFailedError):
        MarketDataValidator(store=store).validate_slice(
            provider_id="ib",
            canonical_symbol="ES",
            timeframe="5m",
        )

    manifest = store.load_validation_manifest("ib", "ES", "5m")
    assert manifest is not None
    assert any(issue.code == "futures_tick_alignment" for issue in manifest.issues)


def test_roll_adjustment_tick_alignment_failure_is_persisted(tmp_path: Path) -> None:
    store = FilesystemHistoricalDataStore(source_cache_root=tmp_path)
    adjusted = pd.DataFrame(
        {
            "open": [100.25, 100.25],
            "high": [100.5, 100.5],
            "low": [100.0, 100.0],
            "close": [100.25, 100.25],
            "volume": [1.0, 1.0],
            "contract": ["OLD", "NEW"],
        },
        index=pd.to_datetime(["2024-03-07T00:00:00Z", "2024-03-14T00:00:00Z"], utc=True),
    )
    raw_contract_frames = {
        "OLD": pd.DataFrame(
            {"open": [100.15], "high": [100.15], "low": [100.15], "close": [100.15], "volume": [1.0]},
            index=pd.to_datetime(["2024-03-07T00:00:00Z"], utc=True),
        ),
        "NEW": pd.DataFrame(
            {"open": [100.25], "high": [100.25], "low": [100.25], "close": [100.25], "volume": [1.0]},
            index=pd.to_datetime(["2024-03-14T00:00:00Z"], utc=True),
        ),
    }
    save_roll_adjusted_slice(
        store,
        canonical_symbol="ES",
        timeframe="1h",
        adjusted_frame=adjusted,
        raw_contract_frames=raw_contract_frames,
        instrument_metadata={"tick_size": 0.25, "instrument_type": "FUTURES"},
        events=(
            RollAdjustmentEvent(
                roll_time_utc=raw_contract_frames["NEW"].index.min().to_pydatetime(),
                outgoing_contract="OLD",
                incoming_contract="NEW",
                outgoing_close_raw=100.15,
                incoming_open_raw=100.25,
                additive_adjustment=0.1,
                cumulative_adjustment=0.1,
            ),
        ),
    )

    with pytest.raises(VerificationFailedError):
        MarketDataValidator(store=store).validate_slice(
            provider_id="ib",
            canonical_symbol="ES",
            timeframe="1h",
        )

    manifest = store.load_validation_manifest("ib", "ES", "1h")
    assert manifest is not None
    assert any(issue.code == "roll_adjustment_tick_alignment" for issue in manifest.issues)


def test_score_summary_excludes_na_checks_from_denominator() -> None:
    summary = build_score_summary(
        (
            ValidationCheckResult(check_code="a", check_status="NA"),
            ValidationCheckResult(check_code="b", check_status="OK", score_pct=100.0),
        )
    )

    assert summary.total_check_count == 2
    assert summary.applicable_check_count == 1
    assert summary.overall_score_pct == pytest.approx(100.0)


def test_score_summary_returns_na_when_no_checks_are_applicable() -> None:
    summary = build_score_summary((ValidationCheckResult(check_code="a", check_status="NA"),))

    assert summary.applicable_check_count == 0
    assert summary.overall_score_pct is None


def test_check_result_samples_are_truncated() -> None:
    result = CheckOutcome(
        check_code="path_integrity",
        issues=tuple(build_issue("FAIL", f"problem_{index}", "problem", index=index) for index in range(5)),
        score_pct=0.0,
    ).to_result()

    assert len(result.sample_details) == 3


def test_issue_details_preserve_typed_scalar_values() -> None:
    issue = build_issue("FAIL", "typed_details", "problem", count=1, ratio=1.5, flagged=True, note=None)

    assert issue.details == {
        "count": 1,
        "ratio": 1.5,
        "flagged": True,
        "note": None,
    }
    assert isinstance(issue.details["count"], int)
    assert isinstance(issue.details["ratio"], float)
    assert isinstance(issue.details["flagged"], bool)
    assert issue.details["note"] is None


def test_return_anomalies_do_not_forward_fill_missing_closes() -> None:
    frame = pd.DataFrame(
        {"close": [100.0, None, 101.0, 102.0]},
        index=pd.to_datetime(
            [
                "2024-01-01T00:00:00Z",
                "2024-01-01T00:30:00Z",
                "2024-01-01T01:00:00Z",
                "2024-01-01T01:30:00Z",
            ],
            utc=True,
        ),
    )

    result = check_return_anomalies(frame)

    assert result.check_code == "return_anomalies"
    assert result.checked_count == 1
    assert result.score_pct == 100.0


def test_roll_audit_missing_contract_column_emits_one_failure(tmp_path: Path) -> None:
    store = FilesystemHistoricalDataStore(source_cache_root=tmp_path)
    adjusted = pd.DataFrame(
        {
            "open": [100.0, 100.0],
            "high": [101.0, 101.0],
            "low": [99.0, 99.0],
            "close": [100.5, 100.5],
            "volume": [1.0, 1.0],
        },
        index=pd.to_datetime(["2024-03-07T00:00:00Z", "2024-03-14T00:00:00Z"], utc=True),
    )
    raw_contract_frames = {
        "OLD": pd.DataFrame(
            {"open": [80.0], "high": [81.0], "low": [79.0], "close": [80.5], "volume": [1.0]},
            index=pd.to_datetime(["2024-03-07T00:00:00Z"], utc=True),
        ),
        "NEW": pd.DataFrame(
            {"open": [90.0], "high": [91.0], "low": [89.0], "close": [90.5], "volume": [1.0]},
            index=pd.to_datetime(["2024-03-14T00:00:00Z"], utc=True),
        ),
    }
    save_roll_adjusted_slice(
        store,
        canonical_symbol="ES",
        timeframe="1h",
        adjusted_frame=adjusted,
        raw_contract_frames=raw_contract_frames,
        instrument_metadata={"tick_size": 0.25, "instrument_type": "FUTURES"},
        events=(
            RollAdjustmentEvent(
                roll_time_utc=raw_contract_frames["NEW"].index.min().to_pydatetime(),
                outgoing_contract="OLD",
                incoming_contract="NEW",
                outgoing_close_raw=80.5,
                incoming_open_raw=90.0,
                additive_adjustment=9.5,
                cumulative_adjustment=9.5,
            ),
            RollAdjustmentEvent(
                roll_time_utc=raw_contract_frames["NEW"].index.min().to_pydatetime(),
                outgoing_contract="OLD",
                incoming_contract="NEW2",
                outgoing_close_raw=80.5,
                incoming_open_raw=90.0,
                additive_adjustment=9.5,
                cumulative_adjustment=19.0,
            ),
        ),
    )

    with pytest.raises(VerificationFailedError):
        MarketDataValidator(store=store).validate_slice(
            provider_id="ib",
            canonical_symbol="ES",
            timeframe="1h",
        )

    manifest = store.load_validation_manifest("ib", "ES", "1h")
    assert manifest is not None
    missing_contract_issues = [issue for issue in manifest.issues if issue.code == "missing_contract_column"]
    assert len(missing_contract_issues) == 1
