from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def bars(count=80):
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    rows = []
    for index in range(count):
        close = 100 + (index % 15) + (index * 0.15)
        rows.append(
            {
                "timestamp": (start + timedelta(days=index)).isoformat(),
                "open": close - 0.25,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": 1_000_000,
            }
        )
    return rows


def test_multi_strategy_endpoint_uses_balanced_default_suite():
    response = client.post(
        "/backtest/multi-strategy",
        json={
            "symbols": ["AAPL"],
            "initial_equity": 100000,
            "bars": {"AAPL": bars()},
            "fee_bps": 0,
            "slippage_bps": 0,
            "force_close_at_end": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["data"]["symbol"] == "AAPL"
    assert payload["data"]["candidate_source"] == "balanced_v1"
    assert payload["data"]["evaluated_count"] == 4
    assert len(payload["data"]["ranked_results"]) == 4
    assert payload["data"]["best_overall"]["rank"] == 1
    assert payload["data"]["selection_status"] in {
        "eligible_strategy_found",
        "no_eligible_strategy",
    }


def test_multi_strategy_endpoint_rejects_multiple_symbols():
    response = client.post(
        "/backtest/multi-strategy",
        json={
            "symbols": ["AAPL", "MSFT"],
            "initial_equity": 100000,
            "bars": {"AAPL": bars(), "MSFT": bars()},
        },
    )

    assert response.status_code == 422


def test_ready_contract_advertises_multi_strategy_selection():
    response = client.get("/ready")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["multi_strategy_endpoint"] == "/backtest/multi-strategy"
    assert data["multi_strategy_profile"] == "balanced_v1"
    assert data["multi_strategy_selection"] == {
        "exact_symbol_only": True,
        "returns_best_eligible": True,
        "safety_gated": True,
    }
