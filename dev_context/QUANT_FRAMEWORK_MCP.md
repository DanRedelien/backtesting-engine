# QUANT FRAMEWORK MCP

Objective: provide a universal architecture framework for quantitative systems.

Use this document when bootstrapping or restructuring:

- backtesting engines
- broker or exchange adapters
- execution simulators
- risk engines
- portfolio analytics platforms
- research stacks that need a path toward production

This is not a one-layout religion. The correct design depends on project scale,
team size, deployment model, and runtime criticality.

## 1. Core architecture principles

- Separate business logic from delivery mechanisms.
- Separate data acquisition from data normalization and storage.
- Separate strategy or model logic from execution and risk controls.
- Separate orchestration from the engines that do the work.
- Separate analytics and artifact generation from the UI that renders them.
- Prefer explicit bounded contexts over giant utility folders.

## 2. Common bounded contexts

Most serious quant systems contain some version of these areas:

- `config`
  Settings, environment loading, typed runtime configuration.
- `data`
  Vendor connectors, normalization, cache, storage, validation.
- `domain`
  Core financial logic, models, strategies, contracts, policies.
- `execution` or `simulation`
  Order semantics, fills, slippage, commissions, session controls.
- `services`
  Orchestration use cases that connect adapters and engines.
- `analytics`
  Metrics, reports, artifacts, post-run analysis, diagnostics.
- `runtime`
  CLI, API, UI, workers, schedulers, notebooks, dashboards.
- `tests`
  Unit, regression, integration, scenario, and contract tests.

Not every project needs all of them on day one, but mixing them together
creates scaling problems later.

## 3. Project scale matters

Use the matching framework file in `dev_context/BASE/`:

- `PROJECT_FRAMEWORK_SMALL.md`
- `PROJECT_FRAMEWORK_MEDIUM.md`
- `PROJECT_FRAMEWORK_MASSIVE.md`

Do not force a massive-project architecture onto a small prototype. Do not keep
a giant fund-grade platform inside a flat 12-file layout.

## 4. Standard repository minimum

Every serious project should have, at minimum:

- `README.md`
- one architecture reference
- one quick module map or package map
- a typed configuration layer
- tests
- one clear runtime entry strategy
- one documented place where artifacts or outputs are written

If LLMs are expected to work inside the project, add:

- `docs/agents.md` or equivalent repository context
- `dev_context/README.md`
- a small number of focused MCP-style documents, not a pile of overlapping lore

## 5. Recommended dependency flow

Healthy default direction:

```text
runtime -> services -> domain / engines -> analytics / storage
```

Allowed support dependencies:

- domain code may depend on config and typed contracts
- services may depend on data, engines, analytics, and storage
- runtime may depend on services and presentation helpers

Avoid the reverse:

- engines should not depend on HTTP or template code
- data loaders should not depend on chart renderers
- strategy code should not depend on CLI parsing

## 6. How to place new code

Put code where its primary responsibility lives:

- new execution semantics -> `execution` or engine packages
- new workflow assembly -> `services`
- new broker or vendor adapter -> `data`
- new model or strategy logic -> `domain` or `strategies`
- new artifact schema or metric -> `analytics`
- new route, page, dashboard, or API handler -> `runtime`

If a new module feels equally at home in three places, the boundaries are
probably unclear and need to be cleaned up before adding more code.

## 7. Cross-project architecture examples

Example A: event-driven backtester

- `data/`
- `strategies/`
- `execution/`
- `services/`
- `analytics/`
- `runtime/`

Example B: risk analytics platform

- `market_data/`
- `features/`
- `regime_models/`
- `risk_models/`
- `validation/`
- `reporting/`
- `api/`

Example C: live execution bot

- `adapters/`
- `signals/`
- `risk_controls/`
- `order_router/`
- `monitoring/`
- `runtime/`

See `dev_context/README.md` for the local mapping of the current repository.

## 8. Universal warning

Do not generalize a specialized project into a universal rule.

Examples:

- A backtesting engine and a hedge-fund risk platform should not share the same
  folder complexity.
- A one-strategy research prototype does not need portfolio scheduling,
  scenario queues, and UI runtimes.
- A production risk engine may need much stricter interface, observability, and
  release controls than a research notebook converted into a package.
