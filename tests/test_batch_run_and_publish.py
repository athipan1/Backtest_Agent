from fastapi.testclient import TestClient

from app import main as app_main


client = TestClient(app_main.app)


def _bars(offset=0):
    closes = [10, 11, 12, 13, 12, 11]
    return [
        {
            "timestamp": f"2026-01-{index:02d}T00:00:00Z",
            "open": close + offset,
            "high": close + offset + 1,
            "low": close + offset - 1,
            "close": close + offset,
            "volume": 1000,
        }
        for index, close in enumerate(closes, start=1)
    ]


def _request(**updates):
    payload = {
        "account_id": "1",
        "batch_id": "batch-1",
        "skill_id": "skill-1",
        "strategy_id": "strategy-alpha",
        "timeframe": "1d",
        "publish_to_database": True,
        "symbols": ["aapl", "MSFT"],
        "initial_equity": 100000,
        "fast_window": 2,
        "slow_window": 3,
        "fee_bps": 0,
        "slippage_bps": 0,
        "bars": {
            "AAPL": _bars(),
            "MSFT": _bars(100),
        },
    }
    payload.update(updates)
    return payload


def test_batch_endpoint_publishes_one_exact_database_run_per_symbol(monkeypatch):
    calls = []

    def fake_publish_backtest_result(**kwargs):
        calls.append(kwargs)
        symbol = kwargs["request"].symbols[0]
        return {
            "status": "success",
            "database_response": {
                "status": "success",
                "data": {"run_id": kwargs["run_id"]},
            },
            "payload": {
                "run_id": kwargs["run_id"],
                "skill_id": kwargs["skill_id"],
                "strategy_id": kwargs["strategy_id"],
                "symbol": symbol,
                "timeframe": kwargs["timeframe"],
            },
        }

    monkeypatch.setattr(
        app_main,
        "publish_backtest_result",
        fake_publish_backtest_result,
    )

    response = client.post(
        "/backtest/run-and-publish-batch",
        json=_request(symbols=["aapl", "AAPL", "msft"]),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["data"]["symbols"] == ["AAPL", "MSFT"]
    assert body["data"]["succeeded_symbols"] == ["AAPL", "MSFT"]
    assert body["data"]["failed_symbols"] == []
    assert body["data"]["published_count"] == 2
    assert body["data"]["published"] is True
    assert body["data"]["all_succeeded"] is True
    assert [item["run_id"] for item in body["data"]["items"]] == [
        "batch-1-aapl",
        "batch-1-msft",
    ]
    assert [call["request"].symbols for call in calls] == [["AAPL"], ["MSFT"]]
    assert [call["request"].initial_equity for call in calls] == [100000, 100000]
    assert [call["metadata"]["batch_symbol"] for call in calls] == [
        "AAPL",
        "MSFT",
    ]


def test_batch_endpoint_reports_partial_failure_without_cross_symbol_fallback(monkeypatch):
    def fake_publish_backtest_result(**kwargs):
        symbol = kwargs["request"].symbols[0]
        if symbol == "MSFT":
            raise RuntimeError("Database unavailable for MSFT")
        return {
            "status": "success",
            "database_response": {"status": "success"},
            "payload": {"run_id": kwargs["run_id"], "symbol": symbol},
        }

    monkeypatch.setattr(
        app_main,
        "publish_backtest_result",
        fake_publish_backtest_result,
    )

    response = client.post(
        "/backtest/run-and-publish-batch",
        json=_request(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "error"
    assert body["data"]["publish_status"] == "partial_failure"
    assert body["data"]["published"] is False
    assert body["data"]["all_succeeded"] is False
    assert body["data"]["succeeded_symbols"] == ["AAPL"]
    assert body["data"]["failed_symbols"] == ["MSFT"]
    failed = body["data"]["items"][1]
    assert failed["symbol"] == "MSFT"
    assert "Database unavailable for MSFT" in failed["error"]


def test_batch_endpoint_can_simulate_all_symbols_without_database_publish(monkeypatch):
    def fail_if_called(**kwargs):
        raise AssertionError("publisher must not run")

    monkeypatch.setattr(app_main, "publish_backtest_result", fail_if_called)

    response = client.post(
        "/backtest/run-and-publish-batch",
        json=_request(publish_to_database=False),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["data"]["publish_status"] == "skipped"
    assert body["data"]["published"] is False
    assert body["data"]["published_count"] == 0
    assert body["data"]["all_succeeded"] is True
