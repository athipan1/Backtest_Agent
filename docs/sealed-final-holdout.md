# Sealed Final Holdout

`nested_walk_forward_v3` adds a final untouched historical holdout to the production Backtest promotion pipeline.

## Purpose

Nested walk-forward, statistical validation, and robustness testing reduce overfitting risk, but they still operate on the research sample. A final holdout provides one last test on bars that strategy selection, parameter choice, and validation thresholds never see.

The production order is:

```text
Full historical dataset
  -> physically split research bars + sealed tail
Research bars only
  -> Nested Walk-Forward
  -> Statistical Validation v2
  -> Robustness Stress
Only after every pre-holdout gate passes
  -> open sealed holdout once
  -> run the exact selected strategy and parameters
  -> Final Holdout gates
  -> Database publish
  -> Promotion Lifecycle, stopping at ROBUSTNESS_PASSED
```

The holdout is sliced before `WalkForwardMultiStrategyRequest` is created. Selection therefore cannot inspect holdout prices, timestamps, returns, metrics, or trade outcomes.

If no strategy is eligible, the result remains a successful `NO_TRADE` decision and the holdout is recorded as `sealed_not_opened`.

## Production configuration

```text
BACKTEST_FINAL_HOLDOUT_ENABLED=true
BACKTEST_FINAL_HOLDOUT_BARS=252
BACKTEST_FINAL_HOLDOUT_MIN_TRADES=10
BACKTEST_FINAL_HOLDOUT_MIN_RETURN=0.0
BACKTEST_FINAL_HOLDOUT_MIN_SHARPE=0.0
BACKTEST_FINAL_HOLDOUT_MAX_DRAWDOWN=-0.20
```

A positive `BACKTEST_FINAL_HOLDOUT_MAX_DRAWDOWN` value is normalized to its negative drawdown floor. For example, `0.15` becomes `-0.15`.

Production `nested_promotion` requires the final holdout to be enabled. Research runs that deliberately do not use a sealed holdout must use the explicit `legacy_fixed` research mode instead of weakening the production pipeline.

By default the provider must return at least 630 research bars plus 252 sealed bars, or 882 bars total.

## Evidence

Promotion metadata contains:

```text
sealed_holdout.enabled
sealed_holdout.start
sealed_holdout.end
sealed_holdout.bar_count
sealed_holdout.trade_count
sealed_holdout.return_pct
sealed_holdout.sharpe_ratio
sealed_holdout.profit_factor
sealed_holdout.max_drawdown
sealed_holdout.dataset_fingerprint
sealed_holdout.strategy_id
sealed_holdout.effective_parameters_sha256
sealed_holdout.passed
sealed_holdout.gates
sealed_holdout.criteria
```

The final gates check:

- exact holdout bar count
- minimum completed trades
- minimum holdout return
- minimum holdout Sharpe ratio
- maximum drawdown floor
- exact strategy identity

Any failed holdout gate blocks Database publishing and the promotion lifecycle. Backtest_Agent therefore cannot reach `ROBUSTNESS_PASSED` for that evidence.

## Leakage controls

The implementation enforces several invariants:

1. Research and holdout bars are sorted and physically separated before selection.
2. The final research timestamp must be earlier than the first holdout timestamp.
3. Nested selection sees only research bars.
4. Statistical and robustness validation run only on the research request.
5. Holdout execution is deferred until all pre-holdout gates pass.
6. The same selected candidate is reused for holdout execution. There is no second selection or parameter search after the holdout is opened.
7. The holdout bar count cannot change between sealing and evaluation.
8. Holdout evidence records a SHA-256 dataset fingerprint and canonical parameter hash.

The holdout result must never be used to tune parameters, thresholds, strategy rankings, or selection rules. A failed holdout is evidence that the candidate should not advance, not feedback for another search on the same sealed sample.

## Deterministic identity

The production run identity includes:

- full dataset fingerprint
- research dataset fingerprint
- exact effective parameters
- validation profile and evidence version
- walk-forward policy
- statistical schema and policy
- robustness policy
- final holdout policy
- final holdout dataset fingerprint

Changing the holdout length, gates, research dataset, sealed dataset, strategy, or parameters creates a different deterministic Backtest identity.

## Validation profile

Phase 4 uses:

```text
validation_profile = nested_walk_forward_v3
evidence_version = 3
```

The maximum state Backtest_Agent can own remains `ROBUSTNESS_PASSED`. It does not approve paper trading, observe paper performance, contact a broker, or invoke Execution_Agent.
