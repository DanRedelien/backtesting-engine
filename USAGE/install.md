# Install and Terminal Preparation

Use this guide once when you first set up the repository, and again only when
your local environment changes. The other usage guides assume this preparation
is already complete and do not repeat it.

## Python Requirement

Python `3.11+` is required.

## Install Dependencies

Run from the repository root:

```bash
python -m pip install -r requirements.txt
```

## Prepare Shared Environment Variables

Settings are environment-driven through the `BTE_` prefix. Prepare these values
once in the terminal session you will use for the repository workflows below.

Common examples:

```bash
BTE_RUNTIME__RESULTS_ROOT=results
BTE_RUNTIME__NAUTILUS_ROOT=var/runtime/nautilus
BTE_DATA__SOURCE_CACHE_ROOT=data/cache
BTE_DATA__IB__HOST=127.0.0.1
BTE_DATA__IB__PORT=7497
BTE_DATA__MT5__BROKER_TIMEZONE_NAME=Europe/Riga
```

PowerShell:

```powershell
$env:BTE_RUNTIME__RESULTS_ROOT = "results"
$env:BTE_RUNTIME__NAUTILUS_ROOT = "var/runtime/nautilus"
$env:BTE_DATA__SOURCE_CACHE_ROOT = "data/cache"
$env:BTE_DATA__IB__HOST = "127.0.0.1"
$env:BTE_DATA__IB__PORT = "7497"
$env:BTE_DATA__MT5__BROKER_TIMEZONE_NAME = "Europe/Riga"
```

If you use the default repository paths and the default local IB host and port,
you only need to export the variables that differ from those defaults. The
examples above are the shared values most operators touch first.

Provider-specific details still matter:

- MT5 workflows require `BTE_DATA__MT5__BROKER_TIMEZONE_NAME`
- IB workflows may require `BTE_DATA__IB__HOST` and `BTE_DATA__IB__PORT`
- all workflows may override `BTE_DATA__SOURCE_CACHE_ROOT`,
  `BTE_RUNTIME__RESULTS_ROOT`, or `BTE_RUNTIME__NAUTILUS_ROOT`

The market-data and future backtesting guides reference this setup instead of
repeating it.

## Quality Gates

Use these commands to confirm the local tree is healthy before making changes
or troubleshooting runtime behavior:

```bash
ruff check .
mypy src tests
lint-imports --config .importlinter
pytest -q
```

## Saved-Bundle Dashboard

Launch the FastAPI terminal UI from the repository root:

```bash
python -m uvicorn backtest_engine.interfaces.terminal_ui.app:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`.

The root URL selects the newest loadable saved bundle under
`results/<bundle_id>/bundle.json`. Open a specific saved bundle directly with:

```text
http://127.0.0.1:8000/bundles/<bundle_id>
```

The first viewport is a read-only four-panel saved-bundle dashboard:

- stats
- strategy correlation
- equity
- drawdown

The terminal UI also exposes JSON routes for:

- bundle catalog and bundle detail reads
- scenario rerun planning for saved portfolio bundles
- study summary and champion reads
- recommendation and latest-recommendation reads

Dashboard panels read only parquet artifact locations declared by the saved
bundle. Missing or insufficient artifacts render empty states instead of
starting a run or fabricating data.

## Next Guides

- [Historical Market Data](market-data.md)
- [Backtesting](backtesting.md)
- [WFO Optimization](wfo.md)
