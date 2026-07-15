# Multi-Strategy Backtest Selection

`POST /backtest/multi-strategy` evaluates multiple strategy configurations for one exact symbol, ranks them with an explainable risk-adjusted score, and selects a strategy only when every safety gate passes.

The endpoint does not submit broker orders and does not bypass Manager, Risk, or Execution controls.

## Why exact-symbol only

A strategy that works for one symbol must not become evidence for another symbol. The request therefore accepts exactly one symbol. Portfolio callers should invoke the endpoint independently for each Scanner-selected symbol.

## Default balanced-v1 suite

When `candidates` is omitted, the endpoint evaluates:

| Strategy ID | Strategy | Windows |
|---|---|---|
| `sma-crossover-balanced-v1` | SMA crossover | 10 / 30 |
| `trend-following-balanced-v1` | Trend following | 20 / 50 |
| `mean-reversion-balanced-v1` | Mean reversion | 5 / 20 |
| `breakout-balanced-v1` | Breakout | 5 / 20 |

Callers may supply custom candidates. Each candidate receives an exact `strategy_id`. Duplicate identities are rejected because downstream Database, Manager, Risk, and Execution gates need unambiguous evidence.

## Default selection gates

A candidate is eligible only when all gates pass:

- at least 10 completed trades
- annualized return at least 5%
- Sharpe ratio at least 0.80
- profit factor at least 1.20
- maximum drawdown no worse than -20%
- excess return versus equal-weight buy-and-hold at least 0%
- zero kill-switch events

The thresholds can be overridden through `selection_criteria`, but lowering them does not authorize paper or live execution. Manager and Risk remain responsible for promotion decisions.

## Ranking

The score combines:

- total and annualized return
- Sharpe and Sortino ratios
- profit factor
- maximum drawdown
- excess return versus the benchmark
- trade activity
- risk-rejection and kill-switch penalties

Eligible strategies always rank ahead of ineligible strategies. The response returns both `best_overall` and `best_eligible`. When no strategy passes all gates, `selection_status` is `no_eligible_strategy`, `best_eligible` is null, and `selected_result` is null.

## Example request

```json
{
  "symbols": ["AAPL"],
  "initial_equity": 100000,
  "bars": {
    "AAPL": []
  },
  "fee_bps": 10,
  "slippage_bps": 5,
  "force_close_at_end": true
}
```

The `bars` array must contain valid historical OHLCV rows. Empty bars are shown only to keep the example compact.

## Expected orchestration

```text
Scanner candidate
  -> exact-symbol multi-strategy Backtest
  -> best_eligible strategy
  -> exact strategy_id Backtest publication
  -> Manager gate
  -> Risk gate
  -> Execution gate
```

A later Manager integration should use `best_eligible.strategy_id` and the exact effective parameters. It must not substitute another strategy or reuse evidence from another symbol.
