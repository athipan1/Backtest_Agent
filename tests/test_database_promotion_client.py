from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.database_client as database_client_module
from app.database_client import DatabaseAgentClient


class FakeResponse:
    def __init__(self, payload, *, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise database_client_module.httpx.HTTPStatusError(
                "request failed",
                request=SimpleNamespace(),
                response=SimpleNamespace(status_code=self.status_code),
            )

    def json(self):
        return self.payload


def test_create_and_transition_use_exact_paths_and_correlation(monkeypatch):
    calls = []

    def fake_post(url, *, json, headers, timeout):
        calls.append(
            {
                "url": url,
                "json": json,
                "headers": headers,
                "timeout": timeout,
            }
        )
        return FakeResponse(
            {
                "status": "success",
                "data": {
                    "promotion_id": "promotion-1",
                    "run_id": "run-1",
                    "state": "GENERATED",
                    "version": 1,
                },
            }
        )

    monkeypatch.setattr(database_client_module.httpx, "post", fake_post)
    client = DatabaseAgentClient(
        base_url="https://database.example/",
        api_key="database-key",
        timeout_seconds=3.5,
    )

    client.create_backtest_promotion(
        {"run_id": "run-1"},
        correlation_id="corr-1",
    )
    client.transition_backtest_promotion(
        "promotion-1",
        {"next_state": "VALIDATED"},
        correlation_id="corr-1",
    )

    assert calls[0]["url"] == "https://database.example/backtests/promotions"
    assert calls[1]["url"] == (
        "https://database.example/backtests/promotions/promotion-1/transition"
    )
    assert calls[0]["headers"] == {
        "Content-Type": "application/json",
        "X-API-KEY": "database-key",
        "X-Correlation-ID": "corr-1",
    }
    assert "X-PROMOTION-APPROVAL-KEY" not in calls[0]["headers"]
    assert "X-PROMOTION-APPROVAL-KEY" not in calls[1]["headers"]
    assert calls[0]["timeout"] == 3.5


def test_promotion_operations_require_database_url():
    client = DatabaseAgentClient(base_url="", api_key="key")
    with pytest.raises(RuntimeError, match="DATABASE_AGENT_URL"):
        client.create_backtest_promotion({"run_id": "run-1"})


def test_error_and_malformed_envelopes_fail_closed(monkeypatch):
    client = DatabaseAgentClient(base_url="https://database.example", api_key="key")

    monkeypatch.setattr(
        database_client_module.httpx,
        "post",
        lambda *args, **kwargs: FakeResponse(
            {"status": "error", "error": {"code": "stale_version"}}
        ),
    )
    with pytest.raises(RuntimeError, match="stale_version"):
        client.create_backtest_promotion({"run_id": "run-1"})

    monkeypatch.setattr(
        database_client_module.httpx,
        "post",
        lambda *args, **kwargs: FakeResponse(["not", "an", "object"]),
    )
    with pytest.raises(RuntimeError, match="malformed"):
        client.create_backtest_promotion({"run_id": "run-1"})

    monkeypatch.setattr(
        database_client_module.httpx,
        "post",
        lambda *args, **kwargs: FakeResponse({"status": "success", "data": None}),
    )
    with pytest.raises(RuntimeError, match="missing promotion data"):
        client.create_backtest_promotion({"run_id": "run-1"})


def test_http_failure_is_not_converted_to_success(monkeypatch):
    monkeypatch.setattr(
        database_client_module.httpx,
        "post",
        lambda *args, **kwargs: FakeResponse({}, status_code=503),
    )
    client = DatabaseAgentClient(base_url="https://database.example", api_key="key")
    with pytest.raises(database_client_module.httpx.HTTPStatusError):
        client.transition_backtest_promotion(
            "promotion-1",
            {"next_state": "VALIDATED"},
        )
