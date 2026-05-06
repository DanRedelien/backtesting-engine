"""Print the repository tree and a compact file-size report.

Run from the repository root:
    python -m tools.project_stats
or:
    python tools/project_stats.py

Complements `tools/build_code_index.py`: this tool reports project-wide
counts (including tests, docs, configs, templates), while the code index
reports the semantic shape of `src/backtest_engine/` only.
"""

from __future__ import annotations

import os
import sys
from typing import Protocol, TypedDict, cast

IGNORE_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".cursor",
        ".gemini",
        ".vscode",
        ".idea",
        "venv",
        "env",
        ".venv",
        "htmlcov",
        "dist",
        "build",
        "results",
        "var",
        "data",
    }
)

TEXT_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".py",
        ".md",
        ".txt",
        ".json",
        ".yaml",
        ".yml",
        ".css",
        ".js",
        ".html",
        ".toml",
        ".ini",
        ".cfg",
    }
)


class ProjectStats(TypedDict):
    total_files: int
    total_folders: int
    total_lines: int
    extension_counts: dict[str, int]


class SupportsReconfigure(Protocol):
    def reconfigure(self, *, encoding: str) -> object: ...


def _is_ignored(name: str, ignore_dirs: frozenset[str]) -> bool:
    if name in ignore_dirs:
        return True
    if name.endswith(".egg-info"):
        return True
    return False


def get_project_stats(root_dir: str, ignore_dirs: frozenset[str]) -> ProjectStats:
    stats: ProjectStats = {
        "total_files": 0,
        "total_folders": 0,
        "total_lines": 0,
        "extension_counts": {},
    }

    for root, dirs, files in os.walk(root_dir):
        dirs[:] = [d for d in dirs if not _is_ignored(d, ignore_dirs)]

        stats["total_folders"] += len(dirs)
        stats["total_files"] += len(files)

        for file in files:
            ext = os.path.splitext(file)[1].lower() or "no extension"
            counts = stats["extension_counts"]
            counts[ext] = counts.get(ext, 0) + 1

            if ext in TEXT_EXTENSIONS:
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        stats["total_lines"] += sum(1 for _ in f)
                except Exception:
                    pass

    return stats


def generate_tree(root_dir: str, ignore_dirs: frozenset[str], prefix: str = "") -> list[str]:
    """Generate a tree representation of the directory structure."""
    tree_lines: list[str] = []
    try:
        items = sorted(
            item for item in os.listdir(root_dir) if not _is_ignored(item, ignore_dirs)
        )
    except PermissionError:
        return []

    for i, item in enumerate(items):
        item_path = os.path.join(root_dir, item)
        is_last = i == len(items) - 1

        connector = "\u2514\u2500\u2500 " if is_last else "\u251c\u2500\u2500 "
        tree_lines.append(f"{prefix}{connector}{item}")

        if os.path.isdir(item_path):
            new_prefix = prefix + ("    " if is_last else "\u2502   ")
            tree_lines.extend(generate_tree(item_path, ignore_dirs, new_prefix))

    return tree_lines


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            cast(SupportsReconfigure, sys.stdout).reconfigure(encoding="utf-8")
        except Exception:
            pass

    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))

    print(f"Analyzing project at: {project_root}\n")

    print("Project Structure:")
    print(os.path.basename(project_root) + "/")
    for line in generate_tree(project_root, IGNORE_DIRS):
        print(line)

    stats = get_project_stats(project_root, IGNORE_DIRS)

    print("\n" + "-" * 30)
    print(f"Total Folders: {stats['total_folders']}")
    print(f"Total Files:   {stats['total_files']}")
    print(f"Total Lines:   {stats['total_lines']} (approx. code/text)")
    print("-" * 30)

    print("\nFiles by extension:")
    ext_counts = stats["extension_counts"]
    for ext, count in sorted(ext_counts.items(), key=lambda x: x[1], reverse=True):
        print(f" {ext:15}: {count}")


if __name__ == "__main__":
    main()
