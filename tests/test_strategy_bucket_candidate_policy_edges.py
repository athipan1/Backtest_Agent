from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.multi_strategy import StrategySelectionCriteria, default_multi_strategy_candidates
from app.strategy_bucket_candidate_policy import (
    CONTROLLED_NO_TRADE_MIN_TRADES,
    CONTROLLED_NO_TRADE_WARNING,
    _extract_manager_symbol_buckets,
    _force_no_trade_selection_criteria,
    _normalize_symbol_buckets,
    apply_strategy_bucket_candidate_policy,
    resolve_strategy_bucket_candidate_policy,
)


class _FakeSelection:
    def __init__(self, warnings=None):
        self.warnings = list(warnings or [])

    def model_copy(self, *, update):
        return _FakeSelection(update.get("warnings", self.warnings))


def _runner(*, existing_warning: bool = False):
    def request_class(**kwargs):
        return SimpleNamespace(**kwargs)

    def select(_request):
        warnings = [CONTROLLED_NO_TRADE_WARNING] if existing_warning else []
        return _FakeSelection(warnings)

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


def _valid_manager_report(*, positions=None, symbols=None):
    if positions is None:
        positions = [
            {
                "symbol": "AAPL",
                "strategy_bucket": "core_dividend",
                "bucket_classification_status": "classified",
                "evidence_gate_passed": True,
            }
        ]
    if symbols is None:
        symbols = ["AAPL"]
    return {
        "backtest_symbols": symbols,
        "response": {
            "status": "success",
            "data": {"pre_backtest_selected_positions": positions},
        },
    }


def test_normalize_symbol_buckets_rejects_invalid_root_and_empty_symbol():
    with pytest.raises(RuntimeError, match="JSON object"):
        _normalize_symbol_buckets([])
    with pytest.raises(RuntimeError, match="empty symbol"):
        _normalize_symbol_buckets({"": "core_dividend"})


def test_manager_report_rejects_invalid_contract_shapes():
    with pytest.raises(RuntimeError, match="root must be a JSON object"):
        _extract_manager_symbol_buckets([])
    with pytest.raises(RuntimeError, match="missing both research_backtest_selection.selected and pre_backtest_selected_positions"):
        _extract_manager_symbol_buckets({"response": {"data": {}}})
    with pytest.raises(RuntimeError, match="position must be a JSON object"):
        _extract_manager_symbol_buckets(
            _valid_manager_report(positions=["bad-row"])
        )
    with pytest.raises(RuntimeError, match="missing symbol"):
        _extract_manager_symbol_buckets(
            _valid_manager_report(
                positions=[
                    {
                        "symbol": "",
                        "strategy_bucket": "core_dividend",
                        "bucket_classification_status": "classified",
                        "evidence_gate_passed": True,
                    }
                ]
            )
        )
    with pytest.raises(RuntimeError, match="evidence gate did not pass"):
        _extract_manager_symbol_buckets(
            _valid_manager_report(
                positions=[
                    {
                        "symbol": "AAPL",
                        "strategy_bucket": "core_dividend",
                        "bucket_classification_status": "classified",
                        "evidence_gate_passed": False,
                    }
                ]
            )
        )


def test_manager_report_requires_exact_backtest_symbol_map():
    with pytest.raises(RuntimeError, match="does not match Backtest symbols"):
        _extract_manager_symbol_buckets(
            _valid_manager_report(symbols=["AAPL", "NVDA"])
        )


def test_explicit_disable_wins_even_when_manager_report_exists(monkeypatch, tmp_path):
    report_path = tmp_path / "preselection.json"
    report_path.write_text(json.dumps(_valid_manager_report()), encoding="utf-8")
    monkeypatch.setenv("BACKTEST_STRATEGY_BUCKET_AWARE_ENABLED", "false")
    monkeypatch.setenv("BACKTEST_STRATEGY_BUCKET_REPORT_PATH", str(report_path))
    monkeypatch.delenv("BACKTEST_STRATEGY_BUCKETS_JSON", raising=False)

    policy = resolve_strategy_bucket_candidate_policy()

    assert policy.applied is False


def test_enabled_policy_rejects_missing_or_invalid_sources(monkeypatch, tmp_path):
    monkeypatch.setenv("BACKTEST_STRATEGY_BUCKET_AWARE_ENABLED", "true")
    monkeypatch.delenv("BACKTEST_STRATEGY_BUCKETS_JSON", raising=False)
    monkeypatch.setenv(
        "BACKTEST_STRATEGY_BUCKET_REPORT_PATH",
        str(tmp_path / "missing.json"),
    )
    with pytest.raises(RuntimeError, match="requires BACKTEST_STRATEGY_BUCKETS_JSON"):
        resolve_strategy_bucket_candidate_policy()

    monkeypatch.setenv("BACKTEST_STRATEGY_BUCKETS_JSON", "{bad-json")
    with pytest.raises(RuntimeError, match="not valid JSON"):
        resolve_strategy_bucket_candidate_policy()

    monkeypatch.delenv("BACKTEST_STRATEGY_BUCKETS_JSON", raising=False)
    invalid_report = tmp_path / "invalid.json"
    invalid_report.write_text("{bad-json", encoding="utf-8")
    monkeypatch.setenv("BACKTEST_STRATEGY_BUCKET_REPORT_PATH", str(invalid_report))
    with pytest.raises(RuntimeError, match="report is invalid JSON"):
        resolve_strategy_bucket_candidate_policy()


def test_request_factory_rejects_invalid_symbol_shape_and_empty_upstream(monkeypatch):
    monkeypatch.setenv("BACKTEST_STRATEGY_BUCKET_AWARE_ENABLED", "true")
    monkeypatch.setenv("BACKTEST_STRATEGY_BUCKETS_JSON", '{"AAPL":"core_dividend"}')
    runner = _runner()
    apply_strategy_bucket_candidate_policy(runner)

    with pytest.raises(RuntimeError, match="exactly one Backtest symbol"):
        runner.WalkForwardMultiStrategyRequest(
            symbols=["AAPL", "MSFT"], bars={"AAPL": [], "MSFT": []}
        )
    with pytest.raises(RuntimeError, match="empty Backtest symbol"):
        runner.WalkForwardMultiStrategyRequest(symbols=[""], bars={"": []})
    with pytest.raises(RuntimeError, match="supplied no Backtest candidates"):
        runner.WalkForwardMultiStrategyRequest(
            symbols=["AAPL"], bars={"AAPL": []}, candidates=[]
        )


def test_controlled_no_trade_preserves_existing_warning(monkeypatch):
    monkeypatch.setenv("BACKTEST_STRATEGY_BUCKET_AWARE_ENABLED", "true")
    monkeypatch.setenv("BACKTEST_STRATEGY_BUCKETS_JSON", '{"NVDA":"news_momentum"}')
    runner = _runner(existing_warning=True)
    apply_strategy_bucket_candidate_policy(runner)
    mean_reversion = [
        candidate
        for candidate in default_multi_strategy_candidates()
        if candidate.strategy_id == "mean-reversion-balanced-v1"
    ]
    request = runner.WalkForwardMultiStrategyRequest(
        symbols=["NVDA"], bars={"NVDA": []}, candidates=mean_reversion
    )

    result = runner.run_walk_forward_multi_strategy_backtest(request)

    assert request.selection_criteria["min_trades"] == CONTROLLED_NO_TRADE_MIN_TRADES
    assert result.warnings == [CONTROLLED_NO_TRADE_WARNING]


def test_force_no_trade_criteria_supports_model_and_unknown_input():
    model_result = _force_no_trade_selection_criteria(StrategySelectionCriteria())
    assert model_result["min_trades"] == CONTROLLED_NO_TRADE_MIN_TRADES
    assert model_result["min_profit_factor"] == 1.2

    unknown_result = _force_no_trade_selection_criteria(object())
    assert unknown_result == {"min_trades": CONTROLLED_NO_TRADE_MIN_TRADES}


def test_policy_wraps_run_identity_and_publish_metadata(monkeypatch):
    monkeypatch.setenv("BACKTEST_STRATEGY_BUCKET_AWARE_ENABLED", "true")
    monkeypatch.setenv("BACKTEST_STRATEGY_BUCKETS_JSON", '{"AAPL":"core_dividend"}')
    runner = _runner()
    policy = apply_strategy_bucket_candidate_policy(runner)
    request = runner.WalkForwardMultiStrategyRequest(
        symbols=["AAPL"], bars={"AAPL": []}
    )

    run_identity = runner._run_id(symbol="AAPL", strategy_id="selected-v1")
    assert "strategy-bucket=core_dividend" in run_identity
    assert policy.policy_id in run_identity

    published = runner.publish_backtest_result(
        request=request,
        metadata={"existing": True},
    )
    metadata = published["metadata"]
    assert metadata["existing"] is True
    bucket_meta = metadata["strategy_bucket_candidate_policy"]
    assert bucket_meta["symbol"] == "AAPL"
    assert bucket_meta["strategy_bucket"] == "core_dividend"
    assert bucket_meta["allowed_strategy_ids"] == [
        "trend-following-balanced-v1",
        "sma-crossover-balanced-v1",
    ]

    with pytest.raises(RuntimeError, match="run identity is missing symbol"):
        runner._run_id(symbol="NVDA", strategy_id="selected-v1")

    bad_request = SimpleNamespace(symbols=["NVDA"])
    with pytest.raises(RuntimeError, match="publish metadata is missing symbol"):
        runner.publish_backtest_result(request=bad_request, metadata={})
