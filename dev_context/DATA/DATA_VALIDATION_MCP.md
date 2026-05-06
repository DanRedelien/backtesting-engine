# Data Validation MCP

Use this document for quality gates on market data before research, backtests,
risk calculations, or production deployment.

## 1. Validation is a first-class workflow

Data validation is not optional cleanup. It is a protective layer between raw
market data and every downstream model.

## 2. Common validation categories

Every serious pipeline should consider some version of:

- schema validation
- timestamp ordering
- duplicate timestamps
- gap detection
- OHLC consistency
- volume sanity
- price continuity
- roll-transition checks for continuous futures
- missing required columns

## 3. Gap policy

Define gaps relative to the timeframe and trading calendar.

Examples:

- a 30-minute gap is severe for 1-minute data
- the same gap may be expected for a daily session boundary

Never count weekend and session-boundary behavior as accidental corruption
without checking the market convention first.

## 4. OHLC integrity

For OHLC bars, validate at least:

- `high >= low`
- `high >= max(open, close)`
- `low <= min(open, close)`

If derived columns exist, validate them too when they matter.

Example:

- if an `average` field is supposed to describe the candle, it should not sit
  outside the candle range unless the source explicitly defines it otherwise

## 5. Price continuity and roll checks

Continuous futures can pass basic OHLC checks while still being economically
wrong because of a failed rollover adjustment.

If the dataset includes contract metadata, validate:

- contract change timestamps
- suspicious close-to-close jumps at roll points
- consistency between roll policy and price adjustments

## 6. Output contract

A validation step should return structured results, not only console text.

Useful fields:

- pass / fail status
- quality score or severity
- counts of each anomaly type
- a bounded list of representative issues
- enough metadata to trace the dataset that was validated

## 7. Cross-project examples

Backtester example:

- validate cached OHLCV files before a backtest or walk-forward run
- include roll-jump checks for continuous futures

Risk-engine example:

- validate return inputs before VaR or stress calculations
- reject stale or misaligned price histories before model execution

Research-script example:

- run schema, timestamp, and gap checks before feature engineering
- store validation results alongside experiment outputs
