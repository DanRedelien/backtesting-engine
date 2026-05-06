from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STRATEGY_ROOT = ROOT / "src" / "backtest_engine" / "strategies"
FORBIDDEN_CONTEXT_IMPORTS = (
    "backtest_engine.application",
    "backtest_engine.bootstrap",
    "backtest_engine.infrastructure",
    "backtest_engine.interfaces",
)
VAGUE_MODULE_NAMES = {"helpers.py", "common.py", "misc.py"}


def test_strategy_package_production_modules_keep_runtime_boundaries() -> None:
    for strategy_dir in _strategy_dirs():
        strategy_id = strategy_dir.name
        for path in _production_python_files(strategy_dir):
            imports = _module_imports(path)
            forbidden_imports = [
                imported
                for imported in imports
                if _is_forbidden_import(imported, strategy_id)
            ]

            assert not forbidden_imports, f"{path}: {forbidden_imports}"


def test_strategy_packages_do_not_use_vague_module_names() -> None:
    for strategy_dir in _strategy_dirs():
        vague_files = sorted(path for path in strategy_dir.rglob("*.py") if path.name in VAGUE_MODULE_NAMES)

        assert not vague_files, strategy_dir


def test_relative_import_scanner_allows_same_strategy_imports(tmp_path: Path) -> None:
    strategy_root = tmp_path / "backtest_engine" / "strategies"
    module_path = strategy_root / "local_strategy" / "definition.py"
    module_path.parent.mkdir(parents=True)
    module_path.write_text("from .parameters import Parameters\n", encoding="utf-8")

    assert _module_imports(module_path, strategy_root=strategy_root) == (
        "backtest_engine.strategies.local_strategy.parameters",
    )


def test_relative_import_scanner_rejects_sibling_strategy_imports(tmp_path: Path) -> None:
    strategy_root = tmp_path / "backtest_engine" / "strategies"
    module_path = strategy_root / "local_strategy" / "definition.py"
    module_path.parent.mkdir(parents=True)
    module_path.write_text("from ..other_strategy.parameters import Parameters\n", encoding="utf-8")

    imports = _module_imports(module_path, strategy_root=strategy_root)

    assert _is_forbidden_import(imports[0], "local_strategy")


def test_relative_import_scanner_rejects_sibling_strategy_alias_imports(tmp_path: Path) -> None:
    strategy_root = tmp_path / "backtest_engine" / "strategies"
    module_path = strategy_root / "local_strategy" / "definition.py"
    module_path.parent.mkdir(parents=True)
    module_path.write_text("from .. import other_strategy\n", encoding="utf-8")

    imports = _module_imports(module_path, strategy_root=strategy_root)

    assert imports == ("backtest_engine.strategies.other_strategy",)
    assert _is_forbidden_import(imports[0], "local_strategy")


def test_relative_import_scanner_rejects_parent_context_imports(tmp_path: Path) -> None:
    strategy_root = tmp_path / "backtest_engine" / "strategies"
    module_path = strategy_root / "local_strategy" / "definition.py"
    module_path.parent.mkdir(parents=True)
    module_path.write_text("from ...application.service import Service\n", encoding="utf-8")

    imports = _module_imports(module_path, strategy_root=strategy_root)

    assert _is_forbidden_import(imports[0], "local_strategy")


def test_relative_import_scanner_rejects_parent_context_alias_imports(tmp_path: Path) -> None:
    strategy_root = tmp_path / "backtest_engine" / "strategies"
    module_path = strategy_root / "local_strategy" / "definition.py"
    module_path.parent.mkdir(parents=True)
    module_path.write_text("from ... import application\n", encoding="utf-8")

    imports = _module_imports(module_path, strategy_root=strategy_root)

    assert imports == ("backtest_engine.application",)
    assert _is_forbidden_import(imports[0], "local_strategy")


def test_dynamic_project_imports_are_forbidden(tmp_path: Path) -> None:
    strategy_root = tmp_path / "backtest_engine" / "strategies"
    module_path = strategy_root / "local_strategy" / "definition.py"
    module_path.parent.mkdir(parents=True)
    module_path.write_text(
        "import importlib\n"
        "importlib.import_module('backtest_engine.core.types')\n"
        "__import__(target_module)\n",
        encoding="utf-8",
    )

    imports = _module_imports(module_path, strategy_root=strategy_root)
    dynamic_imports = tuple(imported for imported in imports if imported.startswith("dynamic:"))

    assert "dynamic:backtest_engine.core.types" in imports
    assert "dynamic:backtest_engine.<non_literal>" in imports
    assert all(_is_forbidden_import(imported, "local_strategy") for imported in dynamic_imports)


def _strategy_dirs() -> tuple[Path, ...]:
    return tuple(sorted(path.parent for path in STRATEGY_ROOT.glob("*/definition.py")))


def _production_python_files(strategy_dir: Path) -> tuple[Path, ...]:
    return tuple(
        sorted(
            path
            for path in strategy_dir.rglob("*.py")
            if "tests" not in path.relative_to(strategy_dir).parts
        )
    )


def _module_imports(path: Path, *, strategy_root: Path = STRATEGY_ROOT) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[str] = []
    importlib_names = {"importlib"}
    import_module_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
            importlib_names.update(alias.asname or alias.name for alias in node.names if alias.name == "importlib")
        elif isinstance(node, ast.ImportFrom):
            if node.module == "importlib":
                import_module_names.update(
                    alias.asname or alias.name for alias in node.names if alias.name == "import_module"
                )
            imports.extend(_resolve_import_from(path, node, strategy_root=strategy_root))
        elif isinstance(node, ast.Call):
            dynamic_import = _dynamic_project_import(node, importlib_names, import_module_names)
            if dynamic_import is not None:
                imports.append(dynamic_import)
    return tuple(imports)


def _resolve_import_from(
    path: Path,
    node: ast.ImportFrom,
    *,
    strategy_root: Path,
) -> tuple[str, ...]:
    if node.level == 0:
        if node.module is None:
            return ()
        return (node.module,)

    module_parts = _module_parts_for_path(path, strategy_root=strategy_root)
    package_parts = module_parts[:-1]
    if path.name == "__init__.py":
        package_parts = module_parts[:-1]
    base_size = len(package_parts) - (node.level - 1)
    if base_size < 1:
        return () if node.module is None else (node.module,)
    resolved_parts = package_parts[:base_size]
    if node.module is not None:
        resolved_parts.extend(node.module.split("."))
        return (".".join(resolved_parts),)
    return tuple(".".join((*resolved_parts, alias.name)) for alias in node.names)


def _module_parts_for_path(path: Path, *, strategy_root: Path) -> list[str]:
    relative_parts = path.relative_to(strategy_root).with_suffix("").parts
    return ["backtest_engine", "strategies", *relative_parts]


def _dynamic_project_import(
    node: ast.Call,
    importlib_names: set[str],
    import_module_names: set[str],
) -> str | None:
    if not _is_dynamic_import_call(node, importlib_names, import_module_names):
        return None
    if not node.args:
        return None
    target = node.args[0]
    if isinstance(target, ast.Constant) and isinstance(target.value, str):
        if target.value.startswith("backtest_engine."):
            return f"dynamic:{target.value}"
        return None
    return "dynamic:backtest_engine.<non_literal>"


def _is_dynamic_import_call(
    node: ast.Call,
    importlib_names: set[str],
    import_module_names: set[str],
) -> bool:
    function = node.func
    if isinstance(function, ast.Name):
        return function.id == "__import__" or function.id in import_module_names
    return (
        isinstance(function, ast.Attribute)
        and function.attr == "import_module"
        and isinstance(function.value, ast.Name)
        and function.value.id in importlib_names
    )


def _is_forbidden_import(imported: str, strategy_id: str) -> bool:
    if imported.startswith("dynamic:backtest_engine."):
        return True
    return imported.startswith(FORBIDDEN_CONTEXT_IMPORTS) or _imports_another_strategy(
        imported,
        strategy_id,
    )


def _imports_another_strategy(imported: str, strategy_id: str) -> bool:
    prefix = "backtest_engine.strategies."
    if not imported.startswith(prefix):
        return False
    imported_strategy = imported.removeprefix(prefix).split(".", maxsplit=1)[0]
    return imported_strategy not in {strategy_id, "package_contracts"}
