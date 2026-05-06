# Data Storage And Cache MCP

Use this document when designing local caches, parquet layers, research data
stores, or larger market-data lakes.

## 1. Choose the storage pattern by scale

There is no single correct pattern.

Common tiers:

- simple local file cache
Good for prototypes, local backtests, and single-user workflows.
- partitioned parquet lake
Good for medium-scale historical datasets and reproducible research.
- database or object-store backed datasets
Good for large teams, concurrent readers, and operational systems.
- hot/cold split
Good when live append traffic and historical snapshots have different write
and query characteristics.

## 2. Universal storage principles

- Make the storage contract explicit.
- Define schema, timezone convention, and symbol naming convention.
- Preserve provenance: source, timeframe, normalization, roll policy, and
  generation time when relevant.
- Prefer immutable historical artifacts when reproducibility matters.
- Avoid silent in-place rewrites of canonical history.

## 3. Cache design rules

- A cache is not the source of truth. It is a reproducible acceleration layer.
- Define freshness rules explicitly.
- Define invalidation or refresh policy explicitly.
- Avoid combining read, fetch, transform, and validation in one opaque method if
  the system is growing.

## 4. File and partition strategy

Choose a shape that matches data volume and access pattern:

- `SYMBOL_timeframe.parquet`
- symbol and timeframe directories
- partitioning by year / month / day
- dataset partitioning by venue, asset class, or instrument family

Do not use sophisticated partitioning only because it sounds scalable. Use it
when the operational benefit is real.

## 5. Schema guidance

At minimum, define:

- timestamp column or index
- OHLCV fields when applicable
- instrument metadata fields when needed
- timezone convention
- contract identifier for continuous futures when roll analysis matters

Document important optional columns such as:

- `average`
- `bar_count`
- `open_interest`
- `contract`
- vendor-specific trade counts

## 6. Schema versioning and metadata manifests

Institutional-grade systems should version not only the data, but also the
meaning of the data.

Track at least:

- `schema_version`
- `dataset_version`
- source vendor or broker
- ingest timestamp
- normalization policy
- roll policy for futures
- adjustment policy for retroactive changes

Store this metadata in one of:

- a sidecar manifest file
- parquet metadata
- a dataset catalog table
- an artifact registry

## 7. Backward compatibility rules

When the schema changes:

- add new columns in a backward-compatible way when possible
- do not silently change the meaning of an existing column
- bump `schema_version` when semantics change
- provide an upgrade or compatibility layer if old datasets must remain usable

Breaking examples:

- changing `close` from settlement to last-trade close without a version bump
- changing timestamps from exchange-local to UTC-naive without metadata
- replacing raw linked futures with back-adjusted history under the same dataset
  identifier

## 8. Retroactive adjustments

Historical data may change after first ingestion because of:

- corporate actions
- vendor corrections
- contract-roll policy changes
- improved back-adjustment logic

Policy guidance:

- do not silently overwrite canonical history if reproducibility matters
- publish a new dataset version or adjustment layer
- record why the change happened
- keep enough metadata to reproduce both old and new outputs when required

For futures specifically, document whether historical series are:

- raw linked
- additive back-adjusted
- multiplicative back-adjusted
- ratio-adjusted

and make that choice visible to downstream users.

## 9. Cross-project examples

Small research example:

- one local parquet file per symbol and timeframe
- one JSON manifest describing source and generation time

Backtester example:

- local cache files for repeatable runs
- separate validation step before the engine consumes the data

Risk-platform example:

- partitioned history plus dataset manifests
- explicit schema versions and adjustment policy for reproducible risk reports

## 10. When to upgrade

Move from simple cache to a richer storage design when you now need:

- much larger data volume
- concurrent readers and writers
- lazy queries across large time ranges
- strict provenance across many datasets
- live append plus historical snapshots
