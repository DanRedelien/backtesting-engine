from __future__ import annotations

from pathlib import Path

import pytest

import tools.generate_run_profile_schema as schema_generator
from backtest_engine.interfaces.run_profiles import load_run_profile_spec

ROOT = Path(__file__).resolve().parents[3]
RUN_PROFILES_DIR = ROOT / "run_profiles"
SUPPORTED_PROFILE_SUFFIXES = (".toml", ".yaml", ".yml")


def test_run_profile_schema_artifact_is_current() -> None:
    expected = schema_generator.render_run_profile_schema_json()
    actual = schema_generator.SCHEMA_PATH.read_text(encoding="utf-8")

    if actual != expected:
        diff = schema_generator.format_schema_diff(
            actual,
            expected,
            path=schema_generator.SCHEMA_PATH,
        )
        pytest.fail(
            "Run-profile JSON Schema artifact is stale. "
            f"Run `{schema_generator.REGENERATE_COMMAND}`.\n{diff}",
        )


def test_schema_check_reports_stale_artifact_without_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    stale_path = tmp_path / "run_profile.schema.json"
    stale_content = '{"stale": true}\n'
    stale_path.write_text(stale_content, encoding="utf-8", newline="\n")
    monkeypatch.setattr(schema_generator, "SCHEMA_PATH", stale_path)

    exit_code = schema_generator.main(["--check"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert stale_path.read_text(encoding="utf-8") == stale_content
    assert schema_generator.REGENERATE_COMMAND in captured.err
    assert "---" in captured.err
    assert "+++" in captured.err


@pytest.mark.parametrize(
    "profile_path",
    sorted(
        path
        for suffix in SUPPORTED_PROFILE_SUFFIXES
        for path in RUN_PROFILES_DIR.glob(f"*{suffix}")
    ),
    ids=lambda path: path.name,
)
def test_committed_run_profiles_validate_through_loader(profile_path: Path) -> None:
    load_run_profile_spec(profile_path)
