from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app.main import app
from app.models import BacktestRobustnessRequest, PriceBar
from app.robustness import (
    _neighboring_windows,
    monte_carlo_trade_bootstrap,
    run_robustness_analysis,
)


client = TestClient(app)


def bars() -> list[PriceBar]:
    closes = [100, 103, 106, 99, 96, 102, 108, 101, 95, 104, 110, 100]
    return [
        PriceBar(
            timestamp=datetime(2026, 1, 1) + timedelta(days=index),
            open=close,
            high=close + 2,
            low=close - 2,
            close=close,
            volume=10000,
        )
        for index, close in enumerate(closes)
    ]


def robustness_request(**overrides) -> BacktestRobustnessRequest:
    payload = {
        "symbols": ["AAPL"],
        "initial_equity": 10000,
        "bars": {"AAPL": bars()},
        "strategy": "sma_crossover",
        "fast_window": 2,
        "slow_window": 4,
        "fee_bps": 0,
        "slippage_bps": 0,
        "use_risk_agent": False,
        "force_close_at_end": True,
        "monte_carlo_simulations": 200,
        "monte_carlo_seed": 7,
        "min_monte_carlo_trades": 2,
    }
    payload.update(overrides)
    return BacktestRobustnessRequest(**payload)


def test_monte_carlo_bootstrap_is_deterministic_for_same_seed():
    inputs = {
        "initial_equity": 10000,
        "trade_pnls": [100, -50, 80, -20, 40],
        "simulations": 500,
        "seed": 123,
        "minimum_trades": 5,
    }

    first = monte_carlo_trade_bootstrap(**inputs)
    second = monte_carlo_trade_bootstrap(**inputs)

    assert first.model_dump() == second.model_dump()
    assert first.status == "completed"
    assert first.p05_final_equity <= first.median_final_equity
    assert first.median_final_equity <= first.p95_final_equity
    assert 0 <= first.probability_of_loss <= 1
    assert first.p05_max_drawdown <= first.median_max_drawdown <= 0


def test_monte_carlo_refuses_to_invent_confidence_from_too_few_trades():
    result = monte_carlo_trade_bootstrap(
        initial_equity=10000,
        trade_pnls=[100, -50],
        simulations=100,
        seed=42,
        minimum_trades=5,
    )

    assert result.status == "insufficient_data"
    assert result.median_final_equity is None
    assert result.probability_of_loss is None
    assert "requires at least 5 closed trades" in result.reason


def test_parameter_neighborhood_is_stable_sorted_and_excludes_baseline():
    request = robustness_request()

    windows = _neighboring_windows(request)

    assert windows == sorted(windows)
    assert (2, 4) not in windows
    assert len(windows) == len(set(windows)) == 7
    assert all(fast < slow for fast, slow in windows)

    edge_windows = _neighboring_windows(
        robustness_request(fast_window=1, slow_window=2)
    )
    assert edge_windows == [(1, 3), (2, 3)]


def test_robustness_analysis_runs_baseline_and_neighboring_parameters():
    result = run_robustness_analysis(robustness_request())

    assert result.baseline.symbols == ["AAPL"]
    assert result.sensitivity.scenario_count == 7
    assert len(result.sensitivity.scenarios) == 7
    assert 1 <= result.sensitivity.baseline_rank_by_return <= 8
    assert result.sensitivity.worst_return_pct <= result.sensitivity.best_return_pct
    assert result.monte_carlo.status in {"completed", "insufficient_data"}


def test_robustness_endpoint_returns_transparent_insufficient_data_status():
    request = robustness_request(min_monte_carlo_trades=10)

    response = client.post(
        "/backtest/robustness",
        json=request.model_dump(mode="json"),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["data"]["monte_carlo"]["status"] == "insufficient_data"
    assert "monte_carlo_insufficient_closed_trades" in payload["data"]["warnings"]
    assert payload["data"]["sensitivity"]["scenario_count"] == 7
