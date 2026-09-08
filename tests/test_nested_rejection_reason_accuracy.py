from types import SimpleNamespace

from app.models import BacktestMetrics
from app.multi_strategy_walk_forward import WalkForwardStabilityResult, _walk_forward_item


def stability(**changes):
    return WalkForwardStabilityResult(
        **dict(
            status="completed",
            passed=False,
            stability_score=0.7,
            available_bars=1000,
            evaluated_windows=6,
            profitable_windows=2,
            profitable_window_rate=1 / 3,
            latest_selected_strategy_id="sma",
            latest_selection_eligible=True,
            gates={"profitable_window_rate": False},
            reasons=["walk_forward_profitable_window_rate gate failed (observed=0.333333)"],
            **changes,
        )
    )


def base():
    metrics = BacktestMetrics(
        initial_equity=100,
        final_equity=101,
        net_profit=1,
        return_pct=0.01,
        trade_count=10,
        winning_trades=5,
        losing_trades=5,
        win_rate=0.5,
        gross_profit=10,
        gross_loss=-9,
        profit_factor=10 / 9,
        expectancy=0.1,
        max_drawdown=-0.1,
    )
    return SimpleNamespace(
        rank=1,
        strategy_id="sma",
        name="SMA",
        strategy="sma_crossover",
        fast_window=10,
        slow_window=30,
        effective_parameters={},
        eligible=False,
        gates={},
        score_components={},
        metrics=metrics,
        warnings=[],
    )


def test_selected_latest_but_oos_failed_reports_actual_blocker():
    item = _walk_forward_item(
        base_item=base(), stability=stability(), promotion_eligible=False, nested=stability()
    )
    assert item.eligible is False
    assert item.gates["latest_training_selection"] is True
    assert "not selected by the latest nested training window" not in item.disqualification_reasons
    assert any(reason.startswith("nested_outer_oos:") for reason in item.disqualification_reasons)


def test_unselected_latest_retains_selection_blocker():
    nested = stability().model_copy(update={"latest_selected_strategy_id": "another"})
    item = _walk_forward_item(
        base_item=base(), stability=stability(), promotion_eligible=False, nested=nested
    )
    assert item.eligible is False
    assert item.gates["latest_training_selection"] is False
    assert "not selected by the latest nested training window" in item.disqualification_reasons
