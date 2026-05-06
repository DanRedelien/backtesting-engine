# mypy: disable-error-code=no-untyped-def
from __future__ import annotations

import pytest

from backtest_engine.interfaces.cli.market_data.__main__ import main

from _market_data_cli_support import FakeService, VerifyPartialFailureService


def test_market_data_cli_dry_run_hides_internal_max_available_start(
    monkeypatch,  # noqa: ANN001
    capsys: pytest.CaptureFixture[str],
) -> None:
    service = FakeService()
    monkeypatch.setattr(
        "backtest_engine.interfaces.cli.market_data.__main__.build_market_data_service",
        lambda settings, diagnostics=None: service,
    )

    exit_code = main(
        [
            "download",
            "historical-market-data",
            "--provider",
            "mt5",
            "--symbols",
            "EURUSD",
            "--timeframes",
            "5m",
            "--dry-run",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "window_mode: max_available" in captured.out
    assert "requested_window: max_available .. 2026-04-15T12:00:00+00:00" in captured.out
    assert "1970-01-01" not in captured.out


def test_market_data_cli_verify_prints_compact_report_by_default(
    monkeypatch,  # noqa: ANN001
    capsys: pytest.CaptureFixture[str],
) -> None:
    service = FakeService()
    monkeypatch.setattr(
        "backtest_engine.interfaces.cli.market_data.__main__.build_market_data_service",
        lambda settings, diagnostics=None: service,
    )

    exit_code = main(
        [
            "verify",
            "market-data",
            "--provider",
            "mt5",
            "--symbols",
            "EURUSD",
            "--timeframes",
            "5m",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS mt5 EURUSD 5m score=87.50% warn=1 bad=0 checks=tick_alignment" in captured.out
    assert "Required columns: 100.00% OK" not in captured.out


def test_market_data_cli_verify_prints_detailed_report(
    monkeypatch,  # noqa: ANN001
    capsys: pytest.CaptureFixture[str],
) -> None:
    service = FakeService()
    monkeypatch.setattr(
        "backtest_engine.interfaces.cli.market_data.__main__.build_market_data_service",
        lambda settings, diagnostics=None: service,
    )

    exit_code = main(
        [
            "verify",
            "market-data",
            "--provider",
            "mt5",
            "--symbols",
            "EURUSD",
            "--timeframes",
            "5m",
            "--detailed",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "mt5 EURUSD 5m 2024-01-01T00:00:00+00:00 .. 2024-01-02T00:00:00+00:00: PASS" in captured.out
    assert "Required columns: 100.00% OK" in captured.out
    assert "Tick alignment: 75.00% WARN" in captured.out
    assert "Overall score: 87.50%" in captured.out


def test_market_data_cli_verify_partial_failure_prints_all_slices(
    monkeypatch,  # noqa: ANN001
    capsys: pytest.CaptureFixture[str],
) -> None:
    service = VerifyPartialFailureService()
    monkeypatch.setattr(
        "backtest_engine.interfaces.cli.market_data.__main__.build_market_data_service",
        lambda settings, diagnostics=None: service,
    )

    exit_code = main(
        [
            "verify",
            "market-data",
            "--provider",
            "mt5",
            "--symbols",
            "EURUSD",
            "GBPUSD",
            "--timeframes",
            "5m",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "PASS mt5 EURUSD 5m score=87.50% warn=1 bad=0 checks=tick_alignment" in captured.out
    assert "FAIL mt5 GBPUSD 5m score=80.00% warn=0 bad=1 checks=required_columns error=VerificationFailedError" in captured.out
