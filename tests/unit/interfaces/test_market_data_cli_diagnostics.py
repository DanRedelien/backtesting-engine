# mypy: disable-error-code=no-untyped-def
from __future__ import annotations

from typing import Literal

import pytest

from backtest_engine.infrastructure.observability import StageDiagnosticEvent
from backtest_engine.interfaces.cli.market_data.diagnostics import TerminalMarketDataDiagnosticsSink

from _market_data_cli_support import TtyStringIO, progress_event


def test_terminal_market_data_diagnostics_sink_prints_compact_progress_line(
    capsys: pytest.CaptureFixture[str],
) -> None:
    sink = TerminalMarketDataDiagnosticsSink()

    sink.emit(
        StageDiagnosticEvent(
            stage="market_data.batch.download",
            status="started",
            message="start batch",
            requested_by="cli",
            details={"provider_id": "mt5", "total_slices": 2},
        )
    )
    sink.emit(
        StageDiagnosticEvent(
            stage="market_data.slice.download",
            status="started",
            message="start slice",
            requested_by="cli",
            details={
                "provider_id": "mt5",
                "canonical_symbol": "EURUSD",
                "timeframe": "5m",
                "completed_slices": 0,
                "total_slices": 2,
            },
        )
    )
    sink.emit(progress_event())

    captured = capsys.readouterr()
    assert "PROGRESS mt5 EURUSD 5m  50.0% rows=1,200 date=2020-06-10 left=1m30s" in captured.out


def test_terminal_market_data_diagnostics_sink_aggregates_errors_at_batch_end(
    capsys: pytest.CaptureFixture[str],
) -> None:
    sink = TerminalMarketDataDiagnosticsSink()

    sink.emit(
        StageDiagnosticEvent(
            stage="market_data.batch.download",
            status="started",
            message="start",
            requested_by="cli",
            details={"provider_id": "ib", "total_slices": 3},
        )
    )
    for symbol in ("ES", "NQ"):
        sink.emit(
            StageDiagnosticEvent(
                stage="market_data.slice.download",
                status="failed",
                message="failed",
                requested_by="cli",
                details={
                    "provider_id": "ib",
                    "canonical_symbol": symbol,
                    "timeframe": "1m",
                    "slice_status": "failed",
                    "completed_slices": 1,
                    "total_slices": 3,
                    "error_type": "InsufficientHistoryError",
                    "error_message": "IB could not cover the requested window",
                    "error_context": '{"actual_end": "2026-04-10"}',
                },
            )
        )
    sink.emit(
        StageDiagnosticEvent(
            stage="market_data.batch.download",
            status="failed",
            message="done",
            requested_by="cli",
            details={"completed_slices": 3, "failed_slices": 2},
        )
    )

    captured = capsys.readouterr()
    assert "ERR [2x]" in captured.out
    assert "ES/1m" in captured.out
    assert "NQ/1m" in captured.out
    assert "actual_end" in captured.out
    assert "FAILED batch 3/3 slices (ok=1, failed=2) total=" in captured.out


def test_terminal_market_data_diagnostics_sink_hides_unstable_early_left(
    capsys: pytest.CaptureFixture[str],
) -> None:
    sink = TerminalMarketDataDiagnosticsSink()

    sink.emit(
        progress_event(
            provider_id="ib",
            canonical_symbol="ES",
            timeframe="1m",
            progress_pct=57.1,
            row_count=35001,
            elapsed_sec=0.8,
            eta_sec=0.2,
            requested_start_utc=None,
            requested_end_utc=None,
            actual_start_utc=None,
            actual_end_utc=None,
        )
    )

    captured = capsys.readouterr()
    assert "PROGRESS ib ES 1m  57.1% rows=35,001 date=-- left=--" in captured.out


def test_terminal_market_data_diagnostics_sink_never_emits_carriage_returns_on_tty() -> None:
    stream = TtyStringIO()
    sink = TerminalMarketDataDiagnosticsSink(stream=stream)

    sink.emit(
        StageDiagnosticEvent(
            stage="market_data.batch.download",
            status="started",
            message="start batch",
            requested_by="cli",
            details={"provider_id": "mt5", "total_slices": 1},
        )
    )
    sink.emit(
        StageDiagnosticEvent(
            stage="market_data.slice.download",
            status="started",
            message="start slice",
            requested_by="cli",
            details={
                "provider_id": "mt5",
                "canonical_symbol": "EURUSD",
                "timeframe": "5m",
                "completed_slices": 0,
                "total_slices": 1,
            },
        )
    )
    sink.emit(progress_event())

    output = stream.getvalue()
    assert "\r" not in output
    assert "PROGRESS mt5 EURUSD 5m" in output


def test_terminal_market_data_diagnostics_sink_keeps_last_stable_left_when_eta_turns_unstable(
    capsys: pytest.CaptureFixture[str],
) -> None:
    sink = TerminalMarketDataDiagnosticsSink()

    sink.emit(
        StageDiagnosticEvent(
            stage="market_data.batch.download",
            status="started",
            message="start batch",
            requested_by="cli",
            details={"provider_id": "mt5", "total_slices": 1},
        )
    )
    sink.emit(progress_event(progress_pct=50.0, elapsed_sec=30.0, eta_sec=30.0))
    sink.emit(progress_event(progress_pct=51.5, elapsed_sec=31.0, eta_sec=0.5))

    captured = capsys.readouterr()
    assert "PROGRESS mt5 EURUSD 5m  50.0% rows=1,200 date=2020-06-10 left=0m30s" in captured.out
    assert "PROGRESS mt5 EURUSD 5m  51.5% rows=1,200 date=2020-06-10 left=0m30s" in captured.out
    assert "left=--" not in captured.out


def test_terminal_market_data_diagnostics_sink_excludes_skipped_slices_from_batch_left(
    monkeypatch,  # noqa: ANN001
    capsys: pytest.CaptureFixture[str],
) -> None:
    timestamps = iter((100.0, 101.0, 121.0, 122.0, 127.0, 128.0, 129.0))
    monkeypatch.setattr(
        "backtest_engine.interfaces.cli.market_data.diagnostics.perf_counter",
        lambda: next(timestamps),
    )
    sink = TerminalMarketDataDiagnosticsSink()

    sink.emit(
        StageDiagnosticEvent(
            stage="market_data.batch.download",
            status="started",
            message="start batch",
            requested_by="cli",
            details={"provider_id": "mt5", "total_slices": 4},
        )
    )
    sink.emit(
        StageDiagnosticEvent(
            stage="market_data.slice.download",
            status="started",
            message="start slice",
            requested_by="cli",
            details={
                "provider_id": "mt5",
                "canonical_symbol": "EURUSD",
                "timeframe": "5m",
                "completed_slices": 0,
                "total_slices": 4,
            },
        )
    )
    sink.emit(progress_event(progress_pct=50.0, elapsed_sec=10.0, eta_sec=10.0))
    sink.emit(
        StageDiagnosticEvent(
            stage="market_data.slice.download",
            status="succeeded",
            message="done slice",
            requested_by="cli",
            details={
                "provider_id": "mt5",
                "canonical_symbol": "EURUSD",
                "timeframe": "5m",
                "slice_status": "downloaded",
                "completed_slices": 1,
                "total_slices": 4,
            },
        )
    )
    sink.emit(
        StageDiagnosticEvent(
            stage="market_data.slice.download",
            status="started",
            message="start skipped slice",
            requested_by="cli",
            details={
                "provider_id": "mt5",
                "canonical_symbol": "GBPUSD",
                "timeframe": "5m",
                "completed_slices": 1,
                "total_slices": 4,
            },
        )
    )
    sink.emit(
        StageDiagnosticEvent(
            stage="market_data.slice.download",
            status="succeeded",
            message="done skipped slice",
            requested_by="cli",
            details={
                "provider_id": "mt5",
                "canonical_symbol": "GBPUSD",
                "timeframe": "5m",
                "slice_status": "skipped",
                "completed_slices": 2,
                "total_slices": 4,
            },
        )
    )
    sink.emit(progress_event(canonical_symbol="USDJPY", progress_pct=50.0, elapsed_sec=10.0, eta_sec=10.0))

    captured = capsys.readouterr()
    assert "PROGRESS mt5 USDJPY 5m  50.0% rows=1,200 date=2020-06-10 left=0m31s" in captured.out


def test_terminal_market_data_diagnostics_sink_throttles_small_progress_updates(
    monkeypatch,  # noqa: ANN001
) -> None:
    timestamps = iter((100.0, 101.0, 102.0, 103.0, 104.0))
    monkeypatch.setattr(
        "backtest_engine.interfaces.cli.market_data.diagnostics.perf_counter",
        lambda: next(timestamps),
    )
    stream = TtyStringIO()
    sink = TerminalMarketDataDiagnosticsSink(stream=stream)

    sink.emit(
        StageDiagnosticEvent(
            stage="market_data.batch.download",
            status="started",
            message="start batch",
            requested_by="cli",
            details={"provider_id": "mt5", "total_slices": 1},
        )
    )
    sink.emit(
        StageDiagnosticEvent(
            stage="market_data.slice.download",
            status="started",
            message="start slice",
            requested_by="cli",
            details={
                "provider_id": "mt5",
                "canonical_symbol": "EURUSD",
                "timeframe": "5m",
                "completed_slices": 0,
                "total_slices": 1,
            },
        )
    )
    sink.emit(progress_event(progress_pct=10.0, elapsed_sec=10.0, eta_sec=90.0))
    sink.emit(progress_event(progress_pct=10.5, elapsed_sec=11.0, eta_sec=89.0))
    sink.emit(progress_event(progress_pct=11.0, elapsed_sec=12.0, eta_sec=88.0))

    lines = [line for line in stream.getvalue().splitlines() if line.startswith("PROGRESS ")]
    assert len(lines) == 2
    assert " 10.0%" in lines[0]
    assert " 11.0%" in lines[1]


def test_terminal_market_data_diagnostics_sink_emits_after_five_seconds_without_one_percent_change(
    monkeypatch,  # noqa: ANN001
) -> None:
    timestamps = iter((100.0, 101.0, 102.0, 108.0))
    monkeypatch.setattr(
        "backtest_engine.interfaces.cli.market_data.diagnostics.perf_counter",
        lambda: next(timestamps),
    )
    stream = TtyStringIO()
    sink = TerminalMarketDataDiagnosticsSink(stream=stream)

    sink.emit(
        StageDiagnosticEvent(
            stage="market_data.batch.download",
            status="started",
            message="start batch",
            requested_by="cli",
            details={"provider_id": "mt5", "total_slices": 1},
        )
    )
    sink.emit(
        StageDiagnosticEvent(
            stage="market_data.slice.download",
            status="started",
            message="start slice",
            requested_by="cli",
            details={
                "provider_id": "mt5",
                "canonical_symbol": "EURUSD",
                "timeframe": "5m",
                "completed_slices": 0,
                "total_slices": 1,
            },
        )
    )
    sink.emit(progress_event(progress_pct=10.0, elapsed_sec=10.0, eta_sec=90.0))
    sink.emit(progress_event(progress_pct=10.5, elapsed_sec=16.0, eta_sec=84.0))

    lines = [line for line in stream.getvalue().splitlines() if line.startswith("PROGRESS ")]
    assert len(lines) == 2
    assert " 10.5%" in lines[1]


def test_terminal_market_data_diagnostics_sink_emits_when_frontier_date_changes(
    monkeypatch,  # noqa: ANN001
) -> None:
    timestamps = iter((100.0, 101.0, 102.0, 103.0))
    monkeypatch.setattr(
        "backtest_engine.interfaces.cli.market_data.diagnostics.perf_counter",
        lambda: next(timestamps),
    )
    stream = TtyStringIO()
    sink = TerminalMarketDataDiagnosticsSink(stream=stream)

    sink.emit(
        StageDiagnosticEvent(
            stage="market_data.batch.download",
            status="started",
            message="start batch",
            requested_by="cli",
            details={"provider_id": "mt5", "total_slices": 1},
        )
    )
    sink.emit(
        StageDiagnosticEvent(
            stage="market_data.slice.download",
            status="started",
            message="start slice",
            requested_by="cli",
            details={
                "provider_id": "mt5",
                "canonical_symbol": "EURUSD",
                "timeframe": "5m",
                "completed_slices": 0,
                "total_slices": 1,
            },
        )
    )
    sink.emit(progress_event(progress_pct=10.0, elapsed_sec=10.0, eta_sec=90.0))
    sink.emit(
        progress_event(
            progress_pct=10.1,
            elapsed_sec=11.0,
            eta_sec=89.0,
            actual_start_utc="2020-06-11T00:00:00+00:00",
        )
    )

    lines = [line for line in stream.getvalue().splitlines() if line.startswith("PROGRESS ")]
    assert len(lines) == 2
    assert "date=2020-06-11" in lines[1]


@pytest.mark.parametrize(
    ("status", "completed_slices", "failed_slices", "expected_prefix"),
    (
        ("succeeded", 2, 0, "DONE batch 2/2 slices (ok=2, failed=0) total=01:30"),
        ("failed", 2, 1, "FAILED batch 2/2 slices (ok=1, failed=1) total=01:30"),
    ),
)
def test_terminal_market_data_diagnostics_sink_batch_summary_includes_total_elapsed(
    monkeypatch,  # noqa: ANN001
    capsys: pytest.CaptureFixture[str],
    status: Literal["succeeded", "failed"],
    completed_slices: int,
    failed_slices: int,
    expected_prefix: str,
) -> None:
    timestamps = iter((100.0, 190.0))
    monkeypatch.setattr(
        "backtest_engine.interfaces.cli.market_data.diagnostics.perf_counter",
        lambda: next(timestamps),
    )
    sink = TerminalMarketDataDiagnosticsSink()

    sink.emit(
        StageDiagnosticEvent(
            stage="market_data.batch.download",
            status="started",
            message="start batch",
            requested_by="cli",
            details={"provider_id": "mt5", "total_slices": 2},
        )
    )
    sink.emit(
        StageDiagnosticEvent(
            stage="market_data.batch.download",
            status=status,
            message="done batch",
            requested_by="cli",
            details={"completed_slices": completed_slices, "failed_slices": failed_slices},
        )
    )

    captured = capsys.readouterr()
    assert expected_prefix in captured.out
