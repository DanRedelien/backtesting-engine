from __future__ import annotations

from decimal import Decimal
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import pytest

from backtest_engine.application.backtests.dry_run_backtest import (
    BacktestDryRunCommand,
    BacktestDryRunResult,
)
from backtest_engine.application.portfolio.run_portfolio_backtest import (
    PortfolioRunCommand,
    PortfolioRunResult,
)
from backtest_engine.application.single.run_single_backtest import SingleRunCommand, SingleRunResult
from backtest_engine.config.runtime import (
    BacktestExecutionPolicy,
    BacktestRunSpec,
    ExecutionCostProfileRef,
    ExecutionWindow,
)
from backtest_engine.core.enums import DatasetSource, RunKind
from backtest_engine.core.money import Money
from backtest_engine.domain.market.datasets import DatasetSpec
from backtest_engine.domain.strategy.specifications import (
    PortfolioStrategySpec,
    StrategyLegSpec,
    StrategySpec,
)
from backtest_engine.interfaces.cli.backtest import __main__ as backtest_main
from backtest_engine.core.errors import InfrastructureError


def test_backtest_cli_missing_subcommand_returns_usage_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(backtest_main, "build_cli_container", _raise_if_container_is_built)

    exit_code = backtest_main.main([])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "usage:" in captured.out
    assert "single" in captured.out
    assert "portfolio" in captured.out


def test_backtest_cli_help_does_not_construct_container(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(backtest_main, "build_cli_container", _raise_if_container_is_built)

    exit_code = backtest_main.main(["--help"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "single" in captured.out
    assert "portfolio" in captured.out


def test_backtest_cli_single_loads_profile_and_delegates_to_adapter(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    container = FakeCliContainer()
    run_spec = _build_run_spec(RunKind.SINGLE, "fixture_single_strategy", "EURUSD")
    loaded_paths: list[Path] = []

    def fake_load_run_profile_spec(path: Path) -> BacktestRunSpec:
        loaded_paths.append(path)
        return run_spec

    monkeypatch.setattr(backtest_main, "load_run_profile_spec", fake_load_run_profile_spec)
    monkeypatch.setattr(backtest_main, "build_cli_container", lambda **kwargs: container)

    exit_code = backtest_main.main(
        [
            "single",
            "--spec",
            "run_profiles/fx_single_asset.yaml",
            "--requested-by",
            "operator",
            "--correlation-id",
            "correlation-001",
            "--bundle-label",
            "bundle-label",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert loaded_paths == [Path("run_profiles/fx_single_asset.yaml")]
    delegated_command, delegated_spec = container.single_calls[0]
    assert delegated_command.requested_by == "operator"
    assert delegated_command.correlation_id == "correlation-001"
    assert delegated_command.bundle_label == "bundle-label"
    assert delegated_spec == run_spec
    assert "OK single" in captured.out
    assert "bundle_id: bundle-single" in captured.out


def test_backtest_cli_single_dry_run_delegates_to_container_without_running_single(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    container = FakeCliContainer()
    run_spec = _build_run_spec(RunKind.SINGLE, "fixture_single_strategy", "EURUSD")
    monkeypatch.setattr(backtest_main, "load_run_profile_spec", lambda path: run_spec)
    monkeypatch.setattr(backtest_main, "build_cli_container", lambda **kwargs: container)

    exit_code = backtest_main.main(
        [
            "single",
            "--spec",
            "run_profiles/fx_single_asset.yaml",
            "--dry-run",
            "--requested-by",
            "operator",
            "--correlation-id",
            "dry-correlation",
        ]
    )

    captured = capsys.readouterr()
    delegated_command, delegated_spec = container.dry_run_calls[0]
    assert exit_code == 0
    assert delegated_command.requested_by == "operator"
    assert delegated_command.correlation_id == "dry-correlation"
    assert delegated_spec == run_spec
    assert container.single_calls == []
    assert "OK dry-run" in captured.out
    assert "run_kind: single" in captured.out


def test_backtest_cli_execution_costs_path_validates_hash_and_builds_container(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    container = FakeCliContainer()
    expected_hash = "a" * 64
    run_spec = _with_execution_cost_hash(
        _build_run_spec(RunKind.SINGLE, "fixture_single_strategy", "EURUSD"),
        expected_hash,
    )
    captured_build_kwargs: dict[str, object] = {}

    def fake_build_cli_container(**kwargs: object) -> FakeCliContainer:
        captured_build_kwargs.update(kwargs)
        return container

    monkeypatch.setattr(backtest_main, "load_run_profile_spec", lambda path: run_spec)
    monkeypatch.setattr(backtest_main, "build_cli_container", fake_build_cli_container)
    monkeypatch.setattr(backtest_main, "load_execution_costs", lambda path: object())
    monkeypatch.setattr(backtest_main, "execution_costs_config_hash", lambda config: expected_hash)

    exit_code = backtest_main.main(
        [
            "single",
            "--spec",
            "run_profiles/fx_single_asset.yaml",
            "--execution-costs-path",
            "var/runtime/calibration/generated/execution_costs.yaml",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured_build_kwargs["execution_costs_path"] == Path(
        "var/runtime/calibration/generated/execution_costs.yaml"
    )
    assert container.single_calls
    assert "OK single" in captured.out


def test_backtest_cli_portfolio_execution_costs_path_validates_hash_and_builds_container(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    container = FakeCliContainer()
    expected_hash = "c" * 64
    run_spec = _with_execution_cost_hash(
        _build_run_spec(RunKind.PORTFOLIO, "fixture_portfolio_strategy", "GBPUSD"),
        expected_hash,
    )
    captured_build_kwargs: dict[str, object] = {}

    def fake_build_cli_container(**kwargs: object) -> FakeCliContainer:
        captured_build_kwargs.update(kwargs)
        return container

    monkeypatch.setattr(backtest_main, "load_run_profile_spec", lambda path: run_spec)
    monkeypatch.setattr(backtest_main, "build_cli_container", fake_build_cli_container)
    _patch_execution_cost_hash(monkeypatch, expected_hash)

    exit_code = backtest_main.main(
        [
            "portfolio",
            "--spec",
            "run_profiles/three_slot_portfolio.yaml",
            "--execution-costs-path",
            "var/runtime/calibration/generated/portfolio_execution_costs.yaml",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured_build_kwargs["execution_costs_path"] == Path(
        "var/runtime/calibration/generated/portfolio_execution_costs.yaml"
    )
    assert container.portfolio_calls
    assert "OK portfolio" in captured.out


def test_backtest_cli_execution_costs_path_requires_profile_hash(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run_spec = _build_run_spec(RunKind.SINGLE, "fixture_single_strategy", "EURUSD")
    monkeypatch.setattr(backtest_main, "load_run_profile_spec", lambda path: run_spec)
    monkeypatch.setattr(backtest_main, "build_cli_container", _raise_if_container_is_built)
    _patch_execution_cost_hash(monkeypatch, "d" * 64)

    exit_code = backtest_main.main(
        [
            "single",
            "--spec",
            "run_profiles/fx_single_asset.yaml",
            "--execution-costs-path",
            "var/runtime/calibration/generated/execution_costs.yaml",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "requires execution_policy.execution_costs.config_content_hash" in captured.out
    assert (
        f"execution_costs_path: {Path('var/runtime/calibration/generated/execution_costs.yaml')}"
        in captured.out
    )
    assert f"actual_config_content_hash: {'d' * 64}" in captured.out
    assert "run_profile_snippet:" in captured.out
    assert "  execution_policy:" in captured.out
    assert "    execution_costs:" in captured.out
    assert "      profile_id: default_execution_costs" in captured.out
    assert f"      config_content_hash: {'d' * 64}" in captured.out


def test_backtest_cli_execution_costs_path_rejects_omitted_policy_hash(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run_spec = _with_execution_cost_policy(
        _build_run_spec(RunKind.SINGLE, "fixture_single_strategy", "EURUSD"),
        None,
    )
    monkeypatch.setattr(backtest_main, "load_run_profile_spec", lambda path: run_spec)
    monkeypatch.setattr(backtest_main, "build_cli_container", _raise_if_container_is_built)
    _patch_execution_cost_hash(monkeypatch, "e" * 64)

    exit_code = backtest_main.main(
        [
            "single",
            "--spec",
            "run_profiles/fx_single_asset.yaml",
            "--execution-costs-path",
            "var/runtime/calibration/generated/execution_costs.yaml",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "requires execution_policy.execution_costs.config_content_hash" in captured.out
    assert f"actual_config_content_hash: {'e' * 64}" in captured.out
    assert f"      config_content_hash: {'e' * 64}" in captured.out


def test_backtest_cli_execution_costs_path_rejects_hash_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run_spec = _with_execution_cost_hash(
        _build_run_spec(RunKind.SINGLE, "fixture_single_strategy", "EURUSD"),
        "a" * 64,
    )
    monkeypatch.setattr(backtest_main, "load_run_profile_spec", lambda path: run_spec)
    monkeypatch.setattr(backtest_main, "build_cli_container", _raise_if_container_is_built)
    _patch_execution_cost_hash(monkeypatch, "b" * 64)

    exit_code = backtest_main.main(
        [
            "single",
            "--spec",
            "run_profiles/fx_single_asset.yaml",
            "--execution-costs-path",
            "var/runtime/calibration/generated/execution_costs.yaml",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "hash does not match run profile" in captured.out
    assert (
        f"execution_costs_path: {Path('var/runtime/calibration/generated/execution_costs.yaml')}"
        in captured.out
    )
    assert f"expected_config_content_hash: {'a' * 64}" in captured.out
    assert f"actual_config_content_hash: {'b' * 64}" in captured.out
    assert f"      config_content_hash: {'b' * 64}" in captured.out


def test_backtest_cli_portfolio_loads_profile_and_delegates_to_adapter(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    container = FakeCliContainer()
    run_spec = _build_run_spec(RunKind.PORTFOLIO, "fixture_portfolio_strategy", "GBPUSD")
    loaded_paths: list[Path] = []

    def fake_load_run_profile_spec(path: Path) -> BacktestRunSpec:
        loaded_paths.append(path)
        return run_spec

    monkeypatch.setattr(backtest_main, "load_run_profile_spec", fake_load_run_profile_spec)
    monkeypatch.setattr(backtest_main, "build_cli_container", lambda **kwargs: container)

    exit_code = backtest_main.main(
        [
            "portfolio",
            "--spec",
            "run_profiles/three_slot_portfolio.yaml",
            "--requested-by",
            "operator",
            "--correlation-id",
            "correlation-portfolio",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert loaded_paths == [Path("run_profiles/three_slot_portfolio.yaml")]
    delegated_command, delegated_spec = container.portfolio_calls[0]
    assert delegated_command.requested_by == "operator"
    assert delegated_command.correlation_id == "correlation-portfolio"
    assert delegated_spec == run_spec
    assert "OK portfolio" in captured.out
    assert "allocation_count: 1" in captured.out
    assert "position_count: 2" in captured.out


def test_backtest_cli_portfolio_dry_run_delegates_to_container_without_running_portfolio(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    container = FakeCliContainer()
    run_spec = _build_run_spec(RunKind.PORTFOLIO, "fixture_portfolio_strategy", "GBPUSD")
    monkeypatch.setattr(backtest_main, "load_run_profile_spec", lambda path: run_spec)
    monkeypatch.setattr(backtest_main, "build_cli_container", lambda **kwargs: container)

    exit_code = backtest_main.main(
        [
            "portfolio",
            "--spec",
            "run_profiles/three_slot_portfolio.yaml",
            "--dry-run",
        ]
    )

    captured = capsys.readouterr()
    delegated_command, delegated_spec = container.dry_run_calls[0]
    assert exit_code == 0
    assert delegated_command.requested_by == "cli"
    assert delegated_command.correlation_id is None
    assert delegated_spec == run_spec
    assert container.portfolio_calls == []
    assert "OK dry-run" in captured.out
    assert "run_kind: portfolio" in captured.out


@pytest.mark.parametrize(
    ("subcommand", "run_kind"),
    (
        ("single", RunKind.PORTFOLIO),
        ("portfolio", RunKind.SINGLE),
    ),
)
def test_backtest_cli_subcommand_profile_mismatch_returns_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    subcommand: str,
    run_kind: RunKind,
) -> None:
    run_spec = _build_run_spec(run_kind, "fixture_mismatch_strategy", "EURUSD")
    monkeypatch.setattr(backtest_main, "load_run_profile_spec", lambda path: run_spec)
    monkeypatch.setattr(backtest_main, "build_cli_container", _raise_if_container_is_built)

    exit_code = backtest_main.main([subcommand, "--spec", "run_profiles/profile.yaml"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "subcommand/profile mismatch" in captured.out


def test_backtest_cli_dry_run_failure_returns_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    container = FailingDryRunCliContainer()
    run_spec = _build_run_spec(RunKind.SINGLE, "fixture_single_strategy", "EURUSD")
    monkeypatch.setattr(backtest_main, "load_run_profile_spec", lambda path: run_spec)
    monkeypatch.setattr(backtest_main, "build_cli_container", lambda **kwargs: container)

    exit_code = backtest_main.main(
        [
            "single",
            "--spec",
            "run_profiles/fx_single_asset.yaml",
            "--dry-run",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert container.single_calls == []
    assert "InfrastructureError" in captured.out
    assert "compiler failed" in captured.out


@pytest.mark.parametrize(
    "write_profile",
    (
        lambda tmp_path: tmp_path / "missing.yaml",
        lambda tmp_path: _write_text(tmp_path / "profile.json", "{}"),
        lambda tmp_path: _write_text(tmp_path / "profile.yaml", "run_kind: batch\n"),
    ),
)
def test_backtest_cli_typed_profile_load_errors_return_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    write_profile: Callable[[Path], Path],
) -> None:
    monkeypatch.setattr(backtest_main, "build_cli_container", _raise_if_container_is_built)
    profile_path = write_profile(tmp_path)

    exit_code = backtest_main.main(["single", "--spec", str(profile_path)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "ApplicationError" in captured.out


class FakeCliContainer:
    def __init__(self) -> None:
        self.single_calls: list[tuple[SingleRunCommand, BacktestRunSpec]] = []
        self.portfolio_calls: list[tuple[PortfolioRunCommand, BacktestRunSpec]] = []
        self.dry_run_calls: list[tuple[BacktestDryRunCommand, BacktestRunSpec]] = []

    def dry_run_backtest(
        self,
        command: BacktestDryRunCommand,
        run_spec: BacktestRunSpec,
    ) -> BacktestDryRunResult:
        self.dry_run_calls.append((command, run_spec))
        return BacktestDryRunResult(
            run_id=run_spec.run_id,
            run_kind=run_spec.run_kind,
            dataset_id=run_spec.dataset.dataset_id,
            runtime_root=f"var/runtime/nautilus/{run_spec.run_id}",
            artifact_root=f"var/runtime/nautilus/{run_spec.run_id}/artifacts",
            catalog_root=f"var/cache/nautilus_catalogs/{run_spec.dataset.dataset_id}",
            venue_names=("SIM",),
            data_count=1,
            instrument_ids=(f"{run_spec.dataset.symbol_universe[0]}.SIM",),
            bar_types=(f"{run_spec.dataset.symbol_universe[0]}.SIM-30-MINUTE-LAST-EXTERNAL",),
            strategy_ids=tuple(strategy.strategy.strategy_id for strategy in run_spec.strategies),
        )

    def run_single_backtest(
        self,
        command: SingleRunCommand,
        run_spec: BacktestRunSpec,
    ) -> SingleRunResult:
        self.single_calls.append((command, run_spec))
        return SingleRunResult(
            run_id=run_spec.run_id,
            bundle_id="bundle-single",
            bundle_uri="results/bundle-single/bundle.json",
            runtime_root=f"var/runtime/nautilus/{run_spec.run_id}",
            metric_values={"net_profit": 100.0},
        )

    def run_portfolio_backtest(
        self,
        command: PortfolioRunCommand,
        run_spec: BacktestRunSpec,
    ) -> PortfolioRunResult:
        self.portfolio_calls.append((command, run_spec))
        return PortfolioRunResult(
            run_id=run_spec.run_id,
            bundle_id="bundle-portfolio",
            bundle_uri="results/bundle-portfolio/bundle.json",
            runtime_root=f"var/runtime/nautilus/{run_spec.run_id}",
            allocation_count=1,
            position_count=2,
            metric_values={"net_profit": 250.0},
        )


class FailingDryRunCliContainer(FakeCliContainer):
    def dry_run_backtest(
        self,
        command: BacktestDryRunCommand,
        run_spec: BacktestRunSpec,
    ) -> BacktestDryRunResult:
        self.dry_run_calls.append((command, run_spec))
        raise InfrastructureError(
            "compiler failed during dry-run",
            run_id=run_spec.run_id,
        )


def _build_run_spec(run_kind: RunKind, strategy_id: str, symbol: str) -> BacktestRunSpec:
    return BacktestRunSpec(
        run_kind=run_kind,
        execution_window=ExecutionWindow(
            start_utc=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end_utc=datetime(2024, 2, 1, tzinfo=timezone.utc),
        ),
        dataset=DatasetSpec(
            source_system=DatasetSource.PARQUET,
            normalization_policy="nautilus_v1",
            schema_version="1",
            symbol_universe=(symbol,),
            timeframe="30m",
            dataset_version="2026-04-03",
        ),
        strategies=(
            PortfolioStrategySpec(
                slot_id="slot-1",
                weight_frac=1.0,
                strategy=StrategySpec(
                    strategy_id=strategy_id,
                    implementation_id=strategy_id,
                    policy_version="v1",
                ),
                legs=(StrategyLegSpec(symbol=symbol),),
            ),
        ),
        capital_base=Money(amount=Decimal("100000"), currency="USD"),
    )


def _with_execution_cost_hash(
    run_spec: BacktestRunSpec,
    config_content_hash: str,
) -> BacktestRunSpec:
    return _with_execution_cost_policy(run_spec, config_content_hash)


def _with_execution_cost_policy(
    run_spec: BacktestRunSpec,
    config_content_hash: str | None,
) -> BacktestRunSpec:
    return run_spec.model_copy(
        update={
            "execution_policy": BacktestExecutionPolicy(
                execution_costs=ExecutionCostProfileRef(
                    profile_id="default_execution_costs",
                    config_content_hash=config_content_hash,
                )
            )
        }
    )


def _patch_execution_cost_hash(
    monkeypatch: pytest.MonkeyPatch,
    config_content_hash: str,
) -> None:
    monkeypatch.setattr(backtest_main, "load_execution_costs", lambda path: object())
    monkeypatch.setattr(
        backtest_main,
        "execution_costs_config_hash",
        lambda config: config_content_hash,
    )


def _write_text(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _raise_if_container_is_built(*args: object, **kwargs: object) -> None:
    raise AssertionError("container should not be constructed")
