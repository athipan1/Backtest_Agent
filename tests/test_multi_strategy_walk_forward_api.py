from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def bars(count=300):
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    rows = []
    price = 100.0
    for index in range(count):
        price += 0.45 if index % 16 < 10 else -0.30
        rows.append(
            {
                "timestamp": (start + timedelta(days=index)).isoformat(),
                "open": price - 0.2,
                "high": price + 1.0,
                "low": price - 1.0,
                "close": price,
                "volume": 1_000_000,
            }
        )
    return rows


def test_walk_forward_multi_strategy_endpoint_returns_stability_evidence():
    response = client.post(
        "/backtest/multi-strategy/walk-forward",
        json={
            "symbols": ["AAPL"],
            "initial_equity": 100000,
            "bars": {"AAPL": bars()},
            "candidates": [
                {
                    "strategy_id": "mean-reversion-api-v1",
                    "name": "Mean reversion API",
                    "strategy": "mean_reversion",
                    "fast_window": 5,
                    "slow_window": 20,
                }
            ],
            "walk_forward_criteria": {
                "train_bars": 60,
                "test_bars": 60,
                "step_bars": 60,
                "min_windows": 4,
                "min_profitable_window_rate": 0.5,
                "min_median_sharpe_ratio": 0.0,
                "min_median_profit_factor": 0.0,
                "max_drawdown_floor": -0.5,
            },
            "fee_bps": 0,
            "slippage_bps": 0,
            "force_close_at_end": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    data = payload["data"]
    assert data["symbol"] == "AAPL"
    assert data["evaluated_count"] == 1
    assert len(data["ranked_results"]) == 1
    item = data["ranked_results"][0]
    assert item["strategy_id"] == "mean-reversion-api-v1"
    assert item["walk_forward"]["evaluated_windows"] == 4
    assert len(item["walk_forward"]["windows"]) == 4
    assert "walk_forward_stability" in item["score_components"]
    assert data["selection_status"] in {
        "eligible_strategy_found",
        "no_eligible_strategy",
    }
    if data["best_eligible"] is None:
        assert data["selected_result"] is None
    else:
        assert data["selected_result"] is not None


def test_walk_forward_endpoint_rejects_multiple_symbols():
    response = client.post(
        "/backtest/multi-strategy/walk-forward",
        json={
            "symbols": ["AAPL", "MSFT"],
            "initial_equity": 100000,
            "bars": {"AAPL": bars(), "MSFT": bars()},
        },
    )

    assert response.status_code == 422


def test_ready_contract_advertises_walk_forward_multi_strategy():
    response = client.get("/ready")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["multi_strategy_walk_forward_endpoint"] == (
        "/backtest/multi-strategy/walk-forward"
    )
    assert data["multi_strategy_walk_forward"] == {
        "rolling_out_of_sample": True,
        "default_train_bars": 126,
        "default_test_bars": 126,
        "default_step_bars": 63,
        "default_min_windows": 4,
        "requires_full_period_and_walk_forward": True,
    }
