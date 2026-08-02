# Execution Realism Policy v0.7

Backtest fills use an explicit execution policy so pricing and quantity assumptions are reproducible and stored with every published run.

## Policy fields

```json
{
  "execution_policy": {
    "bid_ask_spread_bps": 2.0,
    "quantity_increment": 1,
    "signal_execution_delay_bars": 1
  }
}
```

### `bid_ask_spread_bps`

The full quoted spread in basis points. A buy crosses half of the spread above the reference price, while a sell crosses half below it.

For a 10 bps spread at a reference price of 100:

```text
buy reference  = 100.05
sell reference =  99.95
```

Slippage and volume-dependent market impact are added outside the spread. The final simulated price is therefore:

```text
buy  = reference * (1 + (slippage + impact + half spread) / 10000)
sell = reference * (1 - (slippage + impact + half spread) / 10000)
```

### `quantity_increment`

The minimum integer quantity step. Liquidity capacity, portfolio allocation, and locally approved quantities are rounded down to this increment.

Examples:

```text
requested 97, increment 10 -> maximum 90
volume capacity 105, increment 10 -> usable 100
```

Rounding down is fail-safe. The engine never rounds an order up beyond cash, exposure, liquidity, or risk limits.

Fractional-share increments are not included in v0.7. Decimal quantity support requires a separate accounting migration so cash, fees, positions, database serialization, and reconciliation use one exact precision policy.

### `signal_execution_delay_bars`

The current engine supports exactly one bar of signal delay:

```text
signal generated at bar close
  -> order evaluated at the next available bar open
```

Values other than `1` are rejected rather than silently ignored. A configurable multi-bar queue can be added later with explicit stale-order and missing-bar behavior.

## Policy precedence

1. An explicit request `execution_policy` is used when the endpoint supports it.
2. Otherwise runtime defaults are read from:

```bash
BACKTEST_DEFAULT_BID_ASK_SPREAD_BPS
BACKTEST_DEFAULT_QUANTITY_INCREMENT
```

3. Without request or environment overrides, compatibility defaults are 0 bps spread and one-share increments.

The Hourly Backtest workflow applies a 2 bps spread and one-share increment only to the execution step. Its preceding test step remains isolated from production simulation defaults.

## Isolation

The resolved policy is stored in a Python `ContextVar` for the duration of one Backtest request. Concurrent simulations therefore cannot leak spread or quantity settings into each other.

## Run identity and storage

The resolved policy participates in the exact-symbol deterministic run ID. Changing spread or quantity increment creates a different run identity even when bars and strategy parameters are unchanged.

Database_Agent payloads include the policy in both:

```text
parameters.execution_policy
metadata.execution_policy
```

Published engine version:

```text
backtest-agent-0.7.0
```

## Scope

Execution v0.7 combines:

- next-bar open signal execution
- bid-ask spread
- fixed slippage
- volume participation limit
- linear market impact
- transaction fees
- integer quantity increments
- cash, exposure, position, and risk limits

It still does not model exchange calendars, halts, order-book depth, nonlinear market impact, borrow costs, dividends, splits, or fractional-share precision. Those remain future realism layers.
