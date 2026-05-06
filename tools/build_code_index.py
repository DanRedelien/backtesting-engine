"""Auto-generate a deterministic AST-based code index for src/backtest_engine/.

Produces:
- docs/code_index.md (human and LLM readable, grouped by top package)
- docs/code_index.json (machine readable snapshot)

Run from the repository root:
    python -m tools.build_code_index
or:
    python tools/build_code_index.py

The output is idempotent: two consecutive runs produce byte-identical files.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src" / "backtest_engine"
DOCS_DIR = REPO_ROOT / "docs"
INDEX_MD = DOCS_DIR / "code_index.md"
INDEX_JSON = DOCS_DIR / "code_index.json"

PACKAGE_ORDER: list[str] = [
    "core",
    "config",
    "domain",
    "application",
    "infrastructure",
    "analytics",
    "interfaces",
    "bootstrap",
]


def first_line(text: str | None) -> str:
    if not text:
        return ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def format_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    args = ast.unparse(node.args)
    prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
    return f"{prefix}{node.name}({args})"


def dotted_from_path(path: Path) -> str:
    rel = path.relative_to(REPO_ROOT / "src").with_suffix("")
    parts = list(rel.parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def top_package(dotted: str) -> str:
    parts = dotted.split(".")
    if parts == ["backtest_engine"]:
        return "_root"
    if len(parts) >= 2:
        return parts[1]
    return "_root"


def package_sort_key(pkg: str) -> tuple[int, str]:
    if pkg == "_root":
        return (-1, pkg)
    if pkg in PACKAGE_ORDER:
        return (PACKAGE_ORDER.index(pkg), pkg)
    return (len(PACKAGE_ORDER), pkg)


def collect_imports(
    tree: ast.Module, current_dotted: str
) -> tuple[list[str], list[str]]:
    internal: set[str] = set()
    external: set[str] = set()
    current_parts = current_dotted.split(".")

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name
                top = name.split(".")[0]
                if top == "backtest_engine":
                    internal.add(name)
                elif top == "__future__":
                    continue
                else:
                    external.add(top)
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0:
                if node.level > len(current_parts):
                    continue
                base = current_parts[: len(current_parts) - node.level]
                if node.module:
                    resolved = ".".join(base + node.module.split("."))
                else:
                    resolved = ".".join(base)
                if resolved.startswith("backtest_engine"):
                    internal.add(resolved)
                continue
            if node.module is None:
                continue
            top = node.module.split(".")[0]
            if top == "backtest_engine":
                internal.add(node.module)
            elif top == "__future__":
                continue
            else:
                external.add(top)

    return sorted(internal), sorted(external)


def extract_module_info(path: Path) -> dict[str, Any]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))

    classes: list[dict[str, str]] = []
    functions: list[dict[str, str]] = []

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            if node.name.startswith("_"):
                continue
            classes.append(
                {
                    "name": node.name,
                    "purpose": first_line(ast.get_docstring(node)),
                }
            )
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("_"):
                continue
            functions.append(
                {
                    "signature": format_signature(node),
                    "purpose": first_line(ast.get_docstring(node)),
                }
            )

    classes.sort(key=lambda c: c["name"])
    functions.sort(key=lambda f: f["signature"])

    dotted = dotted_from_path(path)
    imports_internal, imports_external = collect_imports(tree, dotted)

    return {
        "path": path.relative_to(REPO_ROOT).as_posix(),
        "dotted": dotted,
        "purpose": first_line(ast.get_docstring(tree)),
        "classes": classes,
        "functions": functions,
        "imports_internal": imports_internal,
        "imports_external": imports_external,
    }


def collect_modules() -> list[dict[str, Any]]:
    paths: list[Path] = []
    for path in SRC_ROOT.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        paths.append(path)
    modules = [extract_module_info(p) for p in sorted(paths)]
    modules.sort(key=lambda m: m["dotted"])
    return modules


def build_summary(modules: list[dict[str, Any]]) -> dict[str, Any]:
    classes = sum(len(m["classes"]) for m in modules)
    functions = sum(len(m["functions"]) for m in modules)
    edges = sum(len(m["imports_internal"]) for m in modules)
    packages = {top_package(m["dotted"]) for m in modules if top_package(m["dotted"]) != "_root"}
    return {
        "modules": len(modules),
        "classes": classes,
        "top_level_functions": functions,
        "internal_import_edges": edges,
        "packages": sorted(packages, key=package_sort_key),
    }


def _append_class_lines(lines: list[str], classes: list[dict[str, str]]) -> None:
    if not classes:
        lines.append("- classes: —")
        return
    lines.append("- classes:")
    for c in classes:
        if c["purpose"]:
            lines.append(f"  - {c['name']}: {c['purpose']}")
        else:
            lines.append(f"  - {c['name']}")


def _append_function_lines(lines: list[str], functions: list[dict[str, str]]) -> None:
    if not functions:
        lines.append("- functions: —")
        return
    lines.append("- functions:")
    for f in functions:
        if f["purpose"]:
            lines.append(f"  - {f['signature']}: {f['purpose']}")
        else:
            lines.append(f"  - {f['signature']}")


def render_markdown(modules: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Code Index")
    lines.append("")
    lines.append("Auto-generated by `tools/build_code_index.py`. DO NOT EDIT BY HAND.")
    lines.append("")
    lines.append("- Source: `src/backtest_engine/`")
    lines.append("- Regenerate: `python -m tools.build_code_index`")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- modules: {summary['modules']}")
    lines.append(f"- classes: {summary['classes']}")
    lines.append(f"- top-level functions: {summary['top_level_functions']}")
    lines.append(f"- internal import edges: {summary['internal_import_edges']}")
    lines.append(f"- packages: {', '.join(summary['packages'])}")
    lines.append("")

    by_package: dict[str, list[dict[str, Any]]] = {}
    for m in modules:
        by_package.setdefault(top_package(m["dotted"]), []).append(m)

    for pkg in sorted(by_package.keys(), key=package_sort_key):
        heading = "(root)" if pkg == "_root" else pkg
        lines.append(f"## {heading}")
        lines.append("")
        for m in by_package[pkg]:
            lines.append(f"### {m['dotted']}")
            lines.append("")
            lines.append(f"`{m['path']}`")
            lines.append("")
            lines.append(f"- purpose: {m['purpose'] or '—'}")
            _append_class_lines(lines, m["classes"])
            _append_function_lines(lines, m["functions"])
            if m["imports_internal"]:
                lines.append(f"- imports (internal): {', '.join(m['imports_internal'])}")
            else:
                lines.append("- imports (internal): —")
            if m["imports_external"]:
                lines.append(f"- imports (external): {', '.join(m['imports_external'])}")
            else:
                lines.append("- imports (external): —")
            lines.append("")

    return "\n".join(lines).rstrip("\n") + "\n"


def write_outputs(modules: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    payload = {"summary": summary, "modules": modules}
    INDEX_JSON.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    INDEX_MD.write_text(
        render_markdown(modules, summary),
        encoding="utf-8",
        newline="\n",
    )


def main() -> None:
    modules = collect_modules()
    summary = build_summary(modules)
    write_outputs(modules, summary)
    print(f"Wrote {INDEX_MD.relative_to(REPO_ROOT).as_posix()}")
    print(f"Wrote {INDEX_JSON.relative_to(REPO_ROOT).as_posix()}")
    print(
        f"modules={summary['modules']} classes={summary['classes']} "
        f"functions={summary['top_level_functions']} "
        f"edges={summary['internal_import_edges']}"
    )


if __name__ == "__main__":
    main()
