# Phase 16: Prospective OOS Evidence & Strategy v8 Research Readiness

This is an **offline, research-only documentary validation**, not a new strategy backtest, trade-execution system or promotion rule. Existing Phase 13–15 nested OOS samples were exposed during candidate selection and must **never** be treated as an untouched independent confirmation.

## Contract

The optional prospective-forward document must be a separately versioned immutable JSON file with the exact schema `phase16-prospective-oos-evidence.v1`. Supply it only to the existing research workflow by setting:

- `BACKTEST_RESEARCH_V8_FORWARD_OOS_FILE`
- `BACKTEST_RESEARCH_V8_FORWARD_OOS_SHA256`

Phase 16 reads the existing Phase 15 pinned hypothesis registry and its SHA-256, plus the actual research/holdout split *boundary timestamps* from the current pre-holdout evaluator. It does **not** access holdout bar content or evaluate sealed-holdout returns. Every prospective fold must start strictly **after the last reserved sealed-holdout timestamp**. A newly collected dataset may be supplied independently, but is **not downloaded or synthesized** by this implementation.

Example of a **fictional schema outline** (no real trade data):

```json
{
  "schema_version": "phase16-prospective-oos-evidence.v1",
  "hypothesis_registry_sha256": "<64-character Phase 15 registry SHA>",
  "source_research_dataset_fingerprint": "<frozen earlier selection dataset>",
  "source_reserved_holdout_id": "<externally recorded reserved holdout identifier>",
  "dataset_identity": {
    "source_id": "new-forward-provider-source",
    "dataset_sha256": "<64-character external prospective dataset hash>",
    "data_feed": "research-paper-feed",
    "sampling_frequency": "1d",
    "first_collected_at": "2027-01-01T09:00:00Z"
  },
  "folds": [
    {"fold_id": "forward-1", "start": "2027-01-02T09:30:00Z",
     "end": "2027-01-02T16:00:00Z"}
  ],
  "evaluations": [
    {
      "fold_id": "forward-1",
      "hypothesis_id": "<registered hypothesis ID>",
      "strategy_id": "<locked strategy ID>",
      "regime": "BULL",
      "strategy_definition_sha256": "<registered locked strategy SHA>",
      "decision": "NO_TRADE",
      "reference_price_gross_pnl": 0,
      "modeled_slippage_cost": 0,
      "modeled_impact_cost": 0,
      "modeled_half_spread_cost": 0,
      "recorded_fees": 0,
      "simulated_net_pnl": 0
    }
  ]
}
```

**The outline is intentionally incomplete:** a real packet must include every preregistered hypothesis **for every forward OOS fold**, and at least three distinct folds per registered hypothesis. TRADE rows additionally require `trade_ledger_fingerprint` and the complete gross/reference and simulated-cost breakdown. A matching fingerprint is a claimed identity, **not an independent ledger reconciliation**.

The *existing* Phase 15 `phase15-preregistered-v8-hypotheses.v1` registry must contain the additional immutable `strategy_definition_sha256` for each hypothesis. Older registries without this key are explicitly rejected for Phase 16. This does not alter the Phase 15 contract or change any candidate, threshold or production decision.

## Fail-closed checks

- Exact SHA-256 of the source packet, registry hash linkage and immutable strategy definition hashes; missing or malformed files are rejected.
- Research-slice end, sealed-holdout end and forward sample interval must be timezone-aware and non-overlapping. No prospective row is evaluated within either existing set.
- Registry `registered_at` must precede every prospective fold start. These times are **self-reported** until externally attested.
- Every `hypothesis_id × fold_id` pair must occur once and only once: no hidden losing folds or silent cash abstentions.
- Cost and P&L arithmetic is rechecked; `NO_TRADE` must have all zero costs and P&L. `TRADE` rows must carry a ledger fingerprint and locked strategy identity.
- No change to preexisting sealed validation, regime selection, Backtest, Risk, Exposure, BUY verdict, Emergency Halt, broker reconciliation, or duplicate-order prevention.
- Any defect suppresses the descriptive hypothesis-fold diagnostics.

## What Phase 16 does **not** prove

An SHA-pinned forward packet is still a **claim supplied by an external file**, not independently verified forward-market or broker evidence. The code does not verify provider timestamps, collect future fills, re-run frozen strategy code, compare held-out broker transactions, calculate inference p-values, or attest timestamps. It therefore never sets external prospective-data independence, confirmatory significance, profitability or Strategy v8 eligibility to true, even if the packet reports positive returns.

The report path is `phase9_oos_fill_evidence.phase16_prospective_oos_evidence`. Its flags are permanently `diagnostic_only=true`, `used_for_selection=false`, `promotion_allowed=false`, `execution_allowed=false`, `sealed_holdout_opened=false` and `net_profitability_proven=false`.

## Next prerequisite

Collect **genuine prospective post-holdout observations**, freeze and independently timestamp both the strategy artifact and preregistration before those observations accrue, then perform independent fill/ledger verification and formally preregistered multiple-testing analysis without unsealing the existing final holdout. No evidence means no v8 approval.
