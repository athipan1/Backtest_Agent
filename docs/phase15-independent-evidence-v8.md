# Phase 15: Archived Point-in-Time Corroboration & Strategy v8 Hypothesis Preregistration

This change is **research-only**. It extends the existing Phase 9–14 research report at `phase9_oos_fill_evidence.phase15_independent_evidence`. It does not create a Strategy v8 candidate, run new strategy trials, select, promote, publish to Database, execute orders or open sealed holdout.

## Independent *documents* do not establish independent historical facts

Phase 13 accepts a separately checksum-pinned historical regime feed, but a checksum and a source-reported availability timestamp are not provider attestation. Phase 15 optionally reads two further **separately checksum-pinned JSON files**, each with independently configured SHA-256. All validation is fail-closed when either is absent.

- `BACKTEST_RESEARCH_V8_ARCHIVE_FILE` and `BACKTEST_RESEARCH_V8_ARCHIVE_SHA256`
- `BACKTEST_RESEARCH_V8_HYPOTHESES_FILE` and `BACKTEST_RESEARCH_V8_HYPOTHESES_SHA256`

The archive document uses `phase15-archived-provider-records.v1`:

```json
{
  "schema_version": "phase15-archived-provider-records.v1",
  "independent_archive_id": "archival-source-id-distinct-from-primary",
  "historical_feed_sha256": "the-actual-sha256-of-phase13-historical-feed",
  "source_dataset_fingerprint": "actual-immutable-provider-dataset",
  "records": [
    {
      "symbol": "AAPL",
      "source_observation_id": "real-provider-observation-id",
      "publisher_record_id": "archived-provider-record-id",
      "regime": "BULL",
      "regime_asof_timestamp": "2026-01-02T09:30:00Z",
      "regime_available_at_timestamp": "2026-01-02T09:40:00Z",
      "publisher_first_seen_at": "2026-01-02T09:41:00Z",
      "archive_first_seen_at": "2026-01-02T09:42:00Z",
      "source_dataset_fingerprint": "actual-immutable-provider-dataset"
    }
  ]
}
```

The hypothesis registry uses `phase15-preregistered-v8-hypotheses.v1`:

```json
{
  "schema_version": "phase15-preregistered-v8-hypotheses.v1",
  "registered_at": "2025-12-31T12:00:00Z",
  "maximum_hypotheses": 3,
  "familywise_alpha": 0.05,
  "hypotheses": [
    {
      "hypothesis_id": "bull-trend-cost-adjusted-edge",
      "strategy_id": "already-existing-preregistered-candidate",
      "regime": "BULL",
      "metric": "simulated_fold_net_pnl_after_costs",
      "expected_direction": "positive",
      "minimum_oos_folds": 3
    }
  ]
}
```

**All examples are fictional and are not real historical observations or a registered research trial.** Generate SHA-256 digests from an actual archival source or independent timestamp registry. The code compares source identities, publication evidence, earliest observed archive times, OOS dates and the immutable registry. It rejects labels only first observed after trade entry, mismatched fingerprints, duplicate source IDs, malformed records, invalid budgets, or a registry timestamp later than the first nested OOS window.

The `registered_at`, `publisher_first_seen_at` and `archive_first_seen_at` fields remain **self-reported** until independent timestamping, provider-signed provenance or independently obtainable historical snapshots substantiate them. A passing Phase 15 contract **never** sets provider-authenticity or externally timestamped preregistration flags to true.

## Scientific integrity and Strategy v8

Phase 15 only summarizes existing Phase 14 selected-candidate nested OOS fold P&L after modeled costs. Because nested OOS has already participated in selection, this **cannot** be treated as an independent confirmatory p-value or an out-of-sample proof of a new v8 hypothesis. A familywise alpha field and hypothesis-count budget are registered but **no new statistical test** is executed or promotion threshold changed.

A minimum of three distinct research OOS folds is required for this strictly descriptive report, and a larger preregistered minimum is honored. This diagnostic condition is **not** a production strategy eligibility threshold. No financial returns, risk-adjusted metrics, portfolio allocation or broker cost observations are invented.

## Remaining evidence before a real v8 validation

1. Establish an independently verifiable historical provider archive with verifiable original release timestamps and version history, not just a JSON snapshot.
2. Have an external trusted timestamp/commitment prove a v8 hypothesis registration **before** any confirmatory data could be seen.
3. Collect independent, untouched future OOS observations and apply a predeclared multiplicity correction; do not reuse selected nested OOS folds as confirmatory tests.
4. Independently reconcile trade fills and execution costs from real Alpaca Paper broker evidence before attributing actual execution slippage.
5. Maintain all existing BUY, Backtest, Risk, portfolio exposure, broker reconciliation, duplicate prevention and emergency-halt gates. Keep `ALLOW_LIVE_TRADING=false`.

Safety flags remain `strategy_v8_promotion_ready=false`, `promotion_allowed=false`, `execution_allowed=false`, `sealed_holdout_opened=false`, and `profitability_proven=false`, regardless of whether documents match.
