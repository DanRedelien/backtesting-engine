"""Generate the committed JSON Schema artifact for run profiles.

Run from the repository root:
    python -m tools.generate_run_profile_schema

Check without writing:
    python -m tools.generate_run_profile_schema --check
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "docs" / "generated" / "run_profile.schema.json"
JSON_SCHEMA_DRAFT_URI = "https://json-schema.org/draft/2020-12/schema"
REGENERATE_COMMAND = "python -m tools.generate_run_profile_schema"


def build_run_profile_schema() -> dict[str, object]:
    """Build the deterministic schema payload from the Pydantic contract."""

    from backtest_engine.interfaces.run_profiles.loader import RunProfile

    schema = RunProfile.model_json_schema()
    schema["$schema"] = JSON_SCHEMA_DRAFT_URI
    normalized = _normalize_json_value(schema)
    if not isinstance(normalized, dict):
        raise TypeError("RunProfile JSON schema must be a JSON object")
    return normalized


def render_run_profile_schema_json() -> str:
    """Render the committed schema artifact with stable formatting."""

    schema = build_run_profile_schema()
    return json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def write_schema_artifact(path: Path | None = None) -> Path:
    """Write the generated schema artifact atomically."""

    target_path = SCHEMA_PATH if path is None else path
    _atomic_write_text(target_path, render_run_profile_schema_json())
    return target_path


def check_schema_artifact(path: Path | None = None) -> int:
    """Return 0 when the committed schema artifact is current."""

    target_path = SCHEMA_PATH if path is None else path
    expected = render_run_profile_schema_json()
    try:
        actual = target_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        actual = ""

    if actual == expected:
        print(f"{_display_path(target_path)} is current.")
        return 0

    print("Run-profile schema artifact is stale.", file=sys.stderr)
    print(f"Run `{REGENERATE_COMMAND}` to update it.", file=sys.stderr)
    diff = format_schema_diff(actual, expected, path=target_path)
    if diff:
        print(diff, file=sys.stderr, end="" if diff.endswith("\n") else "\n")
    return 1


def format_schema_diff(actual: str, expected: str, *, path: Path | None = None) -> str:
    """Return a concise unified diff for a stale schema artifact."""

    target_path = SCHEMA_PATH if path is None else path
    display_path = _display_path(target_path)
    return "".join(
        difflib.unified_diff(
            actual.splitlines(keepends=True),
            expected.splitlines(keepends=True),
            fromfile=display_path,
            tofile=f"{display_path} (generated)",
        )
    )


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for generation and no-write drift checks."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="check the committed schema artifact without writing",
    )
    args = parser.parse_args(argv)

    if args.check:
        return check_schema_artifact()

    target_path = write_schema_artifact()
    print(f"Wrote {_display_path(target_path)}")
    return 0


def _normalize_json_value(value: object) -> object:
    if isinstance(value, Mapping):
        normalized_items: list[tuple[str, object]] = []
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"JSON schema keys must be strings, got {type(key).__name__}")
            normalized_items.append((key, _normalize_json_value(item)))
        return {key: item for key, item in sorted(normalized_items, key=lambda pair: pair[0])}
    if isinstance(value, list):
        return [_normalize_json_value(item) for item in value]
    if value is None or isinstance(value, str | int | float | bool):
        return value
    raise TypeError(f"JSON schema contains non-JSON value {type(value).__name__}")


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8", newline="\n") as temp_file:
            temp_file.write(content)
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def _display_path(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


if __name__ == "__main__":
    raise SystemExit(main())
