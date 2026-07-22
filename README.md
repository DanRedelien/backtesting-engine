> [!NOTE]
> **Project status**
>
> The `main` branch contains the latest stable v1 release of Backtesting Engine.
>
> Active development is now focused on **Backtesting Engine v2** in the [`v2-alpha`](../../tree/v2-alpha) branch.  
> v2 is a major upgrade built around **NautilusTrader**, with a cleaner architecture, faster execution, and better support for realistic futures/FX/CFD backtesting.
> The development will be renewed closer to the end of 2026.
> 
> Use `main` if you want the last stable v1 version.  
> Use `v2-alpha` if you want to follow the current v2 alpha work.
>
> Current v2 alpha tag:
>
> ```bash
> git checkout v2.0.0-alpha.1
> ```

# Backtesting Platform

[![CI](https://github.com/DanRedelien/futures-backtesting-engine/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/DanRedelien/futures-backtesting-engine/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)

Futures-focused research platform for:

- single-strategy backtests
- walk-forward optimization
- multi-strategy portfolio backtests
- terminal-style analytics review via FastAPI

The codebase is optimized for research workflows where no-lookahead execution, artifact reproducibility, and post-run analytics matter more than framework breadth.

## Screenshots

### Terminal UI Overview

<img width="1593" height="734" alt="image" src="https://github.com/user-attachments/assets/a1a4cc0b-1a42-43bb-837f-b039d2e12b3f" />


### Portfolio Analytics

<img width="1586" height="732" alt="image" src="https://github.com/user-attachments/assets/b67de6f8-3a00-4109-bdcb-13fccfa6aa2d" />


### Exit Analysis

<img width="1553" height="712" alt="image" src="https://github.com/user-attachments/assets/4eb47d2b-c662-4f1a-be33-14c456768743" />


### Stress Testing / Scenario Queue

<img width="1550" height="714" alt="image" src="https://github.com/user-attachments/assets/2c125d67-4c4e-40d7-945e-85d7ff652a64" />


<img width="1551" height="709" alt="image" src="https://github.com/user-attachments/assets/bd2bb28b-8948-4cff-bfbc-2968e032afc3" />


### CLI Workflow

<img width="941" height="708" alt="image" src="https://github.com/user-attachments/assets/b80e5def-04cb-41e6-a4bc-9c06fb6d0856" />


## What This Project Does

- Runs single-asset event-driven backtests on cached OHLCV futures data.
- Runs walk-forward validation through Optuna-based parameter search.
- Runs portfolio backtests with shared capital, rebalancing, allocation, and slot-level execution.
- Persists canonical artifacts for later inspection in the terminal UI.
- Supports scenario reruns and portfolio-level analytics from saved artifacts.

## Core Guarantees

- No-lookahead contract: signal at `close[t]`, execution at `open[t+1]`.
- Shared-capital accounting in the portfolio engine.
- Artifact-first workflow: runs write reusable bundles to disk for later analysis.
- Clear layer boundaries: CLI -> services -> engines/runtime.

## Quick Start

```bash
git clone https://github.com/DanRedelien/backtesting-engine.git
cd backtesting-engine
pip install -r requirements.txt
pytest tests/
```

Python `3.11+` is recommended.

`pyproject.toml` already configures pytest `pythonpath`, so no manual `PYTHONPATH` export is needed.

## Common Commands

```bash
# Download cached market data
python run.py --download ES NQ YM RTY CL GC SI

# Single backtest
python run.py --backtest --strategy sma_pullback --symbol ES --tf 1h

# Walk-forward optimization
python run.py --wfo --strategy ict_ob --symbol ES --tf 1h

# Portfolio backtest
python run.py --portfolio-backtest
python run.py --portfolio-backtest --portfolio-config src/backtest_engine/portfolio_layer/portfolio_config_example.yaml

# Lightweight batch backtests with one combined Matplotlib popup
# Batch summary MDD% is drawdown depth (non-negative). Plot filtering uses settings.batch_plot_max_drawdown_pct (default 80).
python run.py batch --strategies sma_pullback ict_ob --symbol ES NQ --tf 1h 30m

# Lightweight WFO batch sweep with verdict heatmap and candidate exports
python run.py wfo-batch --strategies sma_pullback ict_ob --symbol ES --tf 1h

# Launch terminal UI for the latest artifacts
python run.py --dashboard

# Run a backtest and open the UI after completion
python run.py --portfolio-backtest --dashboard
```

## Redis Requirement

The Stress Testing tab in the terminal UI uses Redis/RQ. The rest of the platform does not require Redis.

Install Redis only if you want scenario queueing from the dashboard.

Windows:

```bash
winget install Redis.Redis
```

macOS:

```bash
brew install redis
```

Ubuntu/Debian:

```bash
sudo apt install redis-server
```

## Project Layout

```text
.
|-- README.md
|-- CONTRIBUTING.md
|-- docs/
|   |-- ARCHITECTURE.md
|   |-- EXECUTION_CONTRACT.md
|   |-- MODULE_MAP.md
|   `-- agents.md
|-- cli/
|   |-- single.py
|   |-- wfo.py
|   |-- portfolio.py
|   |-- batch.py
|   `-- wfo_batch.py
|-- run.py
|-- tests/
|   |-- README.md
|   |-- unit/
|   `-- regression/
`-- src/
    |-- data/
    |-- strategies/
    `-- backtest_engine/
        |-- analytics/
        |-- config/
        |-- execution/
        |-- optimization/
        |-- portfolio_layer/
        |-- runtime/
        |-- services/
        |-- single_asset/
        `-- serialization.py
```

## Architecture At A Glance

- `run.py` parses CLI args and dispatches to `cli/`.
- `cli/` is intentionally thin and delegates orchestration to `src/backtest_engine/services/`.
- `src/backtest_engine/single_asset/engine.py` is the canonical single-asset execution engine.
- `src/backtest_engine/execution/` is the shared execution kernel package.
- `src/backtest_engine/config/` is the canonical home for runtime settings models.
- `src/backtest_engine/portfolio_layer/engine/engine.py` is the portfolio event loop with shared capital and multi-slot execution.
- `src/backtest_engine/runtime/terminal_ui/` is the active FastAPI analytics UI.
- `src/backtest_engine/analytics/` contains artifact builders, reports, metrics, and shared analytics transforms.
- `src/backtest_engine/services/scenario_job_service.py` remains the public scenario-queue entry point, with adjacent helper modules for metadata storage and worker execution.
- `src/data/ib_fetcher.py` remains the public IB data entry point, with adjacent helper modules for contract resolution, cache/checkpoint storage, and historical backfill orchestration.

## Results And Artifacts

- Single runs write to `results/`.
- Portfolio runs write to `results/portfolio/`.
- Scenario reruns write to `results/scenarios/<scenario_id>/...`.
- The terminal UI reads saved artifacts rather than requiring a rerun.

## Documentation Map

- [Architecture](docs/ARCHITECTURE.md) - layer boundaries, engine roles, artifact flow.
- [Execution Contract](docs/EXECUTION_CONTRACT.md) - shared execution-kernel semantics, gap rules, and intrabar conflict policy.
- [Module Map](docs/MODULE_MAP.md) - quick reference for canonical packages and contributor entry points.
- [Agent Context](docs/agents.md) - compact project context for LLMs and automation agents.
- [Usage Guide](USAGE.md) - CLI examples, common workflows, and dashboard launch commands.
- [Contributing Guide](CONTRIBUTING.md) - setup, workflow, tests, strategy additions, PR expectations.
- [Analytics README](src/backtest_engine/analytics/README.md)
- [Config README](src/backtest_engine/config/README.md)
- [Execution README](src/backtest_engine/execution/README.md)
- [Optimization README](src/backtest_engine/optimization/README.md)
- [Portfolio Layer README](src/backtest_engine/portfolio_layer/README.md)
- [Runtime README](src/backtest_engine/runtime/README.md)
- [Single-Asset README](src/backtest_engine/single_asset/README.md)
- [Terminal UI README](src/backtest_engine/runtime/terminal_ui/README.md)
- [Strategies README](src/strategies/README.md)
- [Tests README](tests/README.md)

## Strategy Registry

Strategies are exposed through `src/strategies/registry.py`.

Current canonical IDs:

- `ict_ob`
- `sma_pullback`
- `three_bar_mr` (three-bar mean reversion)

The alias `ict_order_block` maps to `ict_ob` and is also accepted by the CLI.
