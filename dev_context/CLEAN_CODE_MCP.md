# CLEAN CODE MCP

Objective: provide universal engineering rules for LLMs and humans building
institutional-grade quantitative systems.

Scope: applies to research code, backtesting engines, data pipelines, risk
models, execution simulators, dashboards, and production services.

Status: mandatory unless the repository has a stronger local rule.

## 1. Communication and language

- Write comments, docstrings, commit messages, and user-facing developer docs in
  English.
- Prefer precise domain terms over slang. Use `mark_to_market`,
  `max_drawdown_pct`, or `annualized_volatility`, not vague names such as
  `calc2` or `magic_value`.
- State assumptions explicitly when a behavior depends on market convention,
  exchange session, timezone, contract roll policy, or units.

## 2. Naming and structure

- Use names that reveal business meaning, not implementation accidents.
- Keep modules cohesive. One module should own one clear responsibility.
- Keep functions small enough that the control flow is obvious without mental
  backtracking.
- Split orchestration from pure calculations. Workflow code should assemble
  steps; domain code should implement the steps.
- Separate adapters from core logic. Broker APIs, file I/O, HTTP, and UI code
  should not leak into pure math or execution semantics.

## 3. Types, contracts, and schemas

- Add type hints to all public functions, methods, and important internal
  helpers.
- Prefer explicit domain models over raw nested dictionaries for stable
  interfaces. `dataclass`, `TypedDict`, `Protocol`, or `pydantic` are all valid
  choices depending on the boundary.
- Validate external inputs at the edges:
  - CLI arguments
  - config files
  - HTTP payloads
  - vendor data
  - artifact schemas
- Avoid passing partially shaped objects through many layers. Normalize early.

## 4. Configuration and constants

- Do not hardcode strategy windows, risk thresholds, trading costs, roll rules,
  or file-system roots inside business logic.
- Put shared runtime configuration in a canonical config layer.
- Keep units in variable names when ambiguity is possible:
  - `_pct` for percent values such as `25.0`
  - `_frac` for fractional values such as `0.25`
  - `_bps` for basis points
  - `_utc` for timezone-normalized timestamps

## 5. Control flow and error handling

- Prefer deterministic behavior over hidden fallbacks.
- When a fallback exists, document when it is used and why it is safe.
- In research and batch pipelines, non-critical issues may log and continue if
  the degraded result remains truthful.
- In live trading or risk-control code, stale data, broken invariants, or
  repeated model failures should escalate, halt, or trip a circuit breaker.
- Do not spam logs inside tight loops. Aggregate repeated failures.

## 6. Numerical and data safety

- Never mix percent and fraction units without explicit conversion.
- Never mix naive and timezone-aware timestamps without normalizing them.
- Never compute returns from zero, missing, or obviously corrupt prices.
- Never silently resample or forward-fill market data unless the policy is
  documented and acceptable for the use case.
- Never introduce lookahead bias through future-index access, manual shifts, or
  leakage during feature engineering and validation.

## 7. Comments and docstrings

- Add comments only when they explain intent, assumptions, edge cases, or
  financial reasoning that is not obvious from the code.
- Public classes and methods should explain both what they do and why the logic
  is designed that way.
- Good docstrings usually include:
  - one-line summary
  - methodology or business rationale
  - key assumptions
  - important argument or return-value details

## 8. Testing and verification

- Add or update tests whenever behavior changes.
- Prefer regression tests for bugs that have already occurred.
- Test numerical code with representative edge cases:
  - sparse data
  - missing bars
  - contract rolls
  - same-bar stop and target collisions
  - negative or zero returns
  - empty slices and short windows
- If a change affects public behavior, update nearby docs and examples.

## 9. Anti-patterns

Reject changes that do any of the following:

- hide market assumptions in magic numbers
- mix broker I/O with signal logic
- use `print()` as the main observability strategy in reusable code
- create giant god-modules with data access, math, orchestration, and rendering
  all mixed together
- use vague names for units, timestamps, or risk measures
- silently repair bad data without surfacing the repair policy
- encode business-critical behavior in comments instead of tests or contracts

## 10. Cross-project examples

Backtester example:

- keep `strategies/` or `domain/alpha/` separate from `execution/`
- keep workflow assembly in `services/` rather than in the event loop

Risk-engine example:

- keep `regime_models/` separate from `risk_models/`
- keep model validation separate from the model implementation

Research-script example:

- keep data loading, feature building, model fitting, and report export in
  separate modules even when the project is still small
