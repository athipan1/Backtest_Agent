# Statistical Strategy Validation

Multi-strategy selection includes statistical evidence so a strategy is not promoted merely because it has a positive headline return.

## Why this exists

Backtesting many candidates creates selection bias. Even when every strategy has no real edge, one candidate can look strong by chance. Small samples, few trades, and unstable equity paths amplify that risk.

`Backtest_Agent` therefore evaluates each candidate using its chronological equity returns and the total number of candidates tested.

## Default gates

```text
minimum finite equity-return observations       30
minimum closed trades                           10
maximum Bonferroni-adjusted one-sided p-value  0.05
minimum Probabilistic Sharpe Ratio              0.95
minimum Deflated Sharpe probability             0.90
minimum 95% bootstrap annualized-return lower    0.00
bootstrap simulations                            500
```

A candidate must pass both the existing performance/risk gates and every enabled statistical gate before it can become `best_eligible`.

## Evidence methods

### One-sided mean test

The service tests whether the average period return is greater than zero using a normal approximation based on the observed standard error.

### Multiple-testing adjustment

The raw one-sided p-value is multiplied by the number of candidates evaluated, capped at 1.0. This is a Bonferroni family-wise error correction.

Trying more strategies therefore makes the significance gate harder, not easier.

### Probabilistic Sharpe Ratio

Probabilistic Sharpe estimates the probability that the observed periodic Sharpe ratio is greater than zero while accounting for sample size, skewness, and kurtosis.

### Deflated Sharpe probability

Deflated Sharpe compares the observed Sharpe ratio with the expected maximum Sharpe that could arise from testing several candidates. It reduces confidence when many alternatives were searched.

### Bootstrap confidence interval

The service performs a deterministic IID bootstrap of equity returns using a configurable seed. The lower confidence bound of annualized mean return must exceed the configured minimum.

The method is intentionally labeled in every result. It is a conservative screening layer, not proof that future performance is guaranteed.

## Response fields

Every ranked multi-strategy result contains `statistical_evidence` with:

- status and pass/fail result
- observation and trade counts
- candidate count
- mean and annualized mean return
- period volatility and periodic Sharpe
- skewness and kurtosis
- raw and adjusted p-values
- Probabilistic Sharpe Ratio
- expected maximum Sharpe
- Deflated Sharpe probability
- bootstrap confidence level and return bounds
- individual gates and failure reasons
- method identifier

The ranking score also contains `statistical_confidence`, but eligibility is determined by explicit gates rather than score alone.

## Configuration

Requests may override `statistical_criteria`:

```json
{
  "statistical_criteria": {
    "enabled": true,
    "min_observations": 30,
    "min_trades": 10,
    "max_adjusted_p_value": 0.05,
    "min_probabilistic_sharpe_ratio": 0.95,
    "min_deflated_sharpe_probability": 0.90,
    "min_bootstrap_annualized_return": 0.0,
    "bootstrap_confidence": 0.95,
    "bootstrap_simulations": 500,
    "bootstrap_seed": 42
  }
}
```

Disabling the statistical layer requires an explicit `enabled=false`. Production orchestration should keep it enabled and record the override in audit metadata when policy permits an exception.

## Limitations

The bootstrap currently resamples individual period returns and assumes observations are exchangeable. Future hardening can add block bootstrap, White's Reality Check, or Hansen's SPA for serially dependent strategies. Nested walk-forward evidence remains required for chronological validation.
