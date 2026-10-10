# Phase 17: Research Evidence Database Integration

This uses the existing `Database_Agent` Railway service and its Postgres primary. It **does not** enable production `PUBLISH_TO_DATABASE`, does not call `/backtests/runs`, create any promotion, evaluate final holdout, or contact Alpaca.

Existing Pre-Holdout Research keeps `PUBLISH_TO_DATABASE=false` and rejects attempts to set it true. The *new, separate* opt-in variable defaults OFF:

```text
BACKTEST_RESEARCH_EVIDENCE_PUBLISH=false
DATABASE_AGENT_URL=https://databaseagent-production.up.railway.app
DATABASE_AGENT_API_KEY=<service key in GitHub Actions Secrets>
```

Only after the Database_Agent Phase 17 rollout, set `BACKTEST_RESEARCH_EVIDENCE_PUBLISH=true` on the existing research runner if publication is desired. Ensure the two `DATABASE_AGENT_*` secrets are present in the runner's environment. Never commit or log secret values.

Each successful per-symbol research result is reduced to bounded Phase13–16 diagnostics. The full per-symbol source artifact is hashed locally but not uploaded (to avoid exposing sealed artifacts or duplicating huge reports). The storage identity is SHA-256 of canonical diagnostic payload. HTTP `POST /research/evidence` is authenticated via `X-API-KEY`. The response is counted as stored only if the evidence ID, original artifact SHA and fail-closed research permissions match. Uncertain HTTP failures are **not** silently retried; the existing immutable endpoint makes a later identical replay safe.

Important limitations: storing a historical/provider evidence claim does not establish historical source authenticity, independent forward OOS, statistical significance, or an actual Alpaca order. Research reports remain `promotion_allowed=false`, `execution_allowed=false` and `sealed_holdout_opened=false` unconditionally. These records are **not** Strategy v8 eligibility evidence for manager approval.
