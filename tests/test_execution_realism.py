from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.api_contracts import StrictBacktestRunRequest
from app.engine import run_backtest
from app.execution import (
    buy_execution_price,
    max_entry_quantity,
    sell_execution_price,
    volume_capacity,
)
from app.execution_policy import (
    ExecutionRealismPolicy,
    execution_policy_context,
)
from app.main import app
from app.models import BacktestRunRequest, PriceBar, RiskCheckPayload
from app.publisher import ENGINE_VERSION, build_database_backtest_payload
from app.risk_adapter import LocalRiskAdapter
from app.risk_engine import run_backtest_with_risk
from app.run_identity import deterministic_symbol_run_id


client = TestClient(app)


def bar(index: int, *, open_price: float, high: float, low: float, close: float) -> PriceBar:
    return PriceBar(
        timestamp=datetime(2026, 1, 1) + timedelta(days=index),
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=1000,
    )


def breakout_request(rows: list[PriceBar], **overrides) -> BacktestRunRequest:
    payload = {
        "symbols": ["AAPL"],
        "initial_equity": 10000,
        "bars": {"AAPL": rows},
        "strategy": "breakout",
        "fast_window": 1,
        "slow_window": 2,
        "max_position_pct": 0.10,
        "stop_loss_pct": 0.03,
        "reward_risk_ratio": 2.0,
        "fee_bps": 0,
        "slippage_bps": 0,
        "use_risk_agent": False,
    }
    payload.update(overrides)
    return BacktestRunRequest(**payload)


def signal_then_gap_rows() -> list[PriceBar]:
    return [
        bar(0, open_price=100, high=100, low=99, close=100),
        bar(1, open_price=101, high=102, low=100, close=101),
        bar(2, open_price=102, high=104, low=101, close=103),
        bar(3, open_price=120, high=122, low=119, close=121),
    ]


def test_close_signal_fills_at_next_bar_open_without_lookahead():
    result = run_backtest(breakout_request(signal_then_gap_rows()))

    buy = next(trade for trade in result.trades if trade.side == "buy")
    assert buy.timestamp == signal_then_gap_rows()[3].timestamp
    assert buy.price == 120
    assert result.execution_model == "next_bar_open"


def test_open_position_metrics_reconcile_unrealized_pnl_and_final_equity():
    result = run_backtest(breakout_request(signal_then_gap_rows()))

    assert result.metrics.trade_count == 0
    assert result.metrics.realized_net_profit == 0
    assert result.metrics.unrealized_pnl == 8
    assert result.metrics.open_position_count == 1
    assert result.metrics.net_profit == pytest.approx(
        result.metrics.realized_net_profit + result.metrics.unrealized_pnl
    )


def test_realized_pnl_includes_entry_and_exit_fees():
    rows = [
        bar(0, open_price=100, high=100, low=99, close=100),
        bar(1, open_price=101, high=102, low=100, close=101),
        bar(2, open_price=102, high=104, low=101, close=103),
        bar(3, open_price=104, high=110, low=103, close=110),
    ]
    result = run_backtest(
        breakout_request(rows, fee_bps=100, force_close_at_end=True)
    )

    buy = next(trade for trade in result.trades if trade.side == "buy")
    sell = next(trade for trade in result.trades if trade.side == "sell")
    expected = (
        (sell.price - buy.price) * buy.quantity
        - buy.fees
        - sell.fees
    )

    assert sell.reason == "end_of_data"
    assert sell.realized_pnl == pytest.approx(expected)
    assert result.metrics.realized_net_profit == pytest.approx(expected)
    assert result.metrics.unrealized_pnl == 0
    assert result.metrics.open_position_count == 0
    assert result.metrics.net_profit == pytest.approx(expected)


def test_force_close_at_end_is_explicit_and_optional():
    open_result = run_backtest(breakout_request(signal_then_gap_rows()))
    closed_result = run_backtest(
        breakout_request(signal_then_gap_rows(), force_close_at_end=True)
    )

    assert open_result.metrics.open_position_count == 1
    assert not any(trade.reason == "end_of_data" for trade in open_result.trades)
    assert closed_result.metrics.open_position_count == 0
    assert closed_result.trades[-1].reason == "end_of_data"


def strict_request(**policy_updates) -> StrictBacktestRunRequest:
    rows = [
        {
            "timestamp": f"2026-01-{index:02d}T00:00:00Z",
            "open": close,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": 10000,
        }
        for index, close in enumerate(
            [10, 11, 12, 13, 12, 11, 12, 13],
            start=1,
        )
    ]
    return StrictBacktestRunRequest(
        symbols=["AAPL"],
        initial_equity=100000,
        fast_window=2,
        slow_window=3,
        fee_bps=0,
        slippage_bps=0,
        use_risk_agent=True,
        force_close_at_end=True,
        max_volume_participation_pct=1.0,
        bars={"AAPL": rows},
        execution_policy={
            "bid_ask_spread_bps": 0.0,
            "quantity_increment": 1,
            "signal_execution_delay_bars": 1,
            **policy_updates,
        },
    )


def test_buy_and_sell_prices_cross_half_of_configured_spread():
    policy = ExecutionRealismPolicy(bid_ask_spread_bps=10.0)

    with execution_policy_context(policy):
        buy_price = buy_execution_price(
            100.0,
            slippage_bps=0.0,
            market_impact_bps=0.0,
            quantity=10,
            volume=1000,
        )
        sell_price = sell_execution_price(
            100.0,
            slippage_bps=0.0,
            market_impact_bps=0.0,
            quantity=10,
            volume=1000,
        )

    assert buy_price == pytest.approx(100.05)
    assert sell_price == pytest.approx(99.95)
    assert buy_price - sell_price == pytest.approx(0.10)


def test_volume_and_entry_quantity_are_aligned_to_increment():
    policy = ExecutionRealismPolicy(quantity_increment=10)

    with execution_policy_context(policy):
        assert volume_capacity(105, 1.0) == 100
        quantity = max_entry_quantity(
            97,
            available_volume_quantity=105,
            reference_price=100,
            bar_volume=10000,
            slippage_bps=0,
            market_impact_bps=0,
            fee_bps=0,
            remaining_cash=1_000_000,
            remaining_exposure=1_000_000,
            portfolio_equity=1_000_000,
            risk_per_trade=1.0,
            max_position_pct=1.0,
            stop_loss_pct=0.01,
        )

    assert quantity == 90


def test_local_risk_clipping_preserves_quantity_increment():
    adapter = LocalRiskAdapter()
    policy = ExecutionRealismPolicy(quantity_increment=10)

    with execution_policy_context(policy):
        decision = adapter.evaluate(
            RiskCheckPayload(
                symbol="AAPL",
                side="buy",
                entry_price=100,
                protection_price=99,
                equity=100000,
                requested_quantity=97,
            ),
            max_position_pct=1.0,
            max_trades_per_day=5,
            risk_per_trade=1.0,
        )

    assert decision.approved is True
    assert decision.final_quantity == 90
    assert "quantity_rounded_to_execution_increment" in decision.warnings


def test_execution_policy_reads_environment_defaults(monkeypatch):
    monkeypatch.setenv("BACKTEST_DEFAULT_BID_ASK_SPREAD_BPS", "4.5")
    monkeypatch.setenv("BACKTEST_DEFAULT_QUANTITY_INCREMENT", "5")

    policy = ExecutionRealismPolicy()

    assert policy.bid_ask_spread_bps == 4.5
    assert policy.quantity_increment == 5
    assert policy.signal_execution_delay_bars == 1


def test_api_rejects_unimplemented_multi_bar_signal_delay():
    payload = strict_request().model_dump(mode="json")
    payload["execution_policy"]["signal_execution_delay_bars"] = 2

    response = client.post("/backtest/run", json=payload)

    assert response.status_code == 422


def test_spread_and_quantity_policy_apply_through_full_engine():
    baseline = run_backtest_with_risk(strict_request())
    realistic = run_backtest_with_risk(
        strict_request(bid_ask_spread_bps=20.0, quantity_increment=10)
    )

    baseline_buys = [trade for trade in baseline.trades if trade.side == "buy"]
    realistic_buys = [trade for trade in realistic.trades if trade.side == "buy"]
    assert baseline_buys
    assert realistic_buys
    assert realistic_buys[0].price > baseline_buys[0].price
    assert all(trade.quantity % 10 == 0 for trade in realistic.trades)
    assert realistic.metrics.final_equity <= baseline.metrics.final_equity


def test_execution_policy_changes_deterministic_run_identity():
    baseline = strict_request()
    realistic = strict_request(
        bid_ask_spread_bps=5.0,
        quantity_increment=10,
    )

    baseline_id = deterministic_symbol_run_id(
        baseline,
        symbol="AAPL",
        timeframe="1d",
        engine_version=ENGINE_VERSION,
    )
    realistic_id = deterministic_symbol_run_id(
        realistic,
        symbol="AAPL",
        timeframe="1d",
        engine_version=ENGINE_VERSION,
    )

    assert baseline_id != realistic_id


def test_database_payload_records_engine_v07_and_execution_policy():
    request = strict_request(
        bid_ask_spread_bps=5.0,
        quantity_increment=10,
    )
    result = run_backtest_with_risk(request)

    payload = build_database_backtest_payload(
        request=request,
        result=result,
        account_id="1",
        run_id="run-realism-1",
    )

    assert payload["engine_version"] == "backtest-agent-0.7.0"
    assert payload["parameters"]["execution_policy"] == {
        "bid_ask_spread_bps": 5.0,
        "quantity_increment": 10,
        "signal_execution_delay_bars": 1,
    }
    assert payload["metadata"]["execution_policy"] == (
        payload["parameters"]["execution_policy"]
    )
