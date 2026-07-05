from fastapi.testclient import TestClient

from app import main as app_main


client = TestClient(app_main.app)


def test_run_and_publish_endpoint_publishes_backtest_payload(monkeypatch):
    calls = []

    def fake_publish_backtest_result(**kwargs):
        calls.append(kwargs)
        return {
            "status": "success",
            "database_response": {"status": "success", "data": {"run_id": kwargs["run_id"]}},
            "payload": {
                "run_id": kwargs["run_id"],
                "account_id": kwargs["account_id"],
                "skill_id": kwargs["skill_id"],
                "strategy_id": kwargs["strategy_id"],
                "symbol": "AAPL",
            },
        }

    monkeypatch.setattr(app_main, "publish_backtest_result", fake_publish_backtest_result)

    response = client.post(
        "/backtest/run-and-publish",
        json={
            "account_id": "1",
            "run_id": "run-1",
            "skill_id": "skill-1",
            "strategy_id": "strategy-alpha",
            "timeframe": "1d",
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
                    {"timestamp": "2026-01-06T00:00:00Z", "open": 11, "high": 12, "low": 10, "close": 11, "volume": 1000},
                ]
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["data"]["published"] is True
    assert body["data"]["publish_status"] == "success"
    assert body["data"]["database_payload"]["skill_id"] == "skill-1"
    assert calls[0]["account_id"] == "1"
    assert calls[0]["skill_id"] == "skill-1"


def test_run_and_publish_endpoint_can_skip_database_publish(monkeypatch):
    def fail_if_called(**kwargs):
        raise AssertionError("publish should not be called when publish_to_database is false")

    monkeypatch.setattr(app_main, "publish_backtest_result", fail_if_called)

    response = client.post(
        "/backtest/run-and-publish",
        json={
            "publish_to_database": False,
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
                    {"timestamp": "2026-01-06T00:00:00Z", "open": 11, "high": 12, "low": 10, "close": 11, "volume": 1000},
                ]
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["published"] is False
    assert body["data"]["publish_status"] == "skipped"
