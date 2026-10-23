# NFLX nested OOS stability diagnostics (research only)

This change adds a read-only diagnostic for a list of out-of-sample windows. It does not change strategy selection, trading eligibility, risk thresholds, sealed holdout handling, or order submission.

## Usage

```bash
python scripts/diagnose_nested_oos_stability.py windows.json
python -m pytest tests/test_nested_oos_stability_diagnostics.py
```

Input example: `{"windows":[{"strategy":"mean_reversion","net_return":-0.02},{"strategy":"sma","net_return":0.03}]}`.

Use **net** return per independent window, including trading costs. Do not feed in-sample optimization results or use these diagnostics to tune on sealed holdout. Zero-return cash windows count as non-positive, matching a strict positive-window diagnostic. The diagnostic 60% minimum is not a substitute for the authoritative Backtest gate; passing it alone never grants trading eligibility.

Previously observed NFLX research cohort had 3 positive windows out of 6, requiring 4. Exact window-level returns should be supplied from the original evidence rather than invented here. Investigate regime, transaction costs and mean-reversion failure periods using separate research/training data; confirm hypotheses on untouched evaluation data.
