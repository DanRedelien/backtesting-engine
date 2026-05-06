# Dev Context Index

This folder is a universal operating reference for LLMs and engineers working
on quantitative finance, trading, risk, and analytics systems.

It is designed to be useful across:

- backtesting engines
- execution simulators
- live trading bots
- market data pipelines
- VaR / ES / stress-testing engines
- research notebooks promoted into production systems
- portfolio analytics and risk dashboards

The current repository is only one example implementation. Example patterns
from this repository are explicitly labeled as examples and must not be treated
as mandatory architecture for every future project.

## Source of truth hierarchy

Always resolve conflicts in this order:

1. repository code and tests
2. repository-specific docs such as `README.md`, `docs/ARCHITECTURE.md`,
   `docs/MODULE_MAP.md`, `docs/IMPORT_RULES.md`, and `docs/agents.md`
3. this `dev_context/` folder

This folder is a guidance layer. It should reduce ambiguity, not override
observable repository behavior.

## Required reading order

For most tasks:

1. `dev_context/CLEAN_CODE_MCP.md`
2. `dev_context/QUANT_FRAMEWORK_MCP.md`
3. `dev_context/BASE/LLM_OPERATING_GUIDE.md`
4. the project-scale framework doc that best matches the target system
5. `dev_context/BASE/CROSS_PROJECT_EXAMPLES.md` when you need contrast across
   project types
6. only the task-specific docs that actually apply

## Folder map

- `CLEAN_CODE_MCP.md`
  Universal engineering and code-quality rules.
- `QUANT_FRAMEWORK_MCP.md`
  Universal quant-system architecture guidance.
- `BASE/`
  How to use this folder and how to think about project size.
- `DATA/`
  Market data acquisition, storage, cache design, and data validation.
- `RESEARCH/`
  Strategy engineering, optimization, walk-forward validation, and math
  invariants.
- `RISK/`
  Risk-model validation and specialized VaR / WHS guidance.
- `REPORTING/`
  Reporting, artifacts, dashboards, and visualization principles.
- `OPS/`
  Observability, runtime safety, circuit breakers, and production operations.

## Project-scale orientation

Choose the closest framework before designing or refactoring architecture:

- `BASE/PROJECT_FRAMEWORK_SMALL.md`
  Small research or prototype systems, roughly up to 30 modules.
- `BASE/PROJECT_FRAMEWORK_MEDIUM.md`
  Medium systems with clear bounded contexts, roughly 30 to 300 modules.
- `BASE/PROJECT_FRAMEWORK_MASSIVE.md`
  Large institutional platforms, often 300+ modules or 100k+ LOC.

## Task-to-document map

- New project bootstrap -> `QUANT_FRAMEWORK_MCP.md` + one project-scale file
- Code quality and refactors -> `CLEAN_CODE_MCP.md`
- Broker, exchange, or vendor data ingestion -> `DATA/MARKET_DATA_PIPELINE_MCP.md`
- Cache, lake, parquet, storage design -> `DATA/DATA_STORAGE_AND_CACHE_MCP.md`
- Data-quality checks -> `DATA/DATA_VALIDATION_MCP.md`
- Strategy implementation or review -> `RESEARCH/STRATEGY_ENGINEERING_MCP.md`
- Parameter search or time-series validation ->
  `RESEARCH/OPTIMIZATION_AND_WALK_FORWARD_MCP.md`
- Math and numerical conventions -> `RESEARCH/QUANT_MATH_INVARIANTS_MCP.md`
- Risk model review or release validation -> `RISK/RISK_MODEL_VALIDATION_MCP.md`
- Regime-aware VaR / ES / WHS -> `RISK/VAR_WHS_MCP.md`
- Dashboards, reports, and artifacts ->
  `REPORTING/REPORTING_AND_VISUALIZATION_MCP.md`
- Live trading safety, runtime monitoring, or production operations ->
  `OPS/OBSERVABILITY_AND_RUNTIME_SAFETY_MCP.md`

## Local repository mapping

This repository is a medium-scale example with several clear bounded contexts:

- `src/backtest_engine/config/` for canonical run, runtime, and platform
  settings
- `src/backtest_engine/domain/` for stable market, strategy, portfolio, and
  artifact contracts
- `src/backtest_engine/application/` for single, portfolio, batch, scenario,
  study, and baseline orchestration
- `src/backtest_engine/infrastructure/data/` for data adapters, caching, and
  dataset materialization
- `src/backtest_engine/infrastructure/nautilus/` for the canonical runtime
  boundary and strategy wrappers
- `src/backtest_engine/infrastructure/optimization/` for study persistence and
  Optuna runtime wiring
- `src/backtest_engine/analytics/read_models/` for typed artifact-read surfaces
- `src/backtest_engine/interfaces/terminal_ui/` for the active terminal UI
- `src/backtest_engine/interfaces/cli/` for CLI delivery adapters

This section exists only to map the current repository. Topic-specific MCP
documents should be read as generic guidance first, not as aliases for these
paths.

## Special note on domain-specific documents

`RISK/VAR_WHS_MCP.md` is intentionally specialized. It is not a default template
for all quant work. Use it only when the task is explicitly about risk
forecasting, VaR / ES, or weighted historical simulation.
