from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["data"]["status"] == "healthy"


def test_backtest_run_endpoint():
    response = client.post(
        "/backtest/run",
        json={
            "symbols": ["AAPL"],
            "initial_equity": 100000,
            "fast_window": 2,
            "slow_window": 3,
            "fee_bps": 0,
            "slippage_bps": 0,
            "bars": {
                "AAPL": [
                    {"timestamp": "2026-01-01T00:00:00Z", "open": 10, "high": 11, "low": 9, "close": 10, "volume": 1000},
                    {"timestamp": "2026-01-02T00:00:00Z", "open": 11, "high": 12, "low": 10, "close": 11, "volume": 1000},
                    {"timestamp": "2026-01-03T00:00:00Z", "open": 12, "high": 13, "low": 11, "close": 12, "volume": 1000},
                    {"timestamp": "2026-01-04T00:00:00Z", "open": 13, "high": 14, "low": 12, "close": 13, "volume": 1000},
                    {"timestamp": "2026-01-05T00:00:00Z", "open": 12, "high": 13, "low": 11, "close": 12, "volume": 1000},
                    {"timestamp": "2026-01-06T00:00:00Z", "open": 11, "high": 12, "low": 10, "close": 11, "volume": 1000}
                ]
            }
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["data"]["strategy"] == "sma_crossover"
    assert payload["data"]["metrics"]["initial_equity"] == 100000
