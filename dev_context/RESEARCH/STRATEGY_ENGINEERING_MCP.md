# Strategy Engineering MCP

Use this document when creating, reviewing, or refactoring alpha, signal, or
strategy components.

## 1. There is no single universal strategy contract

Different systems need different strategy interfaces. Common patterns include:

- vectorized signal generator
  Input: normalized DataFrame(s). Output: signals or features.
- event-driven order emitter
  Input: current bar and engine state. Output: orders or intents.
- portfolio target model
  Input: market state and portfolio state. Output: target weights or target
  positions.
- forecast component
  Input: features. Output: probabilities, scores, returns, or risk forecasts.

Choose one primary contract for the project and keep it stable.

## 2. Universal rules

- Keep the strategy focused on alpha logic.
- Keep external I/O outside the strategy.
- Precompute expensive features when the contract allows it.
- Keep per-step execution lightweight in event-driven engines.
- Make assumptions about timing and bar availability explicit.

## 2.5. ML-driven strategy pipeline

For ML, HMM, or probabilistic strategies, keep these stages distinct:

- feature engineering
- model training
- model artifact storage
- online or backtest inference
- signal mapping
- risk and execution handling

Do not hide training, inference, and order generation inside one opaque class.

## 2.6. Feature engineering rules for ML

- define the feature schema explicitly
- document lookback windows and normalization rules
- fit scalers, encoders, and feature transforms on training data only
- keep training-time feature logic reproducible in inference
- version the feature schema when columns or meanings change

## 3. No-lookahead discipline

Never let a strategy use information that would not have been available at the
decision time.

Common failure modes:

- accessing future rows
- leaking post-close information into intrabar decisions
- using globally fitted transforms before time splits
- naive multi-timeframe joins

## 4. Multi-timeframe rules

If a strategy mixes multiple timeframes, define exactly when higher-timeframe
information becomes available.

Do not blindly apply `shift(1)` as a universal fix.

Correct handling depends on:

- how timestamps are defined
- whether bars are source-native or resampled
- whether the engine already enforces next-bar execution
- whether the join is for features, decisions, or execution levels

## 4.5. Probabilistic outputs are not orders

Posterior probabilities, class scores, and regime scores are intermediate model
outputs. They must be converted into trading intent by an explicit mapping
policy.

Common mapping patterns:

- threshold gating
- rank-and-select
- expected-return minus risk-cost threshold
- regime filter such as `trade only if P(stress) < x`
- hysteresis bands to prevent signal flapping

Document:

- the score being used
- the calibration rule
- the threshold or mapping function
- how uncertainty affects the final signal

## 5. Parameter design

Strategies that will be optimized should expose a clear parameter interface.

Good optimized parameters usually describe:

- lookback lengths
- threshold levels
- volatility scaling
- entry offsets
- regime or filter choices

Avoid optimizing:

- logging toggles
- cosmetic flags
- arbitrary micro-precision increments
- platform-level risk and capital settings unless the project explicitly treats
  them as model parameters

## 6. Risk ownership

Default guidance:

- strategy owns signal logic
- execution layer owns fill semantics
- risk layer owns portfolio-level sizing, guards, and limits

Projects may intentionally combine some of these, but the ownership choice must
be explicit.

## 7. Validation link for ML and stateful strategies

If the strategy depends on fitted models or overlapping labels:

- use time-respecting splits
- use purging or embargo when holdings or labels overlap
- tune thresholds and hyperparameters inside the training loop only
- evaluate final signal behavior on unseen future data

This is especially important for:

- HMM regime filters
- classifier-based entry models
- return-forecast models
- meta-labeling pipelines

## 8. Cross-project examples

Event-driven backtester example:

- strategy consumes current bar and engine state
- precomputed indicators or features are prepared ahead of time
- output is explicit order intent

HMM / risk-aware strategy example:

- feature pipeline produces volatility and regime features
- HMM emits posterior regime probabilities
- signal layer maps those probabilities into gating or sizing rules

ML alpha example:

- feature builder creates tabular inputs
- model inference produces scores or probabilities
- signal mapper converts model output into entry, exit, or ranking decisions
