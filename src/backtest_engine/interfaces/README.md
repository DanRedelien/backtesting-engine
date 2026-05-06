# Interfaces

## Ownership

Owns CLI adapters, terminal UI handlers, and worker-facing request surfaces.
It also owns operator-facing run-profile parsing that translates YAML/TOML
launch documents into the canonical `BacktestRunSpec`.

## May Import

- `application`
- `config`
- `bootstrap`

## Must Never Import

- business semantics not already defined in `application` or `domain`

## Public Surface

- CLI adapters for canonical run and study flows
- run-profile loading under `run_profiles/`, including the public
  `RunProfile` models and `load_run_profile_spec(...)`
- optional run-profile `execution_policy` parsing into the canonical
  `BacktestRunSpec`, without Nautilus imports or runtime wiring
- runnable backtest CLI under `cli/backtest/` for single and portfolio
  run-profile dry-runs and execution, including explicit generated
  `--execution-costs-path` handoff with hash preflight
- historical market-data CLI parsing, diagnostics, and rendering under
  `cli/market_data/`
- offline spread calibration CLI under `cli/calibration/`, which prints the
  generated YAML path, canonical hash, run-profile snippet, and backtest
  handoff command
- terminal UI bundle, study, and recommendation reads plus scenario rerun
  planning
- worker scenario adapters

Package initializers must keep unrelated delivery flows lazily loaded so a
specialized entrypoint such as `python -m backtest_engine.interfaces.cli.market_data`
does not fail because an unrelated CLI surface imported extra runtime modules.

## Add Code Here

- request translation from an edge surface into an application command
- parsing and validation of operator-facing launch files before canonical run
  contracts are built
- declarative request fields that are passed through to config-layer contracts
  without defining execution truth in the delivery layer
- response shaping for terminal UI or worker callers
- presentation-focused app wiring

## Verification

- `tests/unit/interfaces/`

## Canonical References

- [Architecture](../../../docs/ARCHITECTURE.md)
- [Agent Context](../../../docs/agents.md)
