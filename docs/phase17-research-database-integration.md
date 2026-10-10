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

## Existing Strategy Research v7 manual Run (no new workflow)

The **existing** `.github/workflows/strategy-research-v7.yml` now exposes a `workflow_dispatch` checkbox, `publish_research_evidence` (default `false`). After Database_Agent Phase 17 has merged and deployed successfully, start the existing v7 workflow manually and select that checkbox. The step passes `DATABASE_AGENT_URL` and `DATABASE_AGENT_API_KEY` from GitHub Actions Secrets **only** for an explicitly opted-in manual run. Pull request runs never receive these database secrets, even if the code is changed in a PR.

The research-only report verifies `phase17_research_storage.stored_count` and individual `evidence_id` values. Independently GET an ID from `/research/evidence/{evidence_id}` with the existing API key and compare the immutable hash and `promotion_allowed=false`. No stored research record can bypass existing BUY, Risk, Backtest, exposure, emergency halt, duplication, or broker reconciliation checks.

Do **not** enable the checkbox while Database_Agent migration/deployment is pending. Never use `PUBLISH_TO_DATABASE=true` to force this workflow.

## Phase 18: Read-back integrity verification (existing research lane)

For each explicitly opted-in Phase 17 research evidence publication, the Backtest_Agent now performs an authenticated `GET /research/evidence/{evidence_id}` after the successful POST. A report counts as verified only when the stored immutable payload is byte-canonically equivalent to the original bounded research document, its SHA-256 identity matches, original symbol/profile/artifact hash agree, and both payload and response independently deny trading or promotion. HTTP failures, 404, malformed responses and mismatched payloads fail closed without an automatic POST retry.

The research report contains `phase17_research_storage.readback_verified_count` and per-record `readback_verified=true`. These are storage-integrity indicators only, **not** forward-OOS profitability or permission to execute. A manually dispatched, explicitly opted-in rerun of the existing v7 workflow can exercise immutable replay and authenticated read-back; never enable publication on PR runs or change `PUBLISH_TO_DATABASE=false`.
