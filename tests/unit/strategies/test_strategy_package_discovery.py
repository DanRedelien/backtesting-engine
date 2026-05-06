from __future__ import annotations

from pathlib import Path

from backtest_engine.strategies.package_contracts import StrategyPackageDefinition
from backtest_engine.strategies.package_loader import (
    clear_strategy_package_definition_cache,
    load_strategy_package_definition,
)


ROOT = Path(__file__).resolve().parents[3]
STRATEGY_ROOT = ROOT / "src" / "backtest_engine" / "strategies"
REQUIRED_PACKAGE_FILES = frozenset(
    {
        "__init__.py",
        "definition.py",
        "parameters.py",
        "nautilus_strategy.py",
        "README.md",
    }
)


def test_all_strategy_package_definitions_load_from_folders() -> None:
    clear_strategy_package_definition_cache()
    definition_files = sorted(STRATEGY_ROOT.glob("*/definition.py"))

    assert definition_files
    for definition_file in definition_files:
        strategy_dir = definition_file.parent
        implementation_id = strategy_dir.name
        exported = load_strategy_package_definition(implementation_id)

        assert isinstance(exported, StrategyPackageDefinition)
        assert exported.implementation_id == implementation_id
        assert REQUIRED_PACKAGE_FILES.issubset({path.name for path in strategy_dir.iterdir()})
        assert exported.strategy_path.startswith(f"backtest_engine.strategies.{implementation_id}.")
        assert exported.config_path.startswith(f"backtest_engine.strategies.{implementation_id}.")
