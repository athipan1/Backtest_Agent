# Observability and Readiness

## Correlation IDs

Every HTTP request accepts an optional header:

```http
X-Correlation-ID: corr-example-123
```

Accepted IDs are 1 to 128 characters and use letters, digits, `.`, `_`, `:`, or `-`. Missing or invalid values are replaced with a generated UUID.

The resolved ID is:

- returned in the `X-Correlation-ID` response header
- included in operational contract response bodies
- attached to structured request logs
- forwarded to Database_Agent when publishing Backtest evidence

Payload content, API keys, market bars, and account values are not written to request logs.

## Structured request logs

The logger name is:

```text
backtest_agent.request
```

Each completed request emits one compact JSON object:

```json
{
  "event": "http_request_completed",
  "correlation_id": "corr-example-123",
  "method": "POST",
  "path": "/backtest/run",
  "status_code": 200,
  "duration_ms": 14.527
}
```

Unhandled exceptions add only `error_type`. Stack traces remain controlled by the application server configuration.

Route templates are used as metric and log paths. Unknown dynamic paths are collapsed to bounded labels such as `/backtest/__unknown__` to avoid unbounded metric cardinality.

## Metrics

Prometheus-compatible text is available at:

```http
GET /metrics
```

Current metrics:

```text
backtest_process_start_time_seconds
backtest_http_requests_total
backtest_http_request_duration_seconds_count
backtest_http_request_duration_seconds_sum
backtest_validation_failures_total
backtest_authentication_failures_total
backtest_unhandled_errors_total
```

Request labels contain only method, bounded route template, and status code. Symbol, strategy, account, run ID, and correlation ID are deliberately excluded from labels.

The registry is process-local. A multi-worker deployment should scrape each worker separately or adopt a shared Prometheus multiprocess configuration in a later runtime change.

## Health and readiness

`GET /health` reports that the process and HTTP application are alive.

`GET /ready` reports whether critical runtime configuration is safe for traffic. It returns HTTP 503 when a critical check fails.

Readiness checks:

- production requires `BACKTEST_API_KEY`
- when `PUBLISH_TO_DATABASE=true`, `DATABASE_AGENT_URL` is required
- production publishing also requires `DATABASE_AGENT_API_KEY`

Development remains ready without secrets when publishing is disabled. Readiness does not make a network call to Database_Agent, so a dependency outage is detected by publish failures and fail-closed workflow status rather than by potentially expensive readiness traffic.

Example failed readiness response:

```json
{
  "status": "error",
  "correlation_id": "generated-or-provided-id",
  "data": {
    "ready": false,
    "environment": "production",
    "publishing_required": true
  },
  "metadata": {
    "readiness_checks": {}
  },
  "error": {
    "code": "service_not_ready",
    "message": "One or more critical runtime checks failed."
  }
}
```

## Alerting suggestions

Useful initial alerts:

- readiness remains 0 or `/ready` returns 503 for more than five minutes
- `backtest_unhandled_errors_total` increases
- authentication failures increase unexpectedly
- validation failures spike after a deployment
- request duration sum/count indicates sustained latency growth
- scheduled workflow reports a required Database publish failure
