from __future__ import annotations

import configparser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = ROOT / "src" / "backtest_engine"
FORBIDDEN_IMPORT_TOKENS = (
    "single_asset",
    "portfolio_layer",
    "nautilus_layer",
    "backtest_engine.services",
    "backtest_engine.runtime",
    "backtest_engine.runtime.terminal_ui",
    "src.backtest_engine.runtime.terminal_ui",
    "src.data",
)


def test_package_does_not_import_removed_paths() -> None:
    python_files = PACKAGE_ROOT.rglob("*.py")

    for path in python_files:
        content = path.read_text(encoding="utf-8")
        assert not any(token in content for token in FORBIDDEN_IMPORT_TOKENS), path


def test_non_interface_modules_do_not_use_print_or_sys_exit() -> None:
    python_files = PACKAGE_ROOT.rglob("*.py")

    for path in python_files:
        if "interfaces" in path.parts:
            continue

        content = path.read_text(encoding="utf-8")
        assert "print(" not in content, path
        assert "sys.exit(" not in content, path


def test_importlinter_layer_contract_has_no_ignore_import_exceptions() -> None:
    parser = configparser.ConfigParser()
    parser.read(ROOT / ".importlinter", encoding="utf-8")

    section = "importlinter:contract:layer_direction"
    assert parser.has_section(section)
    assert not parser.has_option(section, "ignore_imports")
