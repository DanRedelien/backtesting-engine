# Feature Scope Template

Copy this file into `.cursor/plans/feature_<name>_scope.md` (or the nearest
plan folder) when a task becomes locally stable and touches more than three
modules. Do not commit speculative scope docs back into `docs/`.

Fill every section. An empty section means "none", not "forgot".

---

# Feature scope: <name>

## Direct files (WILL edit)

- `path/to/file.py` - why this file is touched

## Indirect (WILL read, may touch)

- `path/to/file.py` - why this file is consulted

## Entry points

- CLI / FastAPI route / worker / library call that triggers the feature

## Contracts at risk

- execution truth contracts (`BacktestRunSpec`, artifact schema, ...)
- import boundaries (`docs/IMPORT_RULES.md`) or `.importlinter` contracts
- persisted bundle / study / recommendation schema compatibility

## Out of scope

- explicit list of areas this task will not touch
