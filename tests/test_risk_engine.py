from app.models import BacktestRunRequest
from app.risk_engine import run_backtest_with_risk


def bars(closes):
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


def base_request(**overrides):
    data = {
        "symbols": ["AAPL"],
        "initial_equity": 100000,
        "fast_window": 2,
        "slow_window": 3,
        "fee_bps": 0,
        "slippage_bps": 0,
        "bars": {"AAPL": bars([10, 11, 12, 13, 12, 11, 10])},
    }
    data.update(overrides)
    return BacktestRunRequest(**data)


def test_risk_aware_backtest_records_no_rejections_for_safe_run():
    result = run_backtest_with_risk(base_request())

    assert result.metrics.risk_rejections == 0
    assert result.metrics.kill_switch_events == 0
    assert result.risk_rejections == []
    assert len(result.trades) >= 2


def test_risk_aware_backtest_rejects_entries_when_emergency_halt_active():
    result = run_backtest_with_risk(base_request(emergency_halt=True))

    assert result.trades == []
    assert result.metrics.risk_rejections >= 1
    assert result.metrics.kill_switch_events >= 1
    assert "emergency_halt_active" in result.risk_rejections[0].violations


def test_risk_aware_backtest_can_be_run_without_risk_adapter():
    result = run_backtest_with_risk(base_request(use_risk_agent=False, emergency_halt=True))

    assert result.metrics.risk_rejections == 0
    assert len(result.trades) >= 2


def test_risk_aware_backtest_executes_close_signal_at_next_open():
    rows = [
        {"timestamp": "2026-01-01T00:00:00Z", "open": 100, "high": 100, "low": 99, "close": 100, "volume": 1000},
        {"timestamp": "2026-01-02T00:00:00Z", "open": 101, "high": 102, "low": 100, "close": 101, "volume": 1000},
        {"timestamp": "2026-01-03T00:00:00Z", "open": 102, "high": 104, "low": 101, "close": 103, "volume": 1000},
        {"timestamp": "2026-01-04T00:00:00Z", "open": 120, "high": 122, "low": 119, "close": 121, "volume": 1000},
    ]
    result = run_backtest_with_risk(
        base_request(
            strategy="breakout",
            fast_window=1,
            slow_window=2,
            bars={"AAPL": rows},
        )
    )

    buy = next(trade for trade in result.trades if trade.side == "buy")
    assert buy.price == 120
    assert buy.timestamp.isoformat() == "2026-01-04T00:00:00+00:00"
