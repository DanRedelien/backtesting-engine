# mypy: disable-error-code=no-untyped-def
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backtest_engine.interfaces.cli.market_data.__main__ import main

from _market_data_cli_support import FakeService, PartialFailureService


def test_market_data_cli_download_invokes_service(monkeypatch) -> None:  # noqa: ANN001
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
            "--start",
            "2024-01-01",
            "--end",
            "2024-01-02",
        ]
    )

    assert exit_code == 0
    assert service.download_requests[0].symbol_universe == ("EURUSD",)
    assert service.download_requests[0].timeframes == ("5m",)
    assert service.download_requests[0].start_utc == datetime(2024, 1, 1, tzinfo=timezone.utc)
    assert service.download_requests[0].end_utc == datetime(2024, 1, 2, 23, 59, 59, 999999, tzinfo=timezone.utc)


def test_market_data_cli_download_without_dates_requests_max_available(monkeypatch) -> None:  # noqa: ANN001
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
        ]
    )

    assert exit_code == 0
    assert service.download_requests[0].start_utc is None
    assert service.download_requests[0].end_utc is None


def test_market_data_cli_verify_invokes_service(monkeypatch) -> None:  # noqa: ANN001
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

    assert exit_code == 0
    assert service.verify_requests[0].symbol_universe == ("EURUSD",)


def test_market_data_cli_requires_nested_command() -> None:
    assert main(["download"]) == 2
    assert main(["verify"]) == 2


def test_market_data_cli_rejects_future_ib_end(monkeypatch, capsys: pytest.CaptureFixture[str]) -> None:  # noqa: ANN001
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
            "ib",
            "--symbols",
            "ES",
            "--timeframes",
            "1h",
            "--start",
            "2024-01-01",
            "--end",
            "2999-01-01",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert service.download_requests == []
    assert "ApplicationError" in captured.out


def test_market_data_cli_requires_both_window_edges_or_neither(
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
            "--start",
            "2024-01-01",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert service.download_requests == []
    assert "ApplicationError" in captured.out


def test_market_data_cli_exits_nonzero_on_partial_batch_failure(
    monkeypatch,  # noqa: ANN001
    capsys: pytest.CaptureFixture[str],
) -> None:
    service = PartialFailureService()
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
            "BAD",
            "--timeframes",
            "5m",
            "--start",
            "2024-01-01",
            "--end",
            "2024-01-02",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "downloaded" in captured.out
    assert "FAILED" in captured.out
    assert "SymbolMappingError" in captured.out
    assert "BAD/5m" in captured.out
