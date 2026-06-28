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


def test_backtest_compare_endpoint():
    bars = [
        {"timestamp": "2026-01-01T00:00:00Z", "open": 10, "high": 11, "low": 9, "close": 10, "volume": 1000},
        {"timestamp": "2026-01-02T00:00:00Z", "open": 11, "high": 12, "low": 10, "close": 11, "volume": 1000},
        {"timestamp": "2026-01-03T00:00:00Z", "open": 12, "high": 13, "low": 11, "close": 12, "volume": 1000},
        {"timestamp": "2026-01-04T00:00:00Z", "open": 13, "high": 14, "low": 12, "close": 13, "volume": 1000},
        {"timestamp": "2026-01-05T00:00:00Z", "open": 12, "high": 13, "low": 11, "close": 12, "volume": 1000},
        {"timestamp": "2026-01-06T00:00:00Z", "open": 11, "high": 12, "low": 10, "close": 11, "volume": 1000},
        {"timestamp": "2026-01-07T00:00:00Z", "open": 12, "high": 13, "low": 11, "close": 12, "volume": 1000}
    ]
    response = client.post(
        "/backtest/compare",
        json={
            "symbols": ["AAPL"],
            "initial_equity": 100000,
            "fee_bps": 0,
            "slippage_bps": 0,
            "bars": {"AAPL": bars},
            "candidates": [
                {"name": "fast", "fast_window": 2, "slow_window": 3},
                {"name": "slow", "fast_window": 3, "slow_window": 5}
            ]
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["data"]["symbols"] == ["AAPL"]
    assert len(payload["data"]["ranked_results"]) == 2
    assert payload["data"]["best"]["rank"] == 1


def test_backtest_walk_forward_endpoint():
    bars = [
        {"timestamp": f"2026-01-{index:02d}T00:00:00Z", "open": 10 + index % 5, "high": 12 + index % 5, "low": 9 + index % 5, "close": 10 + index % 5, "volume": 1000}
        for index in range(1, 21)
    ]
    response = client.post(
        "/backtest/walk-forward",
        json={
            "symbols": ["AAPL"],
            "initial_equity": 100000,
            "train_ratio": 0.6,
            "min_train_bars": 5,
            "min_test_bars": 3,
            "fee_bps": 0,
            "slippage_bps": 0,
            "bars": {"AAPL": bars},
            "candidates": [
                {"name": "fast", "fast_window": 2, "slow_window": 3},
                {"name": "slow", "fast_window": 3, "slow_window": 5}
            ]
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["data"]["symbols"] == ["AAPL"]
    assert payload["data"]["selected_candidate"]["rank"] == 1
    assert payload["data"]["test_result"] is not None


def test_backtest_report_endpoint():
    response = client.post(
        "/backtest/report",
        json={
            "min_trades": 1,
            "result": {
                "strategy": "sma_crossover",
                "symbols": ["AAPL"],
                "trades": [],
                "equity_curve": [],
                "risk_rejections": [],
                "warnings": [],
                "metrics": {
                    "initial_equity": 100000,
                    "final_equity": 112000,
                    "net_profit": 12000,
                    "return_pct": 0.12,
                    "trade_count": 12,
                    "winning_trades": 8,
                    "losing_trades": 4,
                    "win_rate": 0.66,
                    "gross_profit": 15000,
                    "gross_loss": -3000,
                    "profit_factor": 5.0,
                    "expectancy": 1000,
                    "max_drawdown": -0.05,
                    "risk_rejections": 0,
                    "kill_switch_events": 0
                }
            }
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["data"]["verdict"] == "paper_ready"
    assert payload["data"]["gates"]["trade_count"] is True
    assert payload["data"]["score"] >= 0.8
