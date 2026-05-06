# Contributing

## Working Rules

- Keep modules small, typed, and single-purpose.
- Add code in the bounded context that owns the behavior.
- Prefer explicit contracts over loosely shaped dictionaries.
- Keep delivery adapters thin and orchestration top-down.
- Update tests with every behavior change.
- Update canonical `docs/` pages and the nearest package `README.md` when
  ownership, behavior, or public surfaces change.

## Architecture Discipline

- Do not add new imports to removed module paths or non-canonical runtime
  folders.
- Do not place `sys.exit(...)` below `interfaces/`.
- Do not use `print(...)` in reusable non-interface modules.
- Do not add hidden registries, ambient state, or implicit runtime fallbacks.

## New Module Checklist

- put the module in one obvious bounded context
- add a short module docstring
- export a small public API with `__all__` where appropriate
- add or update tests
- update nearby package docs and canonical docs when ownership changes

## Naming Guidelines

- prefer behavior-specific names such as `run_portfolio_backtest.py`
- prefer contract names such as `artifact_store.py`
- avoid vague modules such as `helpers.py`, `common.py`, or `misc.py`
- keep unit suffixes explicit: `_pct`, `_frac`, `_bps`, `_utc`

## Validation

Standard repository checks:

- `pytest -q`
- `ruff check .`
- `mypy src tests`
- `lint-imports --config .importlinter`
