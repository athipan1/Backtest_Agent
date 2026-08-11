# Statistical Validation v2

`statistical-validation.v2` is the production statistical evidence contract used by Backtest_Agent before a strategy can advance through the promotion lifecycle.

## Why v2 exists

The v1 validator used IID assumptions for the mean-return significance test and bootstrap interval. Financial returns can be serially correlated, so treating every observation as independent can overstate confidence.

Version 2 keeps the existing Bonferroni correction, Probabilistic Sharpe Ratio (PSR), and Deflated Sharpe Ratio (DSR), but makes the production authority time-series-aware.

## Production authority

A new promotion must use `statistical-validation.v2` and must pass every configured gate:

- minimum finite equity-return observations
- minimum completed trades
- HAC/Newey-West adjusted one-sided p-value after multiple-testing correction
- minimum PSR
- minimum DSR probability
- positive lower annualized-return bound from a time-series bootstrap
- minimum HAC probability that mean period return is positive
- a time-series bootstrap method (`stationary` or `moving_block`)

`iid` remains supported only as a diagnostic method. Selecting `iid` makes `time_series_bootstrap_authority=false`, so the evidence cannot pass promotion authority.

## Bootstrap methods

`stationary` is the production default. It resamples runs of adjacent returns with a geometric restart probability whose expected block length is `bootstrap_block_size`.

`moving_block` resamples fixed-length contiguous blocks and concatenates them until the original sample length is restored.

Both methods require enough observations for at least two expected/full blocks. If this condition is not met, validation returns `status=insufficient_data` and fails closed. The IID interval is still emitted as diagnostic evidence when possible.

Configure production with:

```text
BACKTEST_BOOTSTRAP_METHOD=stationary
BACKTEST_BOOTSTRAP_BLOCK_SIZE=10
BACKTEST_BOOTSTRAP_SIMULATIONS=500
BACKTEST_BOOTSTRAP_CONFIDENCE=0.95
BACKTEST_STATISTICAL_MIN_HAC_CONFIDENCE=0.95
```

For backward configuration compatibility, `BACKTEST_STATISTICAL_BOOTSTRAP_SIMULATIONS` and `BACKTEST_STATISTICAL_BOOTSTRAP_CONFIDENCE` remain fallbacks when the new shorter environment variables are absent.

## HAC / Newey-West evidence

The validator estimates the long-run variance of the sample mean with a Bartlett-kernel Newey-West estimator. The HAC lag count is derived deterministically from the configured bootstrap block size and available observations.

Evidence includes:

- `autocorrelation_lag1`
- `hac_standard_error`
- `hac_lag_count`
- `effective_sample_size`
- `hac_mean_positive_probability`
- `sharpe_standard_error`

The one-sided mean-return p-value uses the HAC standard error. PSR and DSR use a Sharpe standard error based on the effective information in the serially dependent sample rather than blindly assuming every return is independent.

## Bootstrap evidence

Evidence records:

- `bootstrap_method`
- `bootstrap_block_size`
- `bootstrap_confidence`
- `bootstrap_annualized_return_lower`
- `bootstrap_annualized_return_upper`
- `block_bootstrap_annualized_return_lower`
- `block_bootstrap_annualized_return_upper`
- `iid_bootstrap_annualized_return_lower`
- `iid_bootstrap_annualized_return_upper`

The generic `bootstrap_annualized_return_*` fields describe the configured method for compatibility. Production gates use the block/stationary interval, never the IID diagnostic interval.

## Determinism and identity

Bootstrap simulation uses a local seeded random generator. Same code + same dataset + same strategy + same statistical policy + same seed produces the same statistical evidence.

The hourly run identity includes the statistical schema version and complete statistical criteria. Changing bootstrap method, block size, confidence, simulation count, HAC confidence threshold, or other statistical policy therefore changes the deterministic Backtest identity.

## Compatibility

Historical v1 evidence remains parseable through `parse_statistical_validation_evidence`. Missing historical schema tags are interpreted as `statistical-validation.v1` for read compatibility.

That compatibility is read-only for promotion authority. New production promotion explicitly rejects v1 statistical evidence.
