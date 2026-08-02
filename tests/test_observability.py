from __future__ import annotations

import json
import logging
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app import main as app_main
from app.main import app
from app.observability import METRICS


client = TestClient(app)


def _bars():
    closes = [10, 11, 12, 13, 12, 11]
    return [
        {
            "timestamp": f"2026-01-{index:02d}T00:00:00Z",
            "open": close,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": 1000,
        }
        for index, close in enumerate(closes, start=1)
    ]


def _publish_payload():
    return {
        "account_id": "1",
        "run_id": "observable-run-1",
        "skill_id": "skill-1",
        "strategy_id": "strategy-1",
        "timeframe": "1d",
        "publish_to_database": True,
        "symbols": ["AAPL"],
        "initial_equity": 100000,
        "fast_window": 2,
        "slow_window": 3,
        "fee_bps": 0,
        "slippage_bps": 0,
        "bars": {"AAPL": _bars()},
    }


@pytest.fixture(autouse=True)
def reset_metrics(monkeypatch):
    METRICS.reset()
    for name in [
        "BACKTEST_ENV",
        "ENVIRONMENT",
        "BACKTEST_API_KEY",
        "PUBLISH_TO_DATABASE",
        "DATABASE_AGENT_URL",
        "DATABASE_AGENT_API_KEY",
    ]:
        monkeypatch.delenv(name, raising=False)
    yield
    METRICS.reset()


def test_correlation_id_is_echoed_in_header_and_contract_body():
    response = client.get(
        "/version",
        headers={"X-Correlation-ID": "corr-observe-123"},
    )

    assert response.status_code == 200
    assert response.headers["X-Correlation-ID"] == "corr-observe-123"
    assert response.json()["correlation_id"] == "corr-observe-123"


def test_invalid_correlation_id_is_replaced_with_uuid():
    response = client.get(
        "/version",
        headers={"X-Correlation-ID": "invalid correlation with spaces"},
    )

    generated = response.headers["X-Correlation-ID"]
    UUID(generated)
    assert response.json()["correlation_id"] == generated


def test_metrics_expose_route_counts_duration_and_validation_failures():
    client.get("/health")
    client.post(
        "/backtest/run",
        json={"symbols": ["AAPL"], "initial_equity": 100000, "bars": {}},
    )

    response = client.get("/metrics")
    text = response.text

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert (
        'backtest_http_requests_total{method="GET",path="/health",status="200"} 1'
        in text
    )
    assert (
        'backtest_http_requests_total{method="POST",path="/backtest/run",status="422"} 1'
        in text
    )
    assert "backtest_http_request_duration_seconds_count" in text
    assert "backtest_validation_failures_total 1" in text
    assert "backtest_authentication_failures_total 0" in text


def test_authentication_failure_metric_is_incremented(monkeypatch):
    monkeypatch.setenv("BACKTEST_API_KEY", "secret")

    response = client.post("/backtest/run", json=_publish_payload())
    metrics = client.get("/metrics").text

    assert response.status_code == 401
    assert "backtest_authentication_failures_total 1" in metrics


def test_structured_request_log_contains_only_operational_fields(caplog):
    caplog.set_level(logging.INFO, logger="backtest_agent.request")

    client.get(
        "/health",
        headers={"X-Correlation-ID": "corr-log-1"},
    )

    record = next(
        item
        for item in caplog.records
        if item.name == "backtest_agent.request"
    )
    event = json.loads(record.getMessage())
    assert event == {
        "correlation_id": "corr-log-1",
        "duration_ms": event["duration_ms"],
        "event": "http_request_completed",
        "method": "GET",
        "path": "/health",
        "status_code": 200,
    }
    assert isinstance(event["duration_ms"], float)


def test_database_publish_receives_request_correlation_id(monkeypatch):
    observed = {}

    def fake_publish_backtest_result(**kwargs):
        observed["correlation_id"] = kwargs["correlation_id"]
        return {
            "status": "success",
            "database_response": {"status": "success"},
            "payload": {"run_id": kwargs["run_id"]},
        }

    monkeypatch.setattr(
        app_main,
        "publish_backtest_result",
        fake_publish_backtest_result,
    )

    response = client.post(
        "/backtest/run-and-publish",
        json=_publish_payload(),
        headers={"X-Correlation-ID": "corr-database-1"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert observed["correlation_id"] == "corr-database-1"
    assert response.headers["X-Correlation-ID"] == "corr-database-1"


def test_development_readiness_is_available_without_secrets():
    response = client.get("/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["data"]["ready"] is True
    assert body["data"]["metrics_endpoint"] == "/metrics"


def test_production_readiness_fails_closed_without_api_key(monkeypatch):
    monkeypatch.setenv("BACKTEST_ENV", "production")

    response = client.get("/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "error"
    assert body["data"]["ready"] is False
    assert body["metadata"]["readiness_checks"]["api_key_policy"]["ok"] is False
    assert body["error"]["code"] == "service_not_ready"


def test_required_database_publish_is_part_of_readiness(monkeypatch):
    monkeypatch.setenv("BACKTEST_ENV", "production")
    monkeypatch.setenv("BACKTEST_API_KEY", "api-secret")
    monkeypatch.setenv("PUBLISH_TO_DATABASE", "true")

    missing = client.get("/ready")
    assert missing.status_code == 503
    assert (
        missing.json()["metadata"]["readiness_checks"]["database_url"]["ok"]
        is False
    )

    monkeypatch.setenv("DATABASE_AGENT_URL", "http://database-agent:8004")
    monkeypatch.setenv("DATABASE_AGENT_API_KEY", "database-secret")
    ready = client.get("/ready")

    assert ready.status_code == 200
    assert ready.json()["data"]["ready"] is True


def test_oversized_request_rejection_still_has_correlation_header(monkeypatch):
    monkeypatch.setenv("BACKTEST_MAX_REQUEST_BYTES", "1024")

    response = client.post(
        "/backtest/run",
        json={"padding": "x" * 5000},
        headers={"X-Correlation-ID": "corr-large-1"},
    )

    assert response.status_code == 413
    assert response.headers["X-Correlation-ID"] == "corr-large-1"
