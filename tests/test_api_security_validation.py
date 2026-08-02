from __future__ import annotations

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api_contracts import StrictBacktestRunRequest
from app.main import app


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


def _payload():
    return {
        "symbols": ["AAPL"],
        "initial_equity": 100000,
        "fast_window": 2,
        "slow_window": 3,
        "fee_bps": 0,
        "slippage_bps": 0,
        "bars": {"AAPL": _bars()},
    }


def test_health_remains_open_when_production_key_is_missing(monkeypatch):
    monkeypatch.setenv("BACKTEST_ENV", "production")
    monkeypatch.delenv("BACKTEST_API_KEY", raising=False)

    response = client.get("/health")

    assert response.status_code == 200


def test_production_compute_endpoint_fails_closed_without_configured_key(
    monkeypatch,
):
    monkeypatch.setenv("BACKTEST_ENV", "production")
    monkeypatch.delenv("BACKTEST_API_KEY", raising=False)

    response = client.post("/backtest/run", json=_payload())

    assert response.status_code == 503
    assert "must be configured" in response.json()["detail"]


def test_configured_api_key_is_required_and_compared(monkeypatch):
    monkeypatch.setenv("BACKTEST_ENV", "development")
    monkeypatch.setenv("BACKTEST_API_KEY", "secret-key")

    missing = client.post("/backtest/run", json=_payload())
    wrong = client.post(
        "/backtest/run",
        json=_payload(),
        headers={"X-API-KEY": "wrong-key"},
    )
    valid = client.post(
        "/backtest/run",
        json=_payload(),
        headers={"X-API-KEY": "secret-key"},
    )

    assert missing.status_code == 401
    assert wrong.status_code == 403
    assert valid.status_code == 200


def test_unknown_top_level_field_is_rejected():
    payload = _payload()
    payload["debug_mode"] = True

    response = client.post("/backtest/run", json=payload)

    assert response.status_code == 422
    assert any(
        error["type"] == "extra_forbidden"
        for error in response.json()["detail"]
    )


def test_unknown_price_bar_field_is_rejected():
    payload = _payload()
    payload["bars"]["AAPL"][0]["adjusted_close"] = 10

    response = client.post("/backtest/run", json=payload)

    assert response.status_code == 422
    assert any(
        error["type"] == "extra_forbidden"
        for error in response.json()["detail"]
    )


def test_duplicate_symbol_after_normalization_is_rejected():
    payload = _payload()
    payload["symbols"] = ["aapl", " AAPL "]

    response = client.post("/backtest/run", json=payload)

    assert response.status_code == 422
    assert "duplicate symbol" in str(response.json()["detail"])


def test_duplicate_timestamp_is_rejected():
    payload = _payload()
    payload["bars"]["AAPL"][1]["timestamp"] = payload["bars"]["AAPL"][0]["timestamp"]

    response = client.post("/backtest/run", json=payload)

    assert response.status_code == 422
    assert "duplicate timestamp" in str(response.json()["detail"])


def test_naive_timestamp_is_rejected():
    payload = _payload()
    payload["bars"]["AAPL"][0]["timestamp"] = "2026-01-01T00:00:00"

    response = client.post("/backtest/run", json=payload)

    assert response.status_code == 422
    assert "explicit timezone" in str(response.json()["detail"])


def test_non_finite_numbers_are_rejected_by_contract():
    payload = _payload()
    payload["initial_equity"] = float("inf")

    with pytest.raises(ValidationError):
        StrictBacktestRunRequest.model_validate(payload)


def test_configured_total_bar_limit_is_enforced(monkeypatch):
    monkeypatch.setenv("BACKTEST_MAX_TOTAL_BARS", "5")

    response = client.post("/backtest/run", json=_payload())

    assert response.status_code == 422
    assert "total bar count" in str(response.json()["detail"])


def test_request_content_length_limit_returns_413(monkeypatch):
    monkeypatch.setenv("BACKTEST_MAX_REQUEST_BYTES", "1024")
    payload = deepcopy(_payload())
    payload["padding"] = "x" * 5000

    response = client.post("/backtest/run", json=payload)

    assert response.status_code == 413
    assert response.json()["status"] == "error"
