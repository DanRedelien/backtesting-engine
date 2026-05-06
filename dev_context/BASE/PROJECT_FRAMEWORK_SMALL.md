# Project Framework: Small

Use this framework for small systems, usually:

- up to 30 modules
- one to three contributors
- one primary workflow
- research or prototype stage

Typical examples:

- single-strategy backtester
- small options pricer
- one broker trading bot
- compact risk dashboard

## Goals

- move fast without creating needless complexity
- keep the layout obvious
- make promotion to medium scale possible later

## Recommended shape

```text
project/
|-- README.md
|-- pyproject.toml
|-- run.py
|-- src/project_name/
|   |-- config.py
|   |-- data/
|   |-- domain/
|   |-- analytics.py
|   `-- runtime/
`-- tests/
```

## Practical rules

- Keep one canonical config module.
- Keep external adapters under `data/` or `runtime/`, not mixed into domain
  logic.
- Keep the domain layer pure enough to test without network or UI dependencies.
- Prefer one clear entry point.
- Keep helper modules honest. If a helper becomes stateful or business-critical,
  promote it into a named module with a clear responsibility.

## When to leave small-project mode

Move toward the medium framework when you now have any of these:

- multiple execution engines
- several workflows with shared semantics
- separate analytics and runtime surfaces
- more than one data source or broker integration
- several contributors touching the same files
- too many "utils" and "helpers" modules

## Anti-patterns

- creating enterprise folder depth with no need
- scattering settings across many files too early
- mixing notebook logic, broker calls, and strategy rules in one module
- pretending a prototype is production-ready because it has extra folders
