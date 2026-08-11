from __future__ import annotations

from app import hourly_promotion_runner as hourly


def _metadata(*, bars: int = 252, holdout_fingerprint: str = "h" * 64):
    return {
        "evidence_version": 3,
        "walk_forward_criteria": {"train_bars": 126, "test_bars": 126},
        "statistical_schema_version": "statistical-validation.v2",
        "statistical_criteria": {"bootstrap_method": "stationary"},
        "robustness_validation": {"criteria": {"min_scenario_pass_rate": 0.8}},
        "final_holdout_criteria": {
            "enabled": True,
            "bars": bars,
            "min_trades": 10,
            "min_return": 0.0,
            "min_sharpe": 0.0,
            "max_drawdown_floor": -0.20,
        },
        "sealed_holdout": {"dataset_fingerprint": holdout_fingerprint},
    }


def _run_id(metadata):
    return hourly._run_id(
        symbol="AAPL",
        strategy_id="strategy-a",
        fingerprint="f" * 64,
        research_fingerprint="r" * 64,
        effective_parameters={
            "strategy": "sma_crossover",
            "fast_window": 10,
            "slow_window": 30,
        },
        timeframe="1d",
        promotion_metadata=metadata,
    )


def test_final_holdout_environment_is_explicit_and_normalizes_drawdown(monkeypatch):
    monkeypatch.setenv("BACKTEST_FINAL_HOLDOUT_ENABLED", "true")
    monkeypatch.setenv("BACKTEST_FINAL_HOLDOUT_BARS", "300")
    monkeypatch.setenv("BACKTEST_FINAL_HOLDOUT_MIN_TRADES", "12")
    monkeypatch.setenv("BACKTEST_FINAL_HOLDOUT_MIN_RETURN", "0.03")
    monkeypatch.setenv("BACKTEST_FINAL_HOLDOUT_MIN_SHARPE", "0.7")
    monkeypatch.setenv("BACKTEST_FINAL_HOLDOUT_MAX_DRAWDOWN", "0.15")

    criteria = hourly._final_holdout_criteria()

    assert criteria.enabled is True
    assert criteria.bars == 300
    assert criteria.min_trades == 12
    assert criteria.min_return == 0.03
    assert criteria.min_sharpe == 0.7
    assert criteria.max_drawdown_floor == -0.15


def test_holdout_policy_change_changes_run_identity():
    assert _run_id(_metadata(bars=252)) != _run_id(_metadata(bars=300))


def test_holdout_dataset_change_changes_run_identity():
    assert _run_id(_metadata(holdout_fingerprint="a" * 64)) != _run_id(
        _metadata(holdout_fingerprint="b" * 64)
    )


def test_research_dataset_change_changes_run_identity():
    metadata = _metadata()
    first = hourly._run_id(
        symbol="AAPL",
        strategy_id="strategy-a",
        fingerprint="f" * 64,
        research_fingerprint="a" * 64,
        effective_parameters={"strategy": "sma_crossover"},
        timeframe="1d",
        promotion_metadata=metadata,
    )
    second = hourly._run_id(
        symbol="AAPL",
        strategy_id="strategy-a",
        fingerprint="f" * 64,
        research_fingerprint="b" * 64,
        effective_parameters={"strategy": "sma_crossover"},
        timeframe="1d",
        promotion_metadata=metadata,
    )

    assert first != second
