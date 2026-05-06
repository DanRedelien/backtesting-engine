from __future__ import annotations

import importlib
import sys
from types import ModuleType
from unittest.mock import patch


FORBIDDEN_PREFIXES = (
    "backtest_engine.infrastructure",
    "backtest_engine.infrastructure.nautilus",
    "backtest_engine.strategies.sma_pullback",
    "backtest_engine.strategies.channel_breakout_long",
    "backtest_engine.strategies.statarb_weighted_spread",
    "backtest_engine.bootstrap.composition_root",
)


def test_run_profile_loader_import_stays_out_of_runtime_and_strategy_modules() -> None:
    module_names = (
        "backtest_engine.interfaces.run_profiles",
        "backtest_engine.interfaces.run_profiles.loader",
        *FORBIDDEN_PREFIXES,
    )
    parent_attrs = _capture_parent_attrs()

    with patch.dict(sys.modules):
        for name in (*module_names, *_loaded_forbidden_modules()):
            sys.modules.pop(name, None)

        module = importlib.import_module("backtest_engine.interfaces.run_profiles.loader")

        assert callable(module.load_run_profile_spec)
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
        ("backtest_engine.interfaces", "run_profiles"),
        ("backtest_engine.interfaces.run_profiles", "loader"),
        ("backtest_engine", "infrastructure"),
        ("backtest_engine", "bootstrap"),
        ("backtest_engine", "strategies"),
    ):
        package = sys.modules.get(parent_path)
        if package is not None and hasattr(package, attr):
            parent_attrs.append((package, attr, getattr(package, attr)))
    return parent_attrs
