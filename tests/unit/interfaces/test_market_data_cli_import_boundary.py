from __future__ import annotations

import importlib
import sys
from types import ModuleType
from unittest.mock import patch


def test_market_data_entrypoint_stays_isolated_from_unrelated_cli_and_bootstrap_modules() -> None:
    module_names = (
        "backtest_engine.bootstrap",
        "backtest_engine.bootstrap.composition_root",
        "backtest_engine.bootstrap._market_data_runtime",
        "backtest_engine.interfaces.cli",
        "backtest_engine.interfaces.cli.market_data",
        "backtest_engine.interfaces.cli.market_data.__main__",
        "backtest_engine.interfaces.cli.run_portfolio_weight_study",
    )

    # Python's import system sets submodule attributes on parent packages as
    # a side-effect.  patch.dict restores sys.modules but not those attrs, so
    # other tests that navigate the attribute chain would find stale module
    # objects.  Save and restore them explicitly.
    _parent_attrs: list[tuple[ModuleType, str, object]] = []
    for parent_path, attr in (
        ("backtest_engine", "bootstrap"),
        ("backtest_engine.interfaces", "cli"),
        ("backtest_engine.interfaces.cli", "market_data"),
        ("backtest_engine.interfaces.cli.market_data", "__main__"),
    ):
        pkg = sys.modules.get(parent_path)
        if pkg is not None and hasattr(pkg, attr):
            _parent_attrs.append((pkg, attr, getattr(pkg, attr)))

    with patch.dict(sys.modules):
        for name in module_names:
            sys.modules.pop(name, None)

        module = importlib.import_module("backtest_engine.interfaces.cli.market_data.__main__")

        assert callable(module.main)
        assert "backtest_engine.bootstrap._market_data_runtime" in sys.modules
        assert "backtest_engine.bootstrap.composition_root" not in sys.modules
        assert "backtest_engine.interfaces.cli.run_portfolio_weight_study" not in sys.modules

    for pkg, attr, original in _parent_attrs:
        setattr(pkg, attr, original)
