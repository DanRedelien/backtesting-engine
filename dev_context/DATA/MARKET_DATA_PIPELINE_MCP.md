# Market Data Pipeline MCP

Use this document for broker, exchange, vendor, and historical market-data
workflows.

Scope:

- futures, equities, FX, crypto, options, rates, and bonds
- historical and streaming data
- direct broker feeds and third-party vendors

## 1. Core principles

- Separate transport from normalization.
- Separate instrument discovery from bar or tick retrieval.
- Normalize timestamps, schema, and column names before downstream use.
- Treat data quality as part of the pipeline, not an afterthought.
- Make source-specific assumptions explicit.

## 2. Adapter design

Each source should have a dedicated adapter or connector layer.

Avoid one giant class that mixes:

- IB
- CCXT
- Polygon
- CQG
- Bloomberg
- custom CSV imports

Different sources have different:

- authentication
- pacing rules
- time conventions
- symbol formats
- rollover behavior
- field availability

## 3. Timeframe policy

Prefer native vendor or exchange timeframes when the source provides them
reliably.

Only resample locally when:

- the source does not provide the required timeframe
- the resampling policy is documented
- the precision loss is acceptable for the use case

Always document whether higher timeframes are:

- source-native
- locally resampled
- stitched from lower-frequency or higher-frequency bars

## 4. Futures rolling

Continuous futures require an explicit roll policy. Common choices:

- date-based roll
- volume-based roll
- open-interest-based roll
- exchange-specific first-notice or last-trade policies

Also define:

- whether the series is raw linked or back-adjusted
- how the adjustment is computed
- what metadata is kept about the active contract

Do not hide roll methodology behind a generic `load_data()` call.

## 5. Reliability requirements

Production-grade adapters should define:

- pacing or rate-limit controls
- retry policy
- checkpoint or resume strategy
- duplicate-bar handling
- partial-download behavior
- stale-data detection

## 6. Timestamp and timezone rules

- Normalize all downstream timestamps to a documented convention.
- Keep exchange-local session logic explicit when it matters.
- Do not mix naive and timezone-aware timestamps in the same pipeline stage.
- If a vendor uses session labels or local timestamps, preserve enough metadata
  to reconstruct the original meaning.

## 7. Cross-project examples

Backtester example:

- `ib_adapter.py` or `exchange_adapter.py` handles transport
- `roll_engine.py` or `contract_selector.py` handles futures continuity
- `data_validator.py` applies quality gates before backtests

Risk-engine example:

- `market_data/prices.py` normalizes returns inputs
- `reference_data/instruments.py` tracks calendars and identifiers
- `validation/ingest_checks.py` blocks corrupted datasets before model runs

Research-script example:

- `load_prices.py` fetches or loads data
- `normalize_prices.py` standardizes fields and timestamps
- `validate_prices.py` runs gap and OHLC checks before analysis
