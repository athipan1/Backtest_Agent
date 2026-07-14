from datetime import datetime, timezone

from app.models import BacktestRunRequest, SimulatedTrade
from app.publisher import _trade_pairs, build_database_backtest_payload, publish_backtest_result
from app.risk_engine import run_backtest_with_risk


def _bars():
    return [
        {"timestamp": "2026-01-01T00:00:00Z", "open": 10, "high": 11, "low": 9, "close": 10, "volume": 1000},
        {"timestamp": "2026-01-02T00:00:00Z", "open": 11, "high": 12, "low": 10, "close": 11, "volume": 1000},
        {"timestamp": "2026-01-03T00:00:00Z", "open": 12, "high": 13, "low": 11, "close": 12, "volume": 1000},
        {"timestamp": "2026-01-04T00:00:00Z", "open": 13, "high": 14, "low": 12, "close": 13, "volume": 1000},
        {"timestamp": "2026-01-05T00:00:00Z", "open": 12, "high": 13, "low": 11, "close": 12, "volume": 1000},
        {"timestamp": "2026-01-06T00:00:00Z", "open": 11, "high": 12, "low": 10, "close": 11, "volume": 1000},
    ]


def _request() -> BacktestRunRequest:
    return BacktestRunRequest(
        symbols=["aapl"],
        initial_equity=100000,
        fast_window=2,
        slow_window=3,
        fee_bps=0,
        slippage_bps=0,
        bars={"AAPL": _bars()},
    )


class FakeDatabaseClient:
    def __init__(self):
        self.payload = None
        self.correlation_id = None

    def publish_backtest_run(self, payload, *, correlation_id=None):
        self.payload = payload
        self.correlation_id = correlation_id
        return {"status": "success", "data": {"run_id": payload["run_id"]}}


def test_trade_pair_publishes_total_round_trip_fees():
    timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = _trade_pairs(
        [
            SimulatedTrade(
                symbol="AAPL",
                side="buy",
                quantity=10,
                price=100,
                fees=1,
                timestamp=timestamp,
            ),
            SimulatedTrade(
                symbol="AAPL",
                side="sell",
                quantity=10,
                price=110,
                fees=1.1,
                timestamp=timestamp,
                realized_pnl=97.9,
            ),
        ]
    )

    assert rows[0]["fees"] == 2.1
    assert rows[0]["realized_pl"] == 97.9


def test_build_database_backtest_payload_shapes_result_for_database_agent():
    request = _request()
    result = run_backtest_with_risk(request)

    payload = build_database_backtest_payload(
        request=request,
        result=result,
        account_id="1",
        run_id="run-1",
        skill_id="skill-1",
        strategy_id="strategy-alpha",
        timeframe="1d",
        metadata={"test": True},
    )

    assert payload["run_id"] == "run-1"
    assert payload["account_id"] == "1"
    assert payload["skill_id"] == "skill-1"
    assert payload["strategy_id"] == "strategy-alpha"
    assert payload["symbol"] == "AAPL"
    assert payload["status"] == "completed"
    assert payload["metrics"]["initial_equity"] == 100000
    assert "win_rate" in payload["metrics"]
    assert "realized_net_profit" in payload["metrics"]
    assert "unrealized_pnl" in payload["metrics"]
    assert payload["metadata"]["execution_model"] == "next_bar_open"
    assert payload["equity_curve"]
    assert payload["metadata"]["source_agent"] == "backtest-agent"
    assert payload["metadata"]["test"] is True


def test_publish_backtest_result_uses_database_client_and_returns_payload():
    request = _request()
    result = run_backtest_with_risk(request)
    database_client = FakeDatabaseClient()

    report = publish_backtest_result(
        request=request,
        result=result,
        account_id="1",
        run_id="run-1",
        skill_id="skill-1",
        database_client=database_client,
        correlation_id="corr-1",
    )

    assert report["status"] == "success"
    assert report["payload"]["run_id"] == "run-1"
    assert report["database_response"]["data"]["run_id"] == "run-1"
    assert database_client.payload["skill_id"] == "skill-1"
    assert database_client.correlation_id == "corr-1"
