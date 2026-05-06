# VaR And WHS MCP

This is a specialized implementation-oriented document for regime-aware
Value-at-Risk and Expected Shortfall models that use weighted historical
simulation.

It is not a default template for all quantitative projects.

Historical note: this family of guidance originated from a prior
HMM-driven adaptive VaR + WHS project and is kept here as a focused risk-model
reference.

## 1. Appropriate use cases

Use this document when the task is explicitly about:

- VaR or ES forecasting
- weighted historical simulation
- regime-aware tail-risk models
- risk backtesting and coverage analysis

## 2. Core idea

Standard historical simulation weights all observations equally.

Weighted historical simulation changes the weights, often to emphasize:

- recency
- regime similarity
- stress regimes
- instrument-specific behavior

Regime-aware WHS is useful when the current market state should influence how
relevant old observations are.

## 3. Required design choices

Any WHS implementation must define:

- return measure
- lookback window
- weighting rule
- fallback behavior when weights collapse
- VaR and ES extraction method
- validation procedure

## 4. Weighting mechanics

All weights must be:

- non-negative
- normalized to sum to 1
- computed from information available at decision time

Common weighting families:

- equal-weight HS
  `w_k = 1 / W`
- exponential time decay
  `w_k is proportional to lambda^age_k`, with `0 < lambda < 1`
- kernel similarity weighting
  `w_k is proportional to K(d(state_t, state_k) / h)`
- posterior-state overlap
  `w_k is proportional to p_t^T p_k`, where `p_t` and `p_k` are regime
  posterior vectors

The correct choice depends on the model design. A risk engine must document why
its weighting rule is economically justified.

## 5. Regime similarity options

If the current state is represented by a scalar stress probability, common
similarity choices include:

- linear similarity
  `sim_k = max(0, 1 - |p_t - p_k|)`
- Gaussian kernel
  `sim_k = exp(-((p_t - p_k)^2) / (2 h^2))`
- triangular or Epanechnikov kernels
  useful when you want compact support

If the current state is represented by a full posterior vector from an HMM or
classifier, common similarity choices include:

- posterior dot product
  `sim_k = p_t^T p_k`
- cosine similarity
- distance-based kernels over the posterior vector

These are defaults, not laws. The important requirement is that the similarity
metric is stable, interpretable, and available at time `t`.

## 6. Weighted tail extraction

One valid specialized design is:

- estimate a current stress probability
- compare it with historical regime probabilities
- weight historical returns by similarity to the current regime
- compute weighted tail metrics from those observations

For weighted VaR:

1. sort returns ascending
2. reorder weights to match the sorted returns
3. compute cumulative weights
4. take the first return where cumulative weight reaches tail probability
5. optionally interpolate between adjacent points

For weighted ES:

- average the tail observations using the same weights
- document whether the VaR boundary point is fully or partially included

## 7. Effective sample size and concentration control

Effective sample size:

`ESS = 1 / sum(w_k^2)`

Interpretation:

- `ESS ~= W` means weights are broad and stable
- low `ESS` means the model is trusting too few observations

Reasonable default heuristics:

- warning zone: `ESS < max(20, 0.10 * W)`
- fallback zone: `ESS < max(10, 0.05 * W)`

These thresholds are implementation defaults, not universal laws. Thin markets,
short windows, or highly concentrated stress states may require different
limits, but the chosen limits must be explicit.

## 8. Fallback taxonomy

A WHS model should define fallback behavior before deployment.

Common fallbacks:

- equal-weight HS
  Use when regime inputs are missing but returns history is valid.
- exponential-decay HS
  Use when regime similarity is unstable but recency weighting is still trusted.
- parametric VaR / ES
  Use when history is too short or tail support is too sparse.
- no-forecast / halt
  Use when both model inputs and fallback inputs fail quality gates.

Typical triggers:

- regime model failed or produced NaNs
- `ESS` below the hard threshold
- fewer than the minimum required valid returns in the lookback window
- data-quality gate failure
- impossible portfolio return construction

## 9. Portfolio construction rules

If the model runs on a portfolio rather than a single asset:

- define whether returns are arithmetic or log returns
- aggregate cross-sectional returns in a mathematically consistent way
- document rebalancing assumptions
- document whether fees and turnover are included

Do not let the WHS logic hide a broken portfolio return series.

## 10. Practical safety checks

- monitor effective sample size
- detect unstable weight concentration
- document fallback rules for sparse or low-quality regime inputs
- ensure the portfolio return construction is mathematically consistent
- validate the model with proper risk backtests

## 11. Minimum validation pack

At minimum, validate:

- breach rate against the target confidence level
- unconditional coverage
- independence or breach clustering
- comparison against a simpler challenger such as equal-weight HS
- model behavior during recent stress windows

Use `RISK/RISK_MODEL_VALIDATION_MCP.md` for the broader governance layer.

## 12. Known limits

WHS can become unstable when:

- weights are too concentrated
- regime estimates are noisy
- history is too short
- return construction is inconsistent across assets

If the model becomes too unstable, a simpler historical or parametric fallback
may be better.

## 13. Relationship to universal risk validation

This file is a model-specific methodology note.

For broader release criteria, challenger comparisons, operational gates, and
model-governance thinking, pair it with `RISK/RISK_MODEL_VALIDATION_MCP.md`.
