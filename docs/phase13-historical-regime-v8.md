# Phase 13: historical regime integration (research only)

This change integrates an **optional, externally supplied historical regime feed** into the existing sealed pre-holdout Strategy Research v7 report. It does **not** derive historical regimes from the current Manager regime context, train on the sealed final holdout, select new strategies, promote models, or place orders.

## Input contract

Set both variables in the existing research job (not the trading workflow):

- BACKTEST_RESEARCH_HISTORICAL_REGIME_FILE: existing local JSON file of historical regime observations.
- BACKTEST_RESEARCH_HISTORICAL_REGIME_SHA256: exact 64-character SHA-256 of the file bytes. Pin the digest independently from your historical source.

Example schema **only** (illustrative dates and labels, not market evidence):

{
  "schema_version": "phase13-historical-regime-feed.v1",
  "source_id": "immutable-provider-archive-identifier",
  "dataset_fingerprint": "provider-specific-immutable-dataset-id",
  "observations": [{
    "symbol": "AAPL",
    "regime": "BULL",
    "source_observation_id": "archived-record-id",
    "regime_asof_timestamp": "2026-01-02T09:30:00Z",
    "regime_available_at_timestamp": "2026-01-02T09:40:00Z",
    "source": "historical_point_in_time_observation",
    "dataset_fingerprint": "provider-specific-immutable-dataset-id"
  }]
}

Never interpret a bar start timestamp as its publication time. Record **when the provider made the regime observation available**, not when the price window began. Preserve provider archive identifiers and raw timestamp provenance.

The adapter reads the file **after** the research/holdout split. It rejects unverifiable digests, malformed and repeated observation IDs, naive timestamps, available-before-as-of data, any observation available after the research end (which might leak the holdout), and oversized files. Its 7-calendar-day age cap is a **fixed diagnostic-only freshness rule**, not a strategy gate.

For each reconciled OOS closed trade, the adapter chooses only the latest unambiguously available observation for that symbol at or before the entry timestamp. If any trade cannot be matched, the whole joined snapshot set is suppressed, with explicit error reasons. An as-of match **does not** establish independent historical source authenticity or causal regime attribution.

## Research outputs

Inside the existing per-symbol report:

- phase9_oos_fill_evidence.phase13_historical_regime_evidence: source read status, checksum, matching coverage, missing reasons and safety flags.
- phase9_oos_fill_evidence.phase12_execution_cost_regime_evidence: the existing simulated reference-price cost breakdown, optionally decorated with matched historical labels. These are modeled costs, not broker fills.
- phase9_oos_fill_evidence.phase13_strategy_research_v8_preparation: descriptive net P&L and costs by nested OOS fold, strategy and matched regime, only when upstream integrity and joins pass. Includes pre-registered research questions and readiness blockers. No automatic parameter tuning, hypothesis tests, candidate promotion or new v8 strategy run.

## Remaining blockers

- Obtain and independently audit an immutable historical PIT archive, including provider availability timestamps and dataset provenance.
- Independently reconcile simulated closeouts and estimate execution costs against broker-quality fills. Simulation/model costs are not broker-measured.
- Pre-register any new v8 hypotheses and multiple-testing budgets **before** another trial; use untouched nested OOS folds. Do not unseal the final holdout to decide new parameters.
- Keep BUY_VERDICT_REQUIRED, Backtest, Risk, exposure, duplicate-order, broker reconciliation and emergency halt gates unchanged.

All diagnostics remain non-authoritative: promotion_allowed=false, execution_allowed=false, sealed_holdout_opened=false and strategy_v8_ready_for_promotion=false.
