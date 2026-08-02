# Nested Walk-Forward Multi-Strategy Validation

`POST /backtest/multi-strategy/walk-forward` performs chronological strategy selection without using future test data to choose a candidate.

The legacy `POST /backtest/multi-strategy` endpoint remains available as a full-period diagnostic. New orchestration should use the nested walk-forward endpoint for promotion decisions.

## Why this exists

A full-period Backtest can accidentally reward a strategy because it was ranked using the same future regimes later presented as validation evidence. A fixed-candidate rolling test is useful, but it still does not prove that the candidate would have been selected using information available at that historical moment.

Nested walk-forward answers the harder question:

1. Which strategy would the system select using only the training window?
2. How does that selected strategy perform in the untouched future test window?
3. Does this process remain stable across several independent chronological windows?

## Window algorithm

For every window:

```text
historical train slice
  -> rank all candidate strategies on train only
  -> select best eligible train candidate
  -> optional embargo gap
  -> run only the selected candidate on untouched future test bars
  -> store train selection evidence and test performance
```

The process then moves forward and repeats. No test metrics are used to select the candidate for that same window.

## Default window design

```text
train bars:                         126
out-of-sample test bars:            126
step bars:                          126
embargo bars:                         0
overlapping test windows:         false
minimum completed windows:            4
```

The default step equals the test length, so test windows are independent and non-overlapping. A caller may intentionally set `allow_overlapping_test_windows=true`, but overlap is visible in the response and is not the production default.

`embargo_bars` inserts an unused chronological gap between train and test slices. It can reduce leakage when features, labels, or market effects cross a split boundary.

## Default stability gates

```text
minimum completed windows                 4
minimum train-eligible window rate      50%
minimum trades per test window             1
profitable test-window rate             60%
median test Sharpe ratio                 0.70
median test profit factor                1.10
worst test maximum drawdown             -20%
maximum aggregate kill-switch events       0
```

Medians are used so one unusually strong test window cannot hide several weak windows.

## Promotion authority

Full-period metrics remain in the response for diagnostics and comparison, but they do not grant promotion.

A strategy can become `best_eligible` only when:

- the aggregate nested out-of-sample gates pass
- the latest training window selected that exact `strategy_id`
- the latest training selection was eligible under the configured train gates
- the selected candidate's fixed-candidate out-of-sample stability gates pass

When these conditions are not satisfied, `best_eligible` and `selected_result` are null.

## Response evidence

The response includes a top-level `nested_walk_forward` object containing:

- `selection_method = nested_train_select_test_evaluate`
- completed window count
- train-eligible window rate
- profitable test-window rate
- median test return, Sharpe, and profit factor
- worst test drawdown
- aggregate kill-switch events
- whether test windows overlap
- configured embargo bars
- selected strategy count by `strategy_id`
- latest selected strategy and eligibility
- per-window train selection and future test evidence

Each window includes:

- train and test date boundaries
- selected `strategy_id` and strategy name
- train eligibility and score
- train metrics
- future test metrics
- warnings

Each ranked candidate also retains fixed-candidate out-of-sample evidence as a diagnostic robustness view.

## Insufficient history

When fewer than the configured minimum windows can be constructed:

```text
nested_walk_forward.status = insufficient_history
nested_walk_forward.passed = false
selection_status = no_eligible_strategy
```

This is a safe no-trade result. The service does not fall back to full-period-only evidence.

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
    "step_bars": 126,
    "embargo_bars": 0,
    "allow_overlapping_test_windows": false,
    "min_windows": 4
  }
}
```

The empty bars array is abbreviated for documentation. Production requests must contain valid chronological OHLCV data.

## Expected orchestration

```text
Scanner candidate symbol
  -> exact-symbol nested walk-forward multi-strategy Backtest
  -> latest train-selected best_eligible strategy
  -> publish strategy_id plus nested OOS evidence
  -> Manager exact Database gate
  -> Risk
  -> Execution
```

Manager should require nested validation evidence rather than infer approval from a full-period record. Database publication should preserve the strategy ID, window criteria, train selection evidence, test metrics, gate results, stability score, and validation timestamp.
