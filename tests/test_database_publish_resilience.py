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


def test_invalid_environment_values_fall_back_and_extremes_are_bounded(monkeypatch):
    monkeypatch.setenv("DATABASE_AGENT_TIMEOUT_SECONDS", "not-a-number")
    monkeypatch.setenv("DATABASE_AGENT_RECONCILIATION_ATTEMPTS", "invalid")
    monkeypatch.setenv("DATABASE_AGENT_RECONCILIATION_BACKOFF_SECONDS", "invalid")
    fallback = DatabaseAgentClient(base_url="https://database.example")
    assert fallback.timeout_seconds == 45.0
    assert fallback.reconciliation_attempts == 3
    assert fallback.reconciliation_backoff_seconds == 1.0

    monkeypatch.setenv("DATABASE_AGENT_TIMEOUT_SECONDS", "999")
    monkeypatch.setenv("DATABASE_AGENT_RECONCILIATION_ATTEMPTS", "99")
    monkeypatch.setenv("DATABASE_AGENT_RECONCILIATION_BACKOFF_SECONDS", "-5")
    bounded = DatabaseAgentClient(base_url="https://database.example")
    assert bounded.timeout_seconds == 120.0
    assert bounded.reconciliation_attempts == 6
    assert bounded.reconciliation_backoff_seconds == 0.0


def test_exact_run_matcher_rejects_each_incompatible_shape():
    payload = _payload()
    exact = _existing_document()
    assert DatabaseAgentClient._existing_run_matches_payload(exact, payload)
    assert not DatabaseAgentClient._existing_run_matches_payload({}, payload)
    assert not DatabaseAgentClient._existing_run_matches_payload(
        {"data": {}},
        payload,
    )

    incompatible = _existing_document()
    incompatible["data"]["run"]["account_id"] = "other"
    assert not DatabaseAgentClient._existing_run_matches_payload(
        incompatible,
        payload,
    )

    for field in ("parameters", "metrics"):
        incompatible = _existing_document()
        incompatible["data"]["run"][field] = {"changed": True}
        assert not DatabaseAgentClient._existing_run_matches_payload(
            incompatible,
            payload,
        )

    incompatible = _existing_document()
    incompatible["data"]["run"]["metadata"] = None
    assert not DatabaseAgentClient._existing_run_matches_payload(
        incompatible,
        payload,
    )

    incompatible = _existing_document()
    incompatible["data"]["run"]["metadata"]["dataset_fingerprint"] = "other"
    assert not DatabaseAgentClient._existing_run_matches_payload(
        incompatible,
        payload,
    )

    for field in ("trades", "equity_curve"):
        incompatible = _existing_document()
        incompatible["data"][field] = None
        assert not DatabaseAgentClient._existing_run_matches_payload(
            incompatible,
            payload,
        )


def test_reconciliation_handles_transient_get_failures_and_backoff(monkeypatch):
    calls = []
    sleeps = []

    def fake_get(url, *, headers, timeout):
        calls.append(url)
        if len(calls) == 1:
            return _response("GET", url, 500, {"detail": "temporarily unavailable"})
        if len(calls) == 2:
            raise httpx.ConnectError(
                "connection reset",
                request=httpx.Request("GET", url),
            )
        return _response("GET", url, 200, _existing_document())

    monkeypatch.setattr(database_client_module.httpx, "get", fake_get)
    monkeypatch.setattr(database_client_module.time, "sleep", sleeps.append)
    client = DatabaseAgentClient(
        base_url="https://database.example",
        reconciliation_attempts=3,
        reconciliation_backoff_seconds=0.25,
    )

    document = client._reconcile_backtest_publish(
        _payload(),
        correlation_id="corr-1",
    )

    assert document is not None
    assert len(calls) == 3
    assert sleeps == [0.25, 0.5, 0.75]
    assert client._reconcile_backtest_publish({}, correlation_id=None) is None


def test_reconciliation_rejects_non_transient_http_error(monkeypatch):
    def fake_get(url, *, headers, timeout):
        return _response("GET", url, 400, {"detail": "bad request"})

    monkeypatch.setattr(database_client_module.httpx, "get", fake_get)
    client = DatabaseAgentClient(
        base_url="https://database.example",
        reconciliation_backoff_seconds=0,
    )

    with pytest.raises(RuntimeError, match="HTTP 400"):
        client._reconcile_backtest_publish(_payload(), correlation_id=None)


def test_publish_disabled_and_transport_paths_remain_fail_closed(monkeypatch):
    disabled = DatabaseAgentClient(base_url="")
    assert disabled.publish_backtest_run(_payload())["status"] == "skipped"

    def fake_post(url, *, json, headers, timeout):
        raise httpx.ConnectError(
            "connection reset",
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(database_client_module.httpx, "post", fake_post)
    monkeypatch.setattr(
        database_client_module.httpx,
        "get",
        lambda url, **kwargs: _response("GET", url, 200, _existing_document()),
    )
    recovered = DatabaseAgentClient(
        base_url="https://database.example",
        reconciliation_backoff_seconds=0,
    )
    assert recovered.publish_backtest_run(_payload())["status"] == "success"

    monkeypatch.setattr(
        database_client_module.httpx,
        "get",
        lambda url, **kwargs: _response("GET", url, 404, {"detail": "missing"}),
    )
    unresolved = DatabaseAgentClient(
        base_url="https://database.example",
        reconciliation_attempts=1,
        reconciliation_backoff_seconds=0,
    )
    with pytest.raises(RuntimeError, match="transport failed"):
        unresolved.publish_backtest_run(_payload())
