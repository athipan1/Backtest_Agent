# Rolling Walk-Forward Multi-Strategy Validation

`POST /backtest/multi-strategy/walk-forward` validates each exact strategy configuration across multiple rolling out-of-sample windows before it can become `best_eligible`.

The existing `POST /backtest/multi-strategy` endpoint remains unchanged for backward compatibility. New orchestration should migrate to the walk-forward endpoint after validating its report contract.

## Why this exists

A full-period Backtest can look strong because one market regime dominates the sample. Rolling validation asks a harder question: does the same fixed strategy continue to work in several later, unseen periods?

The endpoint requires both:

1. every full-period selection gate to pass
2. every rolling walk-forward stability gate to pass

A strategy that passes only one layer is not eligible for promotion to Manager, Risk, or Execution.

## Default window design

```text
train bars: 126
out-of-sample test bars: 126
step bars: 63
minimum completed windows: 4
```

The training segment establishes the chronological split. The fixed candidate is then simulated only on the following test segment. Test windows may overlap because the step is shorter than the test length, but no future bars are moved into an earlier test window.

For roughly two years of daily bars, the defaults normally produce four rolling test windows.

## Default stability gates

```text
minimum completed windows        4
minimum trades per window        1
profitable-window rate          60%
median Sharpe ratio             0.70
median profit factor            1.10
worst maximum drawdown          -20%
maximum kill-switch events       0
```

Medians are used instead of averages so one unusually strong window cannot hide several weak windows.

## Response additions

Each ranked strategy contains:

- `full_period_eligible`
- final `eligible`
- `walk_forward.status`
- `walk_forward.stability_score`
- `walk_forward.evaluated_windows`
- `walk_forward.profitable_window_rate`
- `walk_forward.median_annualized_return`
- `walk_forward.median_sharpe_ratio`
- `walk_forward.median_profit_factor`
- `walk_forward.worst_max_drawdown`
- per-window metrics and date boundaries
- prefixed full-period and walk-forward gate results

`best_eligible` is null unless both validation layers pass. `selected_result` is also null when no strategy qualifies.

## Insufficient history

When fewer than the configured minimum windows can be constructed:

```text
walk_forward.status = insufficient_history
walk_forward.passed = false
selection_status = no_eligible_strategy
```

This is a safe no-trade result, not permission to fall back to a full-period-only strategy.

## Example request

```json
{
  "symbols": ["AAPL"],
  "initial_equity": 100000,
  "bars": {
    "AAPL": []
  },
  "walk_forward_criteria": {
    "train_bars": 126,
    "test_bars": 126,
    "step_bars": 63,
    "min_windows": 4
  }
}
```

The empty bars array is abbreviated for documentation. Production requests must contain valid chronological OHLCV data.

## Expected orchestration

```text
Scanner candidate
  -> exact-symbol walk-forward multi-strategy Backtest
  -> best_eligible strategy
  -> publish exact strategy_id and stability evidence
  -> Manager exact Database gate
  -> Risk
  -> Execution
```

Manager should not infer walk-forward approval from a legacy full-period record. The Database publication contract should preserve the selected strategy ID, window criteria, gate results, stability score, and validation timestamp.
