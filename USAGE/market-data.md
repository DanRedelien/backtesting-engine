# Historical Market Data

Use the canonical entrypoint:

```bash
python -m backtest_engine.interfaces.cli.market_data
```

Before running the commands below, complete the one-time terminal preparation in
[install.md](install.md). That guide owns dependency installation and shared
`BTE_` environment setup.

Supported nested commands:

- `download historical-market-data`
- `verify market-data`

## Safe Runbook

1. Prepare provider-specific environment variables from [install.md](install.md).
2. Run a dry-run when symbol resolution, timeframe support, or window behavior
  is uncertain.
3. Run `download historical-market-data`.
4. Run `verify market-data`.
5. Confirm every requested slice reports `PASS`.
6. Only then reference the slice from a backtest `DatasetSpec`.

`DatasetSource.IB` and `DatasetSource.MT5` materialization is blocked when the
latest `validation_manifest.json` is missing, stale, fingerprint-mismatched, or
not `PASS`.

## Dry-Run

Use dry-run first when you want to confirm resolved symbols, timeframes,
operator window semantics, or output paths:

```bash
python -m backtest_engine.interfaces.cli.market_data download historical-market-data --provider mt5 --symbols EURUSD --timeframes 1h --start 2024-01-01 --end 2024-03-01 --dry-run
python -m backtest_engine.interfaces.cli.market_data download historical-market-data --provider ib --symbols ES --timeframes 5m --start 2024-01-01 --end 2024-03-01 --dry-run
```

## Provider History Expectations

The command can only save data that the selected provider can actually return.
When a short-timeframe download stops early, first check provider access before
assuming the CLI is broken.

MT5 expectations:

- MT5 downloads are already chunked and resumable in this project.
- If M1 or M5 returns only a few days, one week, or one month, the usual causes
  are broker/server history depth, the local terminal cache, the exact provider
  symbol, or the terminal chart setting.
- In MetaTrader 5, increase `Tools -> Options -> Charts -> Max. bars in chart`,
  open the exact symbol on the target timeframe, scroll the chart backward, wait
  for older bars to load, then rerun the same download command without
  `--force`.
- Lowering `BTE_DATA__MT5__CHUNK_DAYS` can help unstable large requests, but it
  cannot create history that the terminal cannot access.

IB expectations:

- IB/TWS ingestion here is intended for CME index futures through TWS or IB
  Gateway.
- The project default max-available window is two years:
  `BTE_DATA__IB__MAX_HISTORICAL_YEARS=2`.
- IBKR documents that expired futures data older than two years from the
  contract expiration is unavailable through historical data APIs. Paid market
  data subscriptions may provide broader live/current access for subscribed
  products, but they do not bypass IBKR's documented unavailable-data rules.
- Without the relevant market-data subscription, expect delayed or limited data
  access rather than full historical coverage for subscribed exchange products.

For deeper free FX M1 or tick research data, consider importing a dedicated
historical source such as Dukascopy into the source-cache workflow instead of
relying on broker terminal history.

## Download

MT5 examples:

```bash
python -m backtest_engine.interfaces.cli.market_data download historical-market-data --provider mt5 --symbols EURUSD GBPUSD --timeframes 5m 15m 1d --start 2020-06-01 --end 2026-04-11
python -m backtest_engine.interfaces.cli.market_data download historical-market-data --provider mt5 --symbols EURUSD GBPUSD --timeframes 5m 15m 1d
```

IB examples:

```bash
python -m backtest_engine.interfaces.cli.market_data download historical-market-data --provider ib --symbols ES NQ YM --timeframes 1m 5m 4h --start 2020-06-01 --end 2026-04-11
python -m backtest_engine.interfaces.cli.market_data download historical-market-data --provider ib --symbols ES NQ YM --timeframes 1m 5m 4h
```

Window modes:

- explicit window: pass `--start` and `--end` together
- max-available: omit both `--start` and `--end`

Passing only one edge is a usage failure.

## Verify

Always verify after download:

```bash
python -m backtest_engine.interfaces.cli.market_data verify market-data --provider mt5 --symbols EURUSD GBPUSD --timeframes 5m 15m 1d
python -m backtest_engine.interfaces.cli.market_data verify market-data --provider ib --symbols ES NQ YM --timeframes 1m 5m 4h
```

Detailed per-check output:

```bash
python -m backtest_engine.interfaces.cli.market_data verify market-data --provider mt5 --symbols EURUSD --timeframes 5m --detailed
```

## Exit Codes

- `0`: success
- `1`: runtime failure or partial batch failure
- `2`: CLI usage error

## Output Contracts

Download progress is append-only ASCII output with no carriage-return rewrites:

```text
PROGRESS <provider> <symbol> <timeframe> <pct> rows=<n> date=<YYYY-MM-DD|--> left=<duration|-->
```

Verification output modes:

- default: one compact line per slice
- `--detailed`: stable multi-line per-check report

Compact verification example:

```text
PASS mt5 EURUSD 5m score=87.50% warn=1 bad=0 checks=tick_alignment
FAIL mt5 GBPUSD 5m score=80.00% warn=0 bad=1 checks=required_columns error=VerificationFailedError
```

Detailed verification example:

```text
mt5 EURUSD 5m 2024-01-01T00:00:00+00:00 .. 2024-01-02T00:00:00+00:00: PASS
Observed window: 2024-01-01T00:00:00+00:00 .. 2024-01-02T00:00:00+00:00 (start=covered, end=covered)
Required columns: 100.00% OK
Tick alignment: 75.00% WARN
Overall score: 87.50% (applicable=2/3, warn=1, bad=0)
```

## Provider Prerequisites

Common prerequisites:

- complete dependency installation and shared environment preparation from
[install.md](install.md)
- choose symbols present in the canonical symbol map
- choose timeframes supported by the selected provider
- set `BTE_DATA__SOURCE_CACHE_ROOT` if you do not want the default
`data/cache`

MT5 prerequisites:

- run on Windows with a local MetaTrader 5 terminal available
- ensure the terminal can log in before running the CLI
- set `BTE_DATA__MT5__BROKER_TIMEZONE_NAME`
- optionally set `BTE_DATA__MT5__TERMINAL_PATH`

IB prerequisites:

- run TWS or IB Gateway locally
- set `BTE_DATA__IB__HOST` and `BTE_DATA__IB__PORT` if you are not using the
defaults
- use the currently supported CME index futures scope
- set `--end` no later than the current UTC time

## Output Layout

Each managed slice is stored under:

```text
data/cache/<provider>/<canonical_symbol>/<timeframe>/
```

Typical contents:

```text
bars.parquet
source_manifest.json
validation_manifest.json
checkpoint.json
```

IB futures slices may also include:

```text
roll_manifest.json
raw_contracts/
```

## Recovery

If a download is interrupted, rerun the same download command first. The
provider-managed flow persists partial parquet writes and `checkpoint.json` so a
backfill can resume instead of restarting the whole window.

Use `--force` only when you intend to discard resumable state for the targeted  
slice:

```bash
python -m backtest_engine.interfaces.cli.market_data download historical-market-data --provider mt5 --symbols EURUSD --timeframes 1h --start 2024-01-01 --end 2024-03-01 --force
```

## Common Failure Patterns

- unknown symbol: the symbol is missing from the canonical symbol map
- unsupported timeframe: the provider does not implement that timeframe
- insufficient history: the provider could not cover the requested UTC window
- missing validation manifest: download finished but verification was not run
- fingerprint mismatch: `bars.parquet` changed after the last verification
- non-finite OHLCV values: the slice contains null, `NaN`, infinite, or
non-numeric bar values and must be re-downloaded or regenerated
- invalid calendar or timezone policy: validation could not resolve session
metadata
- MT5 broker timezone missing: set `BTE_DATA__MT5__BROKER_TIMEZONE_NAME`
- IB end timestamp in the future: rerun with `--end` no later than current UTC

## Next Reads

- [Install and Terminal Preparation](install.md)
- [Microstructure Calibration](microstructure-calibration.md)
- [README.md](../README.md)
- [docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md)
- [docs/MODULE_MAP.md](../docs/MODULE_MAP.md)
- [docs/agents.md](../docs/agents.md)
