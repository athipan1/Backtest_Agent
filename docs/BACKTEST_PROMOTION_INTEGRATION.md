# Backtest_Agent Promotion Lifecycle Integration

## Authority boundary

Backtest_Agent owns evidence generation and may attest only these transitions:

1. `GENERATED -> VALIDATED`
2. `VALIDATED -> OOS_PASSED`
3. `OOS_PASSED -> ROBUSTNESS_PASSED`

Backtest_Agent has no API method, approval credential, broker key, or code path for `APPROVED_FOR_PAPER` or `PAPER_OBSERVING`. Database_Agent remains the lifecycle source of truth. Manager_Agent owns approval policy. Risk_Agent must approve before Execution_Agent, and only Execution_Agent may contact a trading broker.

## Immutable evidence flow

The hourly workflow performs the following sequence for each symbol:

1. Fetch and canonicalize historical bars.
2. Compute the dataset fingerprint.
3. Run nested train-selection and evaluate only on future test windows.
4. Re-run the selected strategy on the complete immutable dataset for diagnostic storage metrics.
5. Compute numeric statistical evidence:
   - Bonferroni-adjusted p-value
   - Probabilistic Sharpe Ratio
   - Deflated Sharpe probability
   - bootstrap annualized-return confidence interval
6. Compute deterministic robustness evidence:
   - parameter perturbation
   - fee stress
   - bid-ask spread stress
   - slippage stress
   - liquidity stress
   - Monte Carlo drawdown stress
   - catastrophic-loss and finite-metric checks
7. Create a deterministic run ID that includes the evidence policy version.
8. Publish the complete immutable Backtest record to Database_Agent.
9. Create or replay the `GENERATED` promotion.
10. Attest each Backtest-owned state in order with expected state and expected version.

The workflow fails if evidence publishing or any required transition fails. A stored Backtest record remains auditable, but the workflow never reports a false green promotion.

## Retry model

Database_Agent creates deterministic transition IDs. Backtest_Agent reads the returned state and version and resumes only from an allowed Backtest-owned state. Replaying an identical request does not create another version or transition-history row. A terminal state, malformed response, changed promotion identity, changed run identity, or unauthorized state fails closed.

## Robustness policy

Production defaults are configurable through environment variables:

```text
BACKTEST_PROMOTION_MIN_PARAMETER_SCENARIOS=4
BACKTEST_PROMOTION_MIN_PARAMETER_PROFITABLE_RATE=0.50
BACKTEST_PROMOTION_MIN_ROBUSTNESS_PASS_RATE=0.80
BACKTEST_PROMOTION_MIN_STRESS_RETURN_PCT=-0.10
BACKTEST_PROMOTION_MAX_STRESS_DRAWDOWN_FLOOR=-0.30
BACKTEST_PROMOTION_CATASTROPHIC_LOSS_FLOOR=-0.50
BACKTEST_PROMOTION_MAX_MONTE_CARLO_LOSS_PROBABILITY=0.50
BACKTEST_PROMOTION_MIN_MONTE_CARLO_P05_EQUITY_RATIO=0.80
BACKTEST_PROMOTION_MAX_MONTE_CARLO_P05_DRAWDOWN_FLOOR=-0.35
BACKTEST_PROMOTION_MONTE_CARLO_SIMULATIONS=500
BACKTEST_PROMOTION_MONTE_CARLO_SEED=42
```

Any missing, insufficient, non-finite, or failed robustness evidence blocks promotion.

## Required runtime configuration

```text
DATABASE_AGENT_URL=<Database_Agent base URL>
DATABASE_AGENT_API_KEY=<Backtest-to-Database service key>
PUBLISH_TO_DATABASE=true
```

Do not configure `BACKTEST_PROMOTION_APPROVAL_TOKEN` in Backtest_Agent. Do not configure an Alpaca trading key in Backtest_Agent. The hourly data provider may use market-data credentials, but the repository has no order-submission client.

## Incident recovery

- Database timeout: fail the symbol and retry the workflow with the same deterministic run ID.
- Transition timeout: retry the same transition payload; Database_Agent returns the original result snapshot.
- Stale version: stop and inspect Database_Agent history. Do not guess the current state.
- Evidence mismatch: stop, compare account/run/strategy/symbol/timeframe/dataset/engine identity, and create no replacement promotion.
- Robustness failure: preserve the Backtest report as a rejected candidate. Do not weaken policy during the same run.
- Promotion already approved or observing: return the downstream state without mutating it.
- Terminal state: fail closed and require a new evidence run under policy.

## Rollout checklist

- All Backtest tests and branch coverage at or above 90 percent
- Ruff and MyPy pass for promotion modules
- Bandit and pip-audit pass
- CycloneDX SBOM generated
- Trivy filesystem and image scans pass
- Container runs non-root and becomes healthy
- Database publish failure produces a failed workflow
- Promotion transition failure produces a failed workflow
- No eligible strategy remains a successful no-trade outcome
- Backtest_Agent never emits `APPROVED_FOR_PAPER` or `PAPER_OBSERVING`
