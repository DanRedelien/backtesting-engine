# Writing a Strategy

Concrete strategies are cartridge packages under
`src/backtest_engine/strategies/<implementation_id>/`. The folder name is the
runtime `StrategySpec.implementation_id`.

## Folder Layout

Required files:

```text
src/backtest_engine/strategies/<implementation_id>/
  __init__.py
  definition.py
  parameters.py
  nautilus_strategy.py
  README.md
```

Optional files:

```text
policy.py
signals.py
risk.py
tests/
```

Do not use vague module names such as `helpers.py`, `common.py`, or `misc.py`.
`README.md` is required for authoring clarity, but the runtime loader never
reads it.

## Implementation ID

`implementation_id` must match:

```text
^[a-z][a-z0-9_]*$
```

The folder name and `STRATEGY_DEFINITION.implementation_id` must be identical.

## Definition Entrypoint

`definition.py` is the only loader entrypoint. It must export exactly one
runtime definition named `STRATEGY_DEFINITION`.

`STRATEGY_DEFINITION` must be a `StrategyPackageDefinition` with:

- `implementation_id`
- `strategy_path`
- `config_path`
- `build_parameters`
- `build_config`
- `min_legs`
- `max_legs`
- optional `validate_strategy_spec`

`strategy_path` and `config_path` point at classes in the same package's
`nautilus_strategy.py`. The loader imports that module and verifies both named
attributes exist when the package definition is loaded.

## Parameters

`parameters.py` defines one validated Pydantic model for the strategy package.
`build_parameters(strategy_spec)` receives `PortfolioStrategySpec` and returns
that validated model instance.

Use `StrategySpec.parameters` for external knobs and derive stable bindings
such as `strategy_id`, `symbol`, and `leg_symbols` from the canonical
`PortfolioStrategySpec`. Prefer model validation over ad hoc dictionary checks.

## Config Builder

`build_config(strategy_spec, parameters, strategy_items, slot_sizing)` returns
the Nautilus config payload as `dict[str, JsonValue]`.

Rules:

- preserve leg order from `strategy_spec.legs`
- use only resolved catalog items passed in by the resolver
- use `slot_sizing` only when provided; it exposes only `slot_multiplier`
- return exact JSON-compatible Python values only
- do not perform file I/O, network I/O, environment reads, hidden lookups, or
  registry mutation

Config values may be nested objects and arrays, but every value must already be
JSON-compatible before serialization: `dict[str, ...]`, `list[...]`, `str`,
finite built-in `int` or `float`, `bool`, or `None`. The resolver rejects
tuples, `Decimal`, datetimes, NumPy scalars, arbitrary objects, `NaN`, and
infinities instead of coercing them.

## Imports

Concrete strategy production modules may import:

- Python standard library modules
- installed project dependencies
- `backtest_engine.core`
- `backtest_engine.domain`
- `backtest_engine.strategies.package_contracts`
- modules inside the same strategy folder

Concrete strategy production modules must not import:

- `backtest_engine.application`
- `backtest_engine.bootstrap`
- `backtest_engine.infrastructure`
- `backtest_engine.interfaces`
- another `backtest_engine.strategies.<other_id>` package

Use relative or same-package absolute imports for package-local code.

## Side Effects

Strategy modules must be side-effect free on import. Importing
`definition.py`, `parameters.py`, `policy.py`, `signals.py`, `risk.py`, or
`nautilus_strategy.py` must not open files, read environment variables, make
network calls, register global objects, or mutate shared runtime state.

## Tests

Put concrete strategy tests inside the strategy folder:

```text
src/backtest_engine/strategies/<implementation_id>/tests/
```

Top-level tests should remain generic and discovery-based. Do not maintain a
handwritten list of shipped strategy IDs in central resolver tests.

## Loader And Resolver Failures

The loader and resolver raise `InfrastructureError` for malformed cartridges:

- `implementation_id` does not match the required regex
- `definition.py` cannot be imported
- `definition.py` fails because a dependency cannot be imported
- `definition.py` does not export `STRATEGY_DEFINITION`
- `STRATEGY_DEFINITION` is not a `StrategyPackageDefinition`
- exported `implementation_id` does not match the folder name
- `strategy_path` or `config_path` does not point at
  `backtest_engine.strategies.<implementation_id>.nautilus_strategy`
- `strategy_path` or `config_path` names an attribute that does not exist in
  `nautilus_strategy.py`
- strategy leg count is below `min_legs` or above `max_legs`
- `validate_strategy_spec` raises
- `build_parameters` raises or returns a non-Pydantic model
- `build_config` raises, returns a non-dictionary, or returns non-JSON config

Package definitions are cached per process after successful loads. Use
`clear_strategy_package_definition_cache()` only for tests or development
reloads; it clears the definition cache, invalidates import caches, and removes
loaded concrete strategy package modules from `sys.modules`.
