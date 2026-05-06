# Agent Context

## Conflict Resolution Order

Resolve disagreements in this order:

1. code and tests
2. task-specific user instructions
3. `README.md`
4. `docs/ARCHITECTURE.md`
5. `docs/MODULE_MAP.md`
6. `docs/IMPORT_RULES.md`
7. nearest package `README.md` under `src/backtest_engine/`
8. `dev_context/CLEAN_CODE_MCP.md` for cleanup and boundary work
9. remaining narrative docs

Narrative docs never override code or tests. If behavior and docs diverge, treat
the docs as stale and sync them after the code is corrected.

## Repository Intent

This repository is a research and backtesting platform built around:

- one canonical Nautilus execution boundary
- typed run contracts
- explicit artifact persistence
- thin delivery surfaces
- strict bounded-context ownership

## Operational Index

- `docs/code_index.md` is an auto-generated AST snapshot of
  `src/backtest_engine/` (modules, symbols, imports). Regenerate via
  `python -m tools.build_code_index` before any task that touches more than
  three modules or after the tree has moved.
- `docs/generated/run_profile.schema.json` is the generated machine-readable
  run-profile schema derived from the Pydantic `RunProfile` contract.
  Regenerate via `python -m tools.generate_run_profile_schema`; check drift
  without writing via `python -m tools.generate_run_profile_schema --check`.
- For tasks that become locally stable, copy `docs/code_scope_template.md`
  into `.cursor/plans/feature_<name>_scope.md` and fill direct / indirect /
  entry points / contracts / out-of-scope. Do not create scope docs
  speculatively.
- `docs/code_index.md` and `docs/code_index.json` do not override code or
  tests; they are narrative artifacts and follow the same conflict baseline
  as other docs. Never hand-edit them.
- Project-wide size and tree overview: `python -m tools.project_stats`.

## Data Context

Assume these source priorities unless code or task-specific docs say otherwise:

- provider-managed ingestion implemented today:
  - IB/TWS for CME index futures historical retrieval
  - MT5 for Forex, CFD, and crypto historical retrieval through a local Windows
    terminal
- generic source-cache path still exists for plain `DatasetSource.PARQUET`
  datasets resolved from `data/cache`
- `DatasetSource.IB` and `DatasetSource.MT5` materialization require a fresh
  `PASS` validation manifest whose fingerprint matches the saved source slice
- provider-managed source slices persist `checkpoint.json` and partial parquet
  writes so interrupted downloads resume instead of restarting the whole window
- canonical symbol selects the storage path; provider symbol resolution stays in
  symbol-map metadata and source manifests
- MT5 bars are normalized to UTC timestamps while broker timezone and calendar
  policy stay explicit for session-aware verification

Read these files when the task touches historical-data behavior:

- `src/backtest_engine/config/nautilus_symbol_map.yaml`
- `src/backtest_engine/config/data.py`
- `src/backtest_engine/infrastructure/data/parquet_normalizer.py`
- `src/backtest_engine/infrastructure/data/market_data_store.py`
- `src/backtest_engine/infrastructure/data/verification.py`
- `src/backtest_engine/infrastructure/data/ib/provider.py`
- `src/backtest_engine/infrastructure/data/mt5/provider.py`

## Code Placement Guide

- core primitives -> `src/backtest_engine/core/`
- validated configuration -> `src/backtest_engine/config/`
- strategy-agnostic business semantics -> `src/backtest_engine/domain/`
- concrete strategy cartridge -> `src/backtest_engine/strategies/<implementation_id>/`
- use-case orchestration -> `src/backtest_engine/application/`
- external and runtime adapters -> `src/backtest_engine/infrastructure/`
- derived read models -> `src/backtest_engine/analytics/`
- CLI, terminal UI, and workers -> `src/backtest_engine/interfaces/`
- dependency wiring -> `src/backtest_engine/bootstrap/`

## Non-Negotiable Constraints

- no imports from removed runtime paths
- no execution truth in delivery layers
- no hidden registries or implicit fallbacks
- concrete strategies are discovered from
  `src/backtest_engine/strategies/<implementation_id>/definition.py`, not
  manually registered
- no `print(...)` in reusable non-interface modules
- no `sys.exit(...)` below `interfaces/`
- no shims, compat layers, or legacy wrappers to preserve stale internal import
  paths

## Documentation Rule

If behavior, ownership, or public surfaces change:

- update the nearest package `README.md`
- update the matching canonical document in `docs/`
- preserve alignment between documentation and tests
