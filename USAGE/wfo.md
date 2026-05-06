# WFO Optimization

This page is a current-state guide, not the finished operator runbook.

The repository already supports walk-forward and portfolio-weight-study
orchestration through typed application and CLI adapter surfaces. What is still
missing is one stable operator-facing runbook with finalized commands and
examples for each optimization workflow.

## Current Public Surface

- walk-forward orchestration through
  `application.optimization.run_walk_forward`
- walk-forward batch orchestration through
  `application.optimization.run_walk_forward_batch`
- portfolio-weight study orchestration through
  `application.optimization.portfolio_weight_study`
- delivery-facing adapters under `backtest_engine.interfaces.cli`
- persisted study, champion, confirmed-fold, and recommendation artifacts under
  `results/`

## Strategy WFO

Current truth:

- canonical walk-forward behavior is owned by
  `application.optimization.run_walk_forward`
- the delivery-facing adapter is
  `interfaces.cli.run_walk_forward.run_walk_forward_cli`
- batch WFO orchestration is also available through the matching batch adapter
- no finished operator runbook is published yet

TODO:

- add a stable operator command surface
- add one single-strategy WFO example
- document fold inputs, optimization metric selection, and expected outputs

## Portfolio WFO And Weight Studies

Current truth:

- portfolio-weight studies are owned by
  `application.optimization.portfolio_weight_study`
- the delivery-facing adapter is
  `interfaces.cli.run_portfolio_weight_study.run_portfolio_weight_study_cli`
- read adapters already exist for study summaries, champions, confirmed folds,
  and recommendations
- no finished operator runbook is published yet

TODO:

- add one portfolio optimization example
- document study artifact outputs and recommendation publication flow
- document how portfolio-focused optimization differs from strategy-focused WFO

## Related Guides

- [Install and Terminal Preparation](install.md)
- [Historical Market Data](market-data.md)
- [Backtesting](backtesting.md)
