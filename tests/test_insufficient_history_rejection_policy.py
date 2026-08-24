from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.insufficient_history_rejection_policy import (
    _history_counts,
    _reclassify_insufficient_history,
    apply_insufficient_history_rejection_policy,
)


def _output(*items):
    return {
        "status": "error",
        "data": {
            "items": list(items),
            "eligible_symbols": [],
            "ineligible_symbols": [],
            "failed_symbols": [item["symbol"] for item in items],
            "eligible_count": 0,
            "ineligible_count": 0,
            "published_count": 0,
            "promoted_count": 0,
            "published": False,
            "publish_status": "partial_failure",
            "all_succeeded": False,
            "selection_complete": False,
            "promotion_lifecycle_required": True,
            "no_trade_is_success": True,
        },
        "error": "One or more nested walk-forward Backtests failed operationally.",
    }


def _failed(symbol: str, error: str):
    return {
        "symbol": symbol,
        "status": "failed",
        "selected_strategy_id": None,
        "published": False,
        "promoted": False,
        "publish_status": "failed",
        "selection": None,
        "error": error,
    }


def _ineligible(symbol: str):
    return {
        "symbol": symbol,
        "status": "no_eligible_strategy",
        "selected_strategy_id": None,
        "published": False,
        "promoted": False,
        "publish_status": "skipped",
        "selection": {"selection_status": "no_eligible_strategy"},
        "error": None,
    }


def test_hourly_yb_insufficient_history_becomes_controlled_no_trade():
    output = _output(
        _failed(
            "YB",
            "Need at least 882 bars for nested walk-forward promotion; received 330",
        ),
        _ineligible("GCT"),
    )

    changed = _reclassify_insufficient_history(output)

    assert changed is True
    assert output["status"] == "success"
    assert output["error"] is None
    assert output["data"]["all_succeeded"] is True
    assert output["data"]["selection_complete"] is True
    assert output["data"]["published"] is True
    assert output["data"]["publish_status"] == "success"
    assert output["data"]["failed_symbols"] == []
    assert output["data"]["ineligible_symbols"] == ["YB", "GCT"]
    item = output["data"]["items"][0]
    assert item["status"] == "no_eligible_strategy"
    assert item["rejection_code"] == "insufficient_history"
    assert item["rejection_stage"] == "historical_data"
    assert item["history_bars_observed"] == 330
    assert item["history_bars_required"] == 882
    assert item["publish_status"] == "skipped"
    assert item["published"] is False
    assert item["promoted"] is False
    assert item["error"] is None
    assert item["sealed_holdout"]["status"] == "sealed_not_opened"


def test_provider_insufficient_history_message_is_controlled_rejection():
    assert _history_counts("YB returned 330 bars; at least 882 are required") == (
        330,
        882,
    )


def test_sealed_holdout_insufficient_history_message_is_controlled_rejection():
    assert _history_counts(
        "insufficient history for sealed final holdout: "
        "observed=330, required=882, research=630, holdout=252"
    ) == (330, 882)


def test_operational_market_data_failure_remains_fail_closed():
    output = _output(
        _failed("YB", "failed to fetch Alpaca Market Data for YB: HTTP Error 503")
    )

    changed = _reclassify_insufficient_history(output)

    assert changed is False
    assert output["status"] == "error"
    assert output["data"]["all_succeeded"] is False
    assert output["data"]["failed_symbols"] == ["YB"]
    assert output["data"]["items"][0]["status"] == "failed"


def test_malformed_bar_failure_remains_fail_closed():
    output = _output(_failed("YB", "YB bar 10 is invalid: close must be positive"))

    changed = _reclassify_insufficient_history(output)

    assert changed is False
    assert output["status"] == "error"
    assert output["data"]["items"][0]["status"] == "failed"


def test_impossible_history_message_does_not_get_reclassified():
    assert _history_counts("YB returned 900 bars; at least 882 are required") is None


def test_adapter_rewrites_report_and_item_after_controlled_rejection(tmp_path):
    report_path = tmp_path / "reports" / "hourly-backtest-result.json"
    runner_output = _output(
        _failed("YB", "YB returned 330 bars; at least 882 are required")
    )
    runner = SimpleNamespace(
        run_nested_hourly_backtest=lambda path: runner_output,
    )

    policy = apply_insufficient_history_rejection_policy(runner)
    result = runner.run_nested_hourly_backtest(report_path)

    assert policy["outcome"] == "NO_TRADE"
    assert policy["fail_closed"] is True
    assert result["status"] == "success"
    assert report_path.exists()
    assert (report_path.parent / "hourly-backtest-yb.json").exists()
