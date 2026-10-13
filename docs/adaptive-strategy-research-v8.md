# Adaptive Strategy Research v8: preregistered, non-executable

This phase makes the **existing** Backtest research process more flexible.
It does **not** lower BUY, Backtest, nested-OOS, statistical, risk, cost,
exposure, idempotency or broker safety thresholds.

## Delivered

1. **Eight fixed v8 candidates**: four unchanged balanced-v1 controls and
   four preregistered hypotheses spanning trend, SMA, breakout and
   mean reversion. New hypothesis configurations are capped at 4% single
   position size. These are research configurations, NOT live allocations.
2. **22 cumulative statistical trials** since v5. New v8 profile trials do
   not reset earlier multiple-testing accounting.
3. **Nested v4 train-only selection** and post-hoc per-fold research
   recommendations. Exact OOS results cannot choose their own candidates.
4. **Optional PIT regime research observations**: for each nested fold,
   consider only archived observations where
   `regime_available_at_timestamp <= train_end < test_start` and no older
   than seven calendar days. Unknown, late, ambiguous or unverified
   observations lead to no regime hypothesis. BEAR/HIGH_RISK/NO_TRADE
   produce research CASH_ABSTENTION instead of a BUY.
5. **Already-existing real cost simulation**: the research runner evaluates
   actual modeled fees, slippage and impact at 1x, 1.5x and 2x once a
   candidate clears the previous nested/statistical gates. It also runs
   the existing CSCV/PBO overfit control for v8. This planner itself
   does not re-run costs or invent fill evidence.

## Execution and leakage isolation

The v8 plan is generated **after** nested selection and is never fed into
`run_walk_forward_multi_strategy_backtest_v4`, Risk, Execution, or
strategy promotion. v8 experiments therefore cannot claim to have
already demonstrated adaptive-regime performance. The plan explicitly
reports `regime_driven_strategy_selection_enabled=false`.

An archived SHA-256 feed confirms only immutable **bytes**, not whether
the provider's past publication time was genuine. The existing Phase 13
historical input adapter must verify its checksum and structure, but
currently reports
`historical_source_independently_audited=false`. No retrospective
regime labeling is granted independent authenticity by this change.
Even an independently attested provider archive would require a
**separate preregistered causal nested-regime evaluation** before
any strategy can be promoted.

No new repository or GitHub workflow is created.

## Run using the existing workflow

GitHub Actions > **Strategy Research v7/v8 (sealed pre-holdout)**
(existing `.github/workflows/strategy-research-v7.yml`) >
**Run workflow** > `research_profile=strategy_research_v8`.

The workflow retains the original Scanner cohort, the same history
minimum and reserved sealed holdout, PBO checks, transaction-cost stress,
nested v4 validation and explicit prohibition on production/database
publication. Keep `publish_research_evidence=false` for initial
exploration. With no externally archived historical PIT feed, the
per-fold regime plan correctly contains no verified regime hypotheses.

Direct CLI execution in the existing checkout:

```bash
BACKTEST_RESEARCH_PROFILE=strategy_research_v8 \
BACKTEST_FINAL_HOLDOUT_ENABLED=true \
PUBLISH_TO_DATABASE=false \
python scripts/run_research_candidate_profile.py
```

The normal provider/data-API credentials and history configuration are
still needed; this snippet does not bypass market data contracts.

## Interpretation

- v8 `pre_holdout_candidate` is **not** permission to open the sealed
  holdout, publish production approval or place any Alpaca Paper order.
- Manager's independent advisory watchlist may display QTTB/JFIN-style
  near misses, but it cannot bypass its existing safety-constrained
  Shadow candidate filter.
- Any altered parameter/hypothesis evaluated on OOS must be counted
  cumulatively as another trial. Do not change v8 choices using the
  sealed holdout or repeatedly cherry-pick favorable OOS results.
- Success means richer research evidence, **not proven profit**.
