from __future__ import annotations

import json

from app.strategy_bucket_candidate_policy import resolve_strategy_bucket_candidate_policy


def _write_report(path, *, research_selected=None, legacy_selected=None, symbols=None):
    data = {}
    if research_selected is not None:
        data["research_backtest_selection"] = {"selected": research_selected}
    if legacy_selected is not None:
        data["pre_backtest_selected_positions"] = legacy_selected
    path.write_text(
        json.dumps(
            {
                "backtest_symbols": symbols or [],
                "response": {"status": "success", "data": data},
            }
        ),
        encoding="utf-8",
    )


def test_research_backtest_selection_is_source_for_bucket_map(monkeypatch, tmp_path):
    report_path = tmp_path / "hourly-pre-backtest-discovery.json"
    _write_report(
        report_path,
        symbols=["YB", "GCT"],
        research_selected=[
            {
                "symbol": "YB",
                "strategy_bucket": "value_rebound",
                "bucket_classification_status": "classified",
                "evidence_gate_passed": True,
            },
            {
                "symbol": "GCT",
                "strategy_bucket": "news_momentum",
                "bucket_classification_status": "classified",
                "evidence_gate_passed": True,
            },
        ],
        legacy_selected=[],
    )
    monkeypatch.setenv("BACKTEST_STRATEGY_BUCKET_AWARE_ENABLED", "true")
    monkeypatch.delenv("BACKTEST_STRATEGY_BUCKETS_JSON", raising=False)
    monkeypatch.setenv("BACKTEST_STRATEGY_BUCKET_REPORT_PATH", str(report_path))

    policy = resolve_strategy_bucket_candidate_policy()

    assert policy.applied is True
    assert policy.symbol_buckets == {
        "YB": "value_rebound",
        "GCT": "news_momentum",
    }


def test_legacy_pre_backtest_positions_remain_supported(monkeypatch, tmp_path):
    report_path = tmp_path / "hourly-pre-backtest-discovery.json"
    _write_report(
        report_path,
        symbols=["AAPL"],
        legacy_selected=[
            {
                "symbol": "AAPL",
                "strategy_bucket": "core_dividend",
                "bucket_classification_status": "classified",
                "evidence_gate_passed": True,
            }
        ],
    )
    monkeypatch.setenv("BACKTEST_STRATEGY_BUCKET_AWARE_ENABLED", "true")
    monkeypatch.delenv("BACKTEST_STRATEGY_BUCKETS_JSON", raising=False)
    monkeypatch.setenv("BACKTEST_STRATEGY_BUCKET_REPORT_PATH", str(report_path))

    policy = resolve_strategy_bucket_candidate_policy()

    assert policy.symbol_buckets == {"AAPL": "core_dividend"}
