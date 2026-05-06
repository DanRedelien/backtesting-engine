# Backtesting Engine

[![CI](https://github.com/DanRedelien/backtesting-engine/actions/workflows/ci.yml/badge.svg?branch=v2-alpha)](https://github.com/DanRedelien/backtesting-engine/actions/workflows/ci.yml?query=branch%3Av2-alpha)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)

Research-grade backtesting platform centered on one Nautilus execution
boundary, typed run contracts, reproducible artifacts, and explicit module
ownership.

> [!NOTE]
> This project builds on [NautilusTrader](https://github.com/nautechsystems/nautilus_trader)
> as the core trading/backtesting execution framework. NautilusTrader is an
> independent open-source project by Nautech Systems; this repository is not
> affiliated with or endorsed by Nautech Systems.

## Overview

- one canonical Nautilus runtime boundary
- typed single, portfolio, batch, walk-forward, and study orchestration
- provider-managed historical market-data ingestion and verification for IB/TWS
  and MT5
- package-discovered concrete strategy cartridges under
  `src/backtest_engine/strategies/`
- persisted bundles, study artifacts, and live allocation recommendations
- thin CLI, terminal UI, and worker delivery surfaces

## Public Surfaces

- typed Python orchestration through
  `backtest_engine.bootstrap.composition_root.build_application_container(...)`
- historical market-data CLI:
  `python -m backtest_engine.interfaces.cli.market_data`
- offline spread calibration CLI:
  `python -m backtest_engine.interfaces.cli.calibration spread`, which publishes
  generated execution-cost YAML, a v2 diagnostics report, and review PNGs
- backtest CLI:
  `python -m backtest_engine.interfaces.cli.backtest`
  or `bte-backtest` for installed environments, with `--dry-run` for
  data/catalog/strategy preparation without execution and
  `--execution-costs-path` for generated calibration YAML handoff
- terminal UI app:
  `backtest_engine.interfaces.terminal_ui.app:app`
  for bundle, study, and recommendation reads plus scenario rerun planning

Operator command examples live in `USAGE/README.md`.

## Quick Start

Latest v2 alpha branch:

```bash
git clone -b v2-alpha https://github.com/DanRedelien/backtesting-engine.git
cd backtesting-engine
python -m pip install -r requirements.txt
pytest -q
```

Python `3.11+` is required.

## Quality Gates

```bash
ruff check .
mypy src tests
lint-imports --config .importlinter
pytest -q
```

## Docs Map

- [Usage Runbook](USAGE/README.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Module Map](docs/MODULE_MAP.md)
- [Import Rules](docs/IMPORT_RULES.md)
- [Writing a Strategy](docs/WRITING_STRATEGY.md)
- [Agent Context](docs/agents.md)
- [Docs Index](docs/README.md)
- [Third-Party Notices](docs/THIRD_PARTY_NOTICES.md)
- [Architecture Decisions](docs/adr/)
- [Development Context](dev_context/README.md)

## CI

The CI workflow runs the same declared gates as the local developer contract:

- `ruff check .`
- `mypy src tests`
- `lint-imports --config .importlinter`
- `pytest -q`

## License

This project is licensed under the [MIT License](LICENSE).

## Credits

- [NautilusTrader](https://github.com/nautechsystems/nautilus_trader) provides
  the core execution and backtesting framework used by this project.
- The offline calibration EDGE estimator follows the MIT-licensed reference
  behavior from [`eguidotti/bidask`](https://github.com/eguidotti/bidask);
  see [Third-Party Notices](docs/THIRD_PARTY_NOTICES.md).
