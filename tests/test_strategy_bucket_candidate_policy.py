from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.multi_strategy import default_multi_strategy_candidates
from app.strategy_bucket_candidate_policy import (
    apply_strategy_bucket_candidate_policy,
    resolve_strategy_bucket_candidate_policy,
    strategy_ids_for_bucket,
)


def _runner():
    def request_class(**kwargs):
        return kwargs

    def run_id(**kwargs):
        return kwargs["strategy_id"]

    def publish(**kwargs):
        return kwargs

    return SimpleNamespace(
        WalkForwardMultiStrategyRequest=request_class,
        _run_id=run_id,
        publish_backtest_result=publish,
    )


def test_bucket_strategy_profiles_are_narrow_and_explainable():
    assert strategy_ids_for_bucket("core_dividend") == (
        "trend-following-balanced-v1",
        "sma-crossover-balanced-v1",
    )
    assert strategy_ids_for_bucket("value_rebound") == (
        "mean-reversion-balanced-v1",
        "sma-crossover-balanced-v1",
    )
    assert strategy_ids_for_bucket("news_momentum") == (
        "breakout-balanced-v1",
        "trend-following-balanced-v1",
    )


def test_disabled_policy_does_not_change_runner(monkeypatch):
    monkeypatch.delenv("BACKTEST_STRATEGY_BUCKET_AWARE_ENABLED", raising=False)
    runner = _runner()
    original = runner.WalkForwardMultiStrategyRequest

    policy = apply_strategy_bucket_candidate_policy(runner)

    assert policy.applied is False
    assert runner.WalkForwardMultiStrategyRequest is original


def test_news_momentum_filters_default_candidates(monkeypatch):
    monkeypatch.setenv("BACKTEST_STRATEGY_BUCKET_AWARE_ENABLED", "true")
    monkeypatch.setenv(
        "BACKTEST_STRATEGY_BUCKETS_JSON",
        '{"AAPL":"news_momentum"}',
    )
    runner = _runner()
    policy = apply_strategy_bucket_candidate_policy(runner)

    request = runner.WalkForwardMultiStrategyRequest(
        symbols=["AAPL"],
        bars={"AAPL": []},
    )

    assert policy.applied is True
    assert [candidate.strategy_id for candidate in request["candidates"]] == [
        "trend-following-balanced-v1",
        "breakout-balanced-v1",
    ]


def test_bucket_policy_intersects_later_regime_candidates(monkeypatch):
    monkeypatch.setenv("BACKTEST_STRATEGY_BUCKET_AWARE_ENABLED", "true")
    monkeypatch.setenv(
        "BACKTEST_STRATEGY_BUCKETS_JSON",
        '{"NVDA":"news_momentum"}',
    )
    runner = _runner()
    apply_strategy_bucket_candidate_policy(runner)
    upstream = [
        candidate
        for candidate in default_multi_strategy_candidates()
        if candidate.strategy_id
        in {"sma-crossover-balanced-v1", "trend-following-balanced-v1"}
    ]

    request = runner.WalkForwardMultiStrategyRequest(
        symbols=["NVDA"],
        bars={"NVDA": []},
        candidates=upstream,
    )

    assert [candidate.strategy_id for candidate in request["candidates"]] == [
        "trend-following-balanced-v1"
    ]


def test_policy_fails_closed_when_symbol_bucket_missing(monkeypatch):
    monkeypatch.setenv("BACKTEST_STRATEGY_BUCKET_AWARE_ENABLED", "true")
    monkeypatch.setenv(
        "BACKTEST_STRATEGY_BUCKETS_JSON",
        '{"AAPL":"core_dividend"}',
    )
    runner = _runner()
    apply_strategy_bucket_candidate_policy(runner)

    with pytest.raises(RuntimeError, match="missing Backtest symbol NVDA"):
        runner.WalkForwardMultiStrategyRequest(
            symbols=["NVDA"],
            bars={"NVDA": []},
        )


def test_policy_fails_closed_on_unknown_bucket(monkeypatch):
    monkeypatch.setenv("BACKTEST_STRATEGY_BUCKET_AWARE_ENABLED", "true")
    monkeypatch.setenv(
        "BACKTEST_STRATEGY_BUCKETS_JSON",
        '{"AAPL":"unassigned"}',
    )

    with pytest.raises(RuntimeError, match="Unsupported strategy bucket"):
        resolve_strategy_bucket_candidate_policy()
