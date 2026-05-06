from __future__ import annotations

import importlib
import sys
from types import ModuleType
from unittest.mock import patch


FORBIDDEN_PREFIXES = (
    "backtest_engine.bootstrap",
    "backtest_engine.infrastructure.data",
    "backtest_engine.infrastructure.nautilus",
    "backtest_engine.strategies",
)


def test_backtest_cli_support_modules_stay_out_of_bootstrap_and_runtime_modules() -> None:
    module_names = (
        "backtest_engine.interfaces.cli.backtest.parsing",
        "backtest_engine.interfaces.cli.backtest.rendering",
        "backtest_engine.interfaces.cli.backtest.diagnostics",
        *FORBIDDEN_PREFIXES,
    )
    parent_attrs = _capture_parent_attrs()

    with patch.dict(sys.modules):
        for name in (*module_names, *_loaded_forbidden_modules()):
            sys.modules.pop(name, None)

        parsing = importlib.import_module("backtest_engine.interfaces.cli.backtest.parsing")
        rendering = importlib.import_module("backtest_engine.interfaces.cli.backtest.rendering")
        diagnostics = importlib.import_module("backtest_engine.interfaces.cli.backtest.diagnostics")

        assert callable(parsing.build_parser)
        assert callable(rendering.format_single_success)
        assert callable(diagnostics.TerminalBacktestDiagnosticsSink)
        assert not [
            name
            for name in sys.modules
            if any(name == prefix or name.startswith(f"{prefix}.") for prefix in FORBIDDEN_PREFIXES)
        ]

    for package, attr, original in parent_attrs:
        setattr(package, attr, original)


def test_backtest_cli_entrypoint_import_stays_out_of_bootstrap_and_runtime_modules() -> None:
    module_names = (
        "backtest_engine.interfaces.cli.backtest.__main__",
        *FORBIDDEN_PREFIXES,
    )
    parent_attrs = _capture_parent_attrs()

    with patch.dict(sys.modules):
        for name in (*module_names, *_loaded_forbidden_modules()):
            sys.modules.pop(name, None)

        module = importlib.import_module("backtest_engine.interfaces.cli.backtest.__main__")

        assert callable(module.main)
        assert not [
            name
            for name in sys.modules
            if any(name == prefix or name.startswith(f"{prefix}.") for prefix in FORBIDDEN_PREFIXES)
        ]

    for package, attr, original in parent_attrs:
        setattr(package, attr, original)


def _loaded_forbidden_modules() -> tuple[str, ...]:
    return tuple(
        name
        for name in sys.modules
        if any(name == prefix or name.startswith(f"{prefix}.") for prefix in FORBIDDEN_PREFIXES)
    )


def _capture_parent_attrs() -> list[tuple[ModuleType, str, object]]:
    parent_attrs: list[tuple[ModuleType, str, object]] = []
    for parent_path, attr in (
        ("backtest_engine", "bootstrap"),
        ("backtest_engine", "infrastructure"),
        ("backtest_engine", "strategies"),
        ("backtest_engine.interfaces.cli.backtest", "parsing"),
        ("backtest_engine.interfaces.cli.backtest", "rendering"),
        ("backtest_engine.interfaces.cli.backtest", "diagnostics"),
        ("backtest_engine.interfaces.cli.backtest", "__main__"),
    ):
        package = sys.modules.get(parent_path)
        if package is not None and hasattr(package, attr):
            parent_attrs.append((package, attr, getattr(package, attr)))
    return parent_attrs
