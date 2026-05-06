# Agent Bootstrap

Read repository context in this order:

1. code and tests for actual behavior
2. `README.md`
3. `docs/ARCHITECTURE.md`
4. `docs/MODULE_MAP.md`
5. `docs/IMPORT_RULES.md`
6. `docs/agents.md`
7. nearest package `README.md` under `src/backtest_engine/`
8. `dev_context/CLEAN_CODE_MCP.md` for cleanup, readability, or boundary-hardening work
9. other `dev_context/` material only when the task needs it

`AGENTS.md` is only the bootstrap reading order. `docs/agents.md` defines the
conflict-resolution order and repository-specific operating rules.

## Conflict Baseline

- code and tests beat narrative docs
- smaller-scope docs may clarify broader docs only when they do not contradict
  code or tests
- update docs after the code change that establishes the new behavior or
  ownership

## Add Code By Intent

- change stable primitives -> `src/backtest_engine/core/`
- change validated settings or run contracts -> `src/backtest_engine/config/`
- add strategy policy contracts -> `src/backtest_engine/domain/strategy/`
- add portfolio planning semantics -> `src/backtest_engine/domain/portfolio/`
- add execution truth contracts -> `src/backtest_engine/domain/execution/`
- add orchestration -> `src/backtest_engine/application/`
- add Nautilus or filesystem logic -> `src/backtest_engine/infrastructure/`
- add CLI or TUI delivery code -> `src/backtest_engine/interfaces/`
- wire dependencies -> `src/backtest_engine/bootstrap/composition_root.py`

## Forbidden Moves

- no imports from non-canonical runtime paths: `services/`, `single_asset/`,
  `portfolio_layer/`, `runtime/`, or `nautilus_layer/`
- no `sys.exit(...)` below `interfaces/`
- no `print(...)` in reusable non-interface modules
- no hidden registries or implicit runtime fallbacks

## Working Standard

- keep module boundaries explicit
- prefer typed contracts over ad hoc dictionaries
- update the nearest package `README.md` and canonical `docs/` pages when
  ownership or behavior changes
