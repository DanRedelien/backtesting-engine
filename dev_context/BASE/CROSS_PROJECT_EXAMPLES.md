# Cross-Project Examples

Purpose: show contrasting implementation shapes so LLMs do not mistake one
repository layout for a universal quant standard.

## 1. Small research script

Typical use case:

- one researcher
- one model family
- local experiments

Possible shape:

```text
project/
|-- research/
|   |-- load_prices.py
|   |-- build_features.py
|   |-- fit_hmm.py
|   `-- evaluate_var.py
|-- config.py
`-- outputs/
```

Good for:

- exploratory HMM or regime work
- quick factor research
- one-off stress studies

## 2. Event-driven backtester

Typical use case:

- rule-based or semi-systematic trading strategy research
- explicit order semantics
- post-run artifact review

Possible shape:

```text
src/
|-- data/
|-- strategies/
|-- execution/
|-- backtester/
|-- optimization/
`-- analytics/
```

Good for:

- futures or crypto strategy research
- order-type testing
- walk-forward optimization

## 3. HMM-driven risk engine

Typical use case:

- regime detection
- VaR / ES forecasting
- challenger-model validation

Possible shape:

```text
src/
|-- market_data/
|-- features/
|-- regime_models/
|-- risk_models/
|-- validation/
`-- reporting/
```

Good for:

- adaptive VaR / ES
- volatility-regime classification
- stress-state monitoring

## 4. Live trading or execution service

Typical use case:

- broker connectivity
- runtime safety
- operational monitoring

Possible shape:

```text
src/
|-- adapters/
|-- strategies/
|-- risk_controls/
|-- order_router/
|-- monitoring/
`-- runtime/
```

Good for:

- broker-connected bots
- execution automation
- alerting and circuit breakers

## 5. Portfolio or risk dashboard platform

Typical use case:

- many analytics consumers
- reproducible artifacts
- API and UI delivery

Possible shape:

```text
src/
|-- data/
|-- analytics/
|-- artifact_store/
|-- services/
`-- api_or_ui/
```

Good for:

- prop-desk dashboards
- portfolio exposure monitoring
- scenario and stress-review tooling

## 6. Rule of use

When reading the MCP documents:

- choose the example closest to the current task
- keep the principles
- do not copy folder names mechanically
- verify against the actual repository you are working in
