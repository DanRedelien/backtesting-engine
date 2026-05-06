# Optimization And Walk-Forward MCP

Use this document for parameter search, model selection, and time-series
validation workflows.

## 1. Optimization is a research tool, not proof of edge

A good optimizer finds promising regions of the parameter space. It does not
prove that a strategy generalizes.

The job of validation is to challenge the result.

## 2. Minimum separation discipline

Do not use one dataset for everything.

At minimum, separate:

- optimization or training data
- validation data
- final unseen evaluation data

For time-series systems, use time-respecting splits.

## 3. Valid validation patterns

Choose the method that matches the project:

- simple holdout
  Good for fast sanity checks.
- rolling walk-forward
  Good for adaptive strategies and repeated re-optimization studies.
- anchored walk-forward
  Good when an expanding history is realistic.
- purged and embargoed splits
  Good when label leakage or serial dependence is a serious concern.

No one pattern is mandatory for every project. The point is leakage control and
truthful out-of-sample evaluation.

## 4. Search-space design

Good search spaces are:

- small enough to explore meaningfully
- wide enough to test the thesis
- based on business logic, not random parameter mining

Red flags:

- too many tunable parameters
- extremely fine increments
- duplicated parameters that encode the same idea
- optimizing money-management knobs before proving alpha logic

## 5. Objective design

Optimize for what the strategy is supposed to achieve.

Common objective ingredients:

- Sharpe or Sortino
- drawdown penalties
- trade-count penalties
- turnover penalties
- stability penalties
- tail-risk penalties

The objective should match the use case. A high-turnover stat-arb strategy and a
slow trend strategy should not automatically share the same objective.

## 6. Robustness checks

A good validation process usually includes some of:

- in-sample vs out-of-sample degradation
- parameter stability across folds
- trade-count sufficiency
- regime sensitivity
- consistency across symbols or periods
- comparison against baselines or naive strategies
- leakage-resistant feature engineering for ML pipelines

## 7. ML-aware validation note

For ML or HMM-driven strategies:

- fit scalers, encoders, regime models, and feature transforms on training data
  only
- apply purging or embargo when labels or holding periods overlap across folds
- separate hyperparameter tuning from final model evaluation
- persist enough metadata to know which feature schema and model artifact
  produced each signal

## 8. Cross-project examples

Backtester example:

- optimizer evaluates strategies using the same event-driven engine used by
  normal runs

Risk-model example:

- regime-model hyperparameters are tuned on training windows and validated on
  future returns without leakage

Research example:

- a notebook or script can still use rolling or purged validation instead of a
  single global fit
