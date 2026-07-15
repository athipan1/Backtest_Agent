from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.models import BacktestMetrics
from app.multi_strategy import (
    MultiStrategyBacktestRequest,
    StrategySelectionCriteria,
    default_multi_strategy_candidates,
    evaluate_selection_gates,
    run_multi_strategy_backtest,
)


def bars(count=90):
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    rows = []
    price = 100.0
    for index in range(count):
        cycle = index % 20
        drift = 1.2 if cycle < 12 else -0.9
        price = max(20.0, price + drift)
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


def metrics(**overrides):
    payload = {
        "initial_equity": 100000,
        "final_equity": 112000,
        "net_profit": 12000,
        "return_pct": 0.12,
        "trade_count": 20,
        "winning_trades": 12,
        "losing_trades": 8,
        "win_rate": 0.60,
        "gross_profit": 18000,
        "gross_loss": -6000,
        "profit_factor": 3.0,
        "expectancy": 600,
        "max_drawdown": -0.10,
        "annualized_return": 0.15,
        "annualized_volatility": 0.20,
        "sharpe_ratio": 1.25,
        "sortino_ratio": 1.60,
        "calmar_ratio": 1.50,
        "benchmark_return_pct": 0.08,
        "excess_return_pct": 0.04,
        "realized_net_profit": 12000,
        "unrealized_pnl": 0,
        "open_position_count": 0,
        "allocation_rejections": 0,
        "partial_fills": 0,
        "liquidity_rejections": 0,
        "risk_rejections": 0,
        "kill_switch_events": 0,
    }
    payload.update(overrides)
    return BacktestMetrics(**payload)


def test_default_suite_covers_every_supported_strategy_once():
    candidates = default_multi_strategy_candidates()

    assert [candidate.strategy for candidate in candidates] == [
        "sma_crossover",
        "trend_following",
        "mean_reversion",
        "breakout",
    ]
    assert len({candidate.strategy_id for candidate in candidates}) == 4


def test_selection_gates_require_complete_risk_adjusted_evidence():
    criteria = StrategySelectionCriteria()
    gates, reasons = evaluate_selection_gates(metrics(), criteria)

    assert all(gates.values())
    assert reasons == []

    failed_gates, failed_reasons = evaluate_selection_gates(
        metrics(
            trade_count=2,
            annualized_return=-0.05,
            sharpe_ratio=None,
            profit_factor=0.80,
            max_drawdown=-0.35,
            excess_return_pct=-0.10,
            kill_switch_events=1,
        ),
        criteria,
    )

    assert not any(failed_gates.values())
    assert len(failed_reasons) == len(failed_gates)


def test_multi_strategy_run_is_ranked_and_exact_symbol_scoped():
    request = MultiStrategyBacktestRequest(
        symbols=["aapl"],
        initial_equity=100000,
        bars={"AAPL": bars()},
        fee_bps=0,
        slippage_bps=0,
        force_close_at_end=True,
    )

    result = run_multi_strategy_backtest(request)

    assert result.symbol == "AAPL"
    assert result.candidate_source == "balanced_v1"
    assert result.evaluated_count == 4
    assert [item.rank for item in result.ranked_results] == [1, 2, 3, 4]
    assert len({item.strategy_id for item in result.ranked_results}) == 4
    assert {item.strategy for item in result.ranked_results} == {
        "sma_crossover",
        "trend_following",
        "mean_reversion",
        "breakout",
    }
    assert result.selection_status in {
        "eligible_strategy_found",
        "no_eligible_strategy",
    }
    if result.best_eligible is None:
        assert result.selected_result is None
        assert result.warnings
    else:
        assert result.best_eligible.eligible is True
        assert result.selected_result is not None
        assert result.selected_result.strategy == result.best_eligible.strategy


def test_multi_strategy_rejects_ambiguous_strategy_identity():
    duplicate = {
        "strategy_id": "duplicate-v1",
        "name": "duplicate",
        "strategy": "sma_crossover",
        "fast_window": 2,
        "slow_window": 5,
    }

    with pytest.raises(ValidationError, match="duplicate strategy identities"):
        MultiStrategyBacktestRequest(
            symbols=["AAPL"],
            initial_equity=100000,
            bars={"AAPL": bars()},
            candidates=[duplicate, duplicate],
        )


def test_multi_strategy_rejects_portfolio_level_selection():
    with pytest.raises(ValidationError):
        MultiStrategyBacktestRequest(
            symbols=["AAPL", "MSFT"],
            initial_equity=100000,
            bars={"AAPL": bars(), "MSFT": bars()},
        )
