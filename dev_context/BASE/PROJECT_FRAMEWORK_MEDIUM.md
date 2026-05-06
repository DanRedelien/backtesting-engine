# Project Framework: Medium

Use this framework for medium systems, usually:

- roughly 30 to 300 modules
- multiple workflows sharing important invariants
- clear bounded contexts
- active refactoring and growing contributor surface

Typical examples:

- a futures backtesting platform
- a multi-strategy portfolio research stack
- a risk analytics platform
- a reusable execution simulator with reporting surfaces

## Design goal

Preserve velocity while making responsibility boundaries explicit.

## Recommended bounded contexts

```text
project/
|-- docs/
|-- dev_context/
|-- src/project_name/
|   |-- config/
|   |-- data/
|   |-- execution/
|   |-- domain/ or strategies/
|   |-- services/
|   |-- analytics/
|   `-- runtime/
`-- tests/
```

Possible additional contexts:

- `optimization/`
- `portfolio/`
- `risk/`
- `adapters/`
- `serialization/`

## Rules for medium systems

- Make workflow orchestration a first-class layer.
- Keep engine semantics and portfolio accounting out of CLI and UI code.
- Keep analytics logic separate from the runtime that renders it.
- Keep adapters separate from domain logic.
- Use README files or module maps for the major packages.
- Create stable typed contracts where packages meet.

## Example medium-scale shapes

Example A: event-driven backtesting platform

- `data/` for adapters and validation
- `execution/` for fill semantics and cost models
- `strategies/` for alpha logic
- `services/` for orchestration
- `analytics/` for reports and artifacts
- `runtime/` for CLI, API, or dashboard delivery

Example B: HMM-driven risk platform

- `market_data/` for normalized returns and instrument inputs
- `features/` for realized-volatility, clustering, or regime features
- `regime_models/` for HMM or classifier logic
- `risk_models/` for VaR / ES or stress forecasts
- `validation/` for coverage and challenger analysis
- `reporting/` for audit packs and dashboards

See `dev_context/README.md` for the local mapping of the current repository.

## When to leave medium-project mode

Move toward the massive framework when you now need:

- strong team ownership boundaries
- multiple deployable services or packages
- schema/version governance across teams
- explicit platform APIs between bounded contexts
- dedicated observability, audit, release, and rollback processes

## Anti-patterns

- keeping everything in one package because "imports still work"
- creating hidden dependencies between runtime, services, and engines
- allowing several bounded contexts to mutate the same artifact contract
- letting the UI become the source of truth for analytics semantics
