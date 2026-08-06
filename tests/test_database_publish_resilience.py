from __future__ import annotations

import httpx
import pytest

import app.database_client as database_client_module
from app.database_client import DatabaseAgentClient


def _payload(*, symbol: str = "MSFT") -> dict:
    return {
        "run_id": "run-1",
        "account_id": "1",
        "skill_id": "hourly-sma-crossover",
        "strategy_id": "hourly-sma-crossover",
        "symbol": symbol,
        "timeframe": "1d",
        "engine_version": "backtest-agent-0.7.0",
        "parameters": {"fast_window": 2, "slow_window": 3},
        "metrics": {"return_pct": 0.05},
        "metadata": {"dataset_fingerprint": "fingerprint-1"},
        "trades": [],
        "equity_curve": [
            {"timestamp": "2026-08-01T00:00:00Z", "equity": 100000}
        ],
    }


def _existing_document(*, symbol: str = "MSFT") -> dict:
    payload = _payload(symbol=symbol)
    return {
        "status": "success",
        "data": {
            "run": {
                key: payload[key]
                for key in (
                    "run_id",
                    "account_id",
                    "skill_id",
                    "strategy_id",
                    "symbol",
                    "timeframe",
                    "engine_version",
                    "parameters",
                    "metrics",
                    "metadata",
                )
            },
            "trades": [],
            "equity_curve": [payload["equity_curve"][0]],
            "skill_result": None,
        },
    }


def _response(
    method: str,
    url: str,
    status_code: int,
    payload: dict,
) -> httpx.Response:
    request = httpx.Request(method, url)
    return httpx.Response(status_code, request=request, json=payload)


def test_default_timeout_is_configurable_and_bounded(monkeypatch):
    monkeypatch.setenv("DATABASE_AGENT_TIMEOUT_SECONDS", "75")
    calls = []

    def fake_post(url, *, json, headers, timeout):
        calls.append(timeout)
        return _response("POST", url, 200, {"status": "success", "data": {}})

    monkeypatch.setattr(database_client_module.httpx, "post", fake_post)
    client = DatabaseAgentClient(
        base_url="https://database.example",
        api_key="key",
        reconciliation_backoff_seconds=0,
    )

    client.publish_backtest_run(_payload())

    assert calls == [75.0]


def test_timeout_recovers_only_from_exact_persisted_run(monkeypatch):
    post_calls = []
    get_calls = []

    def fake_post(url, *, json, headers, timeout):
        post_calls.append(url)
        raise httpx.ReadTimeout(
            "read timed out",
            request=httpx.Request("POST", url),
        )

    def fake_get(url, *, headers, timeout):
        get_calls.append(url)
        return _response("GET", url, 200, _existing_document())

    monkeypatch.setattr(database_client_module.httpx, "post", fake_post)
    monkeypatch.setattr(database_client_module.httpx, "get", fake_get)
    client = DatabaseAgentClient(
        base_url="https://database.example",
        api_key="super-secret",
        timeout_seconds=5,
        reconciliation_attempts=2,
        reconciliation_backoff_seconds=0,
    )

    result = client.publish_backtest_run(_payload(), correlation_id="corr-1")

    assert result["status"] == "success"
    assert len(post_calls) == 1
    assert get_calls == ["https://database.example/backtests/runs/run-1"]


def test_duplicate_server_error_recovers_from_exact_run(monkeypatch):
    def fake_post(url, *, json, headers, timeout):
        return _response("POST", url, 500, {"detail": "duplicate key"})

    def fake_get(url, *, headers, timeout):
        return _response("GET", url, 200, _existing_document())

    monkeypatch.setattr(database_client_module.httpx, "post", fake_post)
    monkeypatch.setattr(database_client_module.httpx, "get", fake_get)
    client = DatabaseAgentClient(
        base_url="https://database.example",
        timeout_seconds=5,
        reconciliation_backoff_seconds=0,
    )

    result = client.publish_backtest_run(_payload())

    assert result["status"] == "success"


def test_timeout_without_persisted_run_fails_closed_with_context(monkeypatch):
    def fake_post(url, *, json, headers, timeout):
        raise httpx.ReadTimeout(
            "read timed out",
            request=httpx.Request("POST", url),
        )

    def fake_get(url, *, headers, timeout):
        return _response("GET", url, 404, {"detail": "not found"})

    monkeypatch.setattr(database_client_module.httpx, "post", fake_post)
    monkeypatch.setattr(database_client_module.httpx, "get", fake_get)
    client = DatabaseAgentClient(
        base_url="https://database.example",
        api_key="super-secret",
        timeout_seconds=5,
        reconciliation_attempts=2,
        reconciliation_backoff_seconds=0,
    )

    with pytest.raises(RuntimeError) as exc_info:
        client.publish_backtest_run(_payload())

    message = str(exc_info.value)
    assert "timed out" in message
    assert "run_id=run-1" in message
    assert "super-secret" not in message
    assert "https://database.example" not in message


def test_existing_run_with_different_identity_is_rejected(monkeypatch):
    def fake_post(url, *, json, headers, timeout):
        return _response("POST", url, 500, {"detail": "duplicate key"})

    def fake_get(url, *, headers, timeout):
        return _response("GET", url, 200, _existing_document(symbol="AAPL"))

    monkeypatch.setattr(database_client_module.httpx, "post", fake_post)
    monkeypatch.setattr(database_client_module.httpx, "get", fake_get)
    client = DatabaseAgentClient(
        base_url="https://database.example",
        timeout_seconds=5,
        reconciliation_backoff_seconds=0,
    )

    with pytest.raises(RuntimeError, match="immutable identity"):
        client.publish_backtest_run(_payload(symbol="MSFT"))
