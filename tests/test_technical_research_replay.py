from datetime import datetime, timedelta, timezone

import pytest

from app.technical_research_replay import (
    nested_pit_diagnostics,
    signal_as_of,
    validate_pit_rows,
)


def rows(count=24):
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    return [
        {
            "timestamp": start + timedelta(days=i),
            "indicators_as_of": start + timedelta(days=i),
            "regime_as_of": start + timedelta(days=i),
            "open": float(100 + i),
            "close": 105.0,
            "sma200": 100.0,
            "rsi14": 60.0,
            "macd": 0.30,
            "macd_signal": 0.10,
            "regime": "bull",
        }
        for i in range(count)
    ]


def test_research_predicates_match_technical_observation_without_order_authority():
    assert signal_as_of(rows()[0]) == {
        "trend_following": True,
        "mean_reversion": False,
    }
    oversold = dict(rows()[0], close=95.0, rsi14=25.0)
    assert signal_as_of(oversold) == {
        "trend_following": False,
        "mean_reversion": True,
    }
    oversold["macd"] = float("nan")
    assert not any(signal_as_of(oversold).values())


def test_future_indicators_are_rejected():
    sample = rows()
    sample[3]["indicators_as_of"] += timedelta(days=1)
    with pytest.raises(ValueError, match="look_ahead"):
        validate_pit_rows(sample)


def test_unsorted_and_naive_timestamps_fail_closed():
    sample = rows()
    sample[4]["timestamp"] = sample[3]["timestamp"]
    with pytest.raises(ValueError, match="chronological"):
        validate_pit_rows(sample)
    sample = rows()
    sample[0]["indicators_as_of"] = datetime(2025, 1, 1)
    with pytest.raises(ValueError, match="timezone-aware"):
        validate_pit_rows(sample)


def test_nested_folds_are_disjoint_and_costs_reduce_results():
    sample = rows(35)
    low = nested_pit_diagnostics(
        sample, train_bars=9, test_bars=6, embargo_bars=2, cost_bps=0,
    )
    high = nested_pit_diagnostics(
        sample, train_bars=9, test_bars=6, embargo_bars=2, cost_bps=1000,
    )
    assert low["fold_count"] > 0
    assert not low["passed"]
    assert low["diagnostic_only"]
    assert not low["production_certified"]
    assert not low["execution_authorized"]
    assert not low["sealed_holdout_opened"]
    for fold in low["folds"]:
        assert fold["train_end"] < fold["test_start"]
        for trade in fold["test_trades"]:
            assert fold["test_start"] <= trade["signal_at"]
            assert trade["entry_at"] > trade["signal_at"]
            assert trade["exit_at"] > trade["entry_at"]
            assert trade["exit_at"] <= fold["test_end"]
            assert trade["regime"] == "bull"
    assert high["cost_bps_round_trip"] > low["cost_bps_round_trip"]
    assert all(
        high_fold["test_metrics"]["net_return_sum"]
        <= low_fold["test_metrics"]["net_return_sum"]
        for high_fold, low_fold in zip(high["folds"], low["folds"])
    )


def test_no_training_edge_abstains_instead_of_trading():
    sample = rows()
    for bar in sample:
        bar["macd"] = -1
    report = nested_pit_diagnostics(
        sample, train_bars=9, test_bars=6, embargo_bars=2
    )
    assert report["fold_count"] > 0
    assert all(fold["abstained"] for fold in report["folds"])
    assert all(fold["test_metrics"]["trade_count"] == 0 for fold in report["folds"])


def test_future_regime_labels_are_rejected():
    sample = rows()
    sample[4]["regime_as_of"] += timedelta(days=1)
    with pytest.raises(ValueError, match="look_ahead_regime_timestamp"):
        validate_pit_rows(sample)
