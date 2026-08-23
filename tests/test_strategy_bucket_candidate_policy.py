from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.multi_strategy import default_multi_strategy_candidates
from app.strategy_bucket_candidate_policy import (
    CONTROLLED_NO_TRADE_MIN_TRADES,
    CONTROLLED_NO_TRADE_WARNING,
    apply_strategy_bucket_candidate_policy,
    resolve_strategy_bucket_candidate_policy,
    strategy_ids_for_bucket,
)


class _FakeSelection:
    def __init__(self, warnings=None):
        self.warnings = list(warnings or [])

    def model_copy(self, *, update):
        return _FakeSelection(update.get("warnings", self.warnings))


def _runner():
    def request_class(**kwargs):
        return SimpleNamespace(**kwargs)

    def select(_request):
        return _FakeSelection()

    def run_id(**kwargs):
        return kwargs["strategy_id"]

    def publish(**kwargs):
        return kwargs

    return SimpleNamespace(
        WalkForwardMultiStrategyRequest=request_class,
        run_walk_forward_multi_strategy_backtest=select,
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


def test_disabled_policy_does_not_change_runner(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("BACKTEST_STRATEGY_BUCKET_AWARE_ENABLED", raising=False)
    monkeypatch.delenv("BACKTEST_STRATEGY_BUCKETS_JSON", raising=False)
    monkeypatch.delenv("BACKTEST_STRATEGY_BUCKET_REPORT_PATH", raising=False)
    runner = _runner()
    original = runner.WalkForwardMultiStrategyRequest

    policy = apply_strategy_bucket_candidate_policy(runner)

    assert policy.applied is False
    assert runner.WalkForwardMultiStrategyRequest is original


def test_manager_preselection_report_auto_enables_policy(monkeypatch, tmp_path):
    report_path = tmp_path / "hourly-pre-backtest-discovery.json"
    report_path.write_text(
        json.dumps(
            {
                "backtest_symbols": ["AAPL", "NVDA"],
                "response": {
                    "status": "success",
                    "data": {
                        "pre_backtest_selected_positions": [
                            {
                                "symbol": "AAPL",
                                "strategy_bucket": "core_dividend",
                                "bucket_classification_status": "classified",
                                "evidence_gate_passed": True,
                            },
                            {
                                "symbol": "NVDA",
                                "strategy_bucket": "news_momentum",
                                "bucket_classification_status": "classified",
                                "evidence_gate_passed": True,
                            },
                        ]
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("BACKTEST_STRATEGY_BUCKET_AWARE_ENABLED", raising=False)
    monkeypatch.delenv("BACKTEST_STRATEGY_BUCKETS_JSON", raising=False)
    monkeypatch.setenv("BACKTEST_STRATEGY_BUCKET_REPORT_PATH", str(report_path))

    policy = resolve_strategy_bucket_candidate_policy()

    assert policy.applied is True
    assert policy.symbol_buckets == {
        "AAPL": "core_dividend",
        "NVDA": "news_momentum",
    }
    assert policy.source == f"manager_report:{report_path}"


def test_manager_report_fails_closed_on_unclassified_position(monkeypatch, tmp_path):
    report_path = tmp_path / "hourly-pre-backtest-discovery.json"
    report_path.write_text(
        json.dumps(
            {
                "backtest_symbols": ["AAPL"],
                "response": {
                    "data": {
                        "pre_backtest_selected_positions": [
                            {
                                "symbol": "AAPL",
                                "strategy_bucket": "core_dividend",
                                "bucket_classification_status": "review",
                                "evidence_gate_passed": True,
                            }
                        ]
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("BACKTEST_STRATEGY_BUCKET_AWARE_ENABLED", raising=False)
    monkeypatch.delenv("BACKTEST_STRATEGY_BUCKETS_JSON", raising=False)
    monkeypatch.setenv("BACKTEST_STRATEGY_BUCKET_REPORT_PATH", str(report_path))

    with pytest.raises(RuntimeError, match="not classified"):
        resolve_strategy_bucket_candidate_policy()


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
    assert [candidate.strategy_id for candidate in request.candidates] == [
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

    assert [candidate.strategy_id for candidate in request.candidates] == [
        "trend-following-balanced-v1"
    ]


def test_empty_bucket_regime_intersection_becomes_controlled_no_trade(monkeypatch):
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
        if candidate.strategy_id == "mean-reversion-balanced-v1"
    ]

    request = runner.WalkForwardMultiStrategyRequest(
        symbols=["NVDA"],
        bars={"NVDA": []},
        candidates=upstream,
    )
    result = runner.run_walk_forward_multi_strategy_backtest(request)

    assert [candidate.strategy_id for candidate in request.candidates] == [
        "mean-reversion-balanced-v1"
    ]
    assert request.selection_criteria["min_trades"] == CONTROLLED_NO_TRADE_MIN_TRADES
    assert CONTROLLED_NO_TRADE_WARNING in result.warnings


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
