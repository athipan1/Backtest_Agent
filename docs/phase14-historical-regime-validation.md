# Phase 14: Historical Regime Validation & Strategy Research v8 Readiness

This phase extends the existing research artifact, without new workflows or trading controls. It checks **consistency of supplied historical data**, not provider authenticity or profitability.

### Output
The existing `phase9_oos_fill_evidence` artifact now includes `phase14_historical_regime_validation`.

It checks, independently of the Phase 13 matching flag:

- A checksum-pinned historical dataset is present with stable source and observation identifiers.
- A single historical `symbol + asof` is not retrospectively assigned conflicting regime labels. Revised history is rejected rather than treated as originally known.
- Historical observation IDs, exact available-at timestamps, regime labels and fingerprints match the selected OOS trade.
- The selected observation is the latest available to the strategy **at the entry timestamp**. No later labels may be joined.
- Nested OOS fold intervals are chronological, non-overlapping and have unambiguous TRADE / NO_TRADE classifications.
- Every TRADE OOS fold contributes reconciled closed-position evidence. NO_TRADE folds are acknowledged, not counted as profitable trades.
- The reference-price gross P&L, modeled slippage/impact/spread/fees and simulated net P&L reconcile by trade and fold.
- Descriptive positive-versus-negative *net-P&L* fold fractions can be reported, but are not statistical significance or future net returns.

### Production-safe invariants
- A SHA-256 digest detects changed bytes, **not** genuine provider publication timing. Without an independently audited provider archive, historical truth remains unverified.
- All costs are from the execution **simulator**, not verified Alpaca broker fill data.
- The strict contract does not imply Strategy v8 has a profitable hypothesis or authorize another trial. Preregister research hypotheses and control multiplicity before any new out-of-sample evaluation.
- Never include the physically sealed final holdout in the archived source, fit the regime labeling algorithm with future samples, or change selection/risk/promotion thresholds.
- The new artifact is strictly descriptive, with `strategy_v8_validation_ready=false`, `promotion_allowed=false`, `execution_allowed=false`, and `sealed_holdout_opened=false`.

The optional historical feed is still configured with `BACKTEST_RESEARCH_HISTORICAL_REGIME_FILE` and `BACKTEST_RESEARCH_HISTORICAL_REGIME_SHA256` as documented in Phase 13. **It is not connected to a verified historical provider by default.**

### Phase 15 prerequisites

Independently attest a provider's versioned PIT archive (including original publication timestamps), cross-check historical revisions and exchange sessions, compare multiple untouched nested-OOS folds with preregistered hypotheses and a multiplicity budget, reconcile broker-quality execution cost evidence, and only then assess research readiness. None of these steps can be bypassed by a green CI run.
