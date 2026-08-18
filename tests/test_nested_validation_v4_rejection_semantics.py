from __future__ import annotations

from copy import deepcopy

from app import nested_validation_v4 as v4


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
        },
        "error": "One or more nested walk-forward Backtests failed operationally.",
    }


def _failed(symbol: str, error: str, *, published: bool = False):
    return {
        "symbol": symbol,
        "status": "failed",
        "selected_strategy_id": None,
        "published": published,
        "promoted": False,
        "publish_status": "failed",
        "selection": None,
        "error": error,
    }


def test_expected_statistical_rejection_becomes_safe_no_trade():
    output = _output(
        _failed("META", "selected strategy statistical validation did not pass")
    )
    statistical = {
        "META": {
            "status": "completed",
            "passed": False,
            "gates": {"adjusted_p_value": False},
        }
    }

    changed = v4._reclassify_expected_gate_rejections(
        output,
        statistical_by_symbol=statistical,
        robustness_by_symbol={},
        holdout_by_symbol={},
    )

    assert changed is True
    item = output["data"]["items"][0]
    assert item["status"] == "no_eligible_strategy"
    assert item["rejection_stage"] == "statistical_validation"
    assert item["rejection_evidence"] == statistical["META"]
    assert item["sealed_holdout"] == {
        "enabled": True,
        "status": "sealed_not_opened",
    }
    assert item["published"] is False
    assert item["promoted"] is False
    assert item["error"] is None
    assert output["status"] == "success"
    assert output["data"]["selection_complete"] is True
    assert output["data"]["failed_symbols"] == []
    assert output["data"]["ineligible_symbols"] == ["META"]
    assert output["data"]["published"] is True


def test_final_holdout_rejection_is_recorded_as_opened_rejected():
    output = _output(
        _failed(
            "NVDA",
            "sealed final holdout blocked promotion: "
            "sealed_final_holdout_all_gates, sealed_final_holdout_passed",
        )
    )
    holdout = {
        "NVDA": {
            "enabled": True,
            "passed": False,
            "strategy_id": "sma-crossover-balanced-v1",
            "gates": {
                "minimum_return": False,
                "minimum_sharpe": True,
            },
        }
    }

    changed = v4._reclassify_expected_gate_rejections(
        output,
        statistical_by_symbol={},
        robustness_by_symbol={},
        holdout_by_symbol=holdout,
    )

    assert changed is True
    item = output["data"]["items"][0]
    assert item["status"] == "no_eligible_strategy"
    assert item["rejection_stage"] == "sealed_final_holdout"
    assert item["sealed_holdout"]["status"] == "opened_rejected"
    assert item["sealed_holdout"]["passed"] is False
    assert item["sealed_holdout"]["gates"]["minimum_return"] is False
    assert item["published"] is False
    assert item["promoted"] is False
    assert output["status"] == "success"
    assert output["data"]["ineligible_count"] == 1
    assert output["data"]["published_count"] == 0
    assert output["data"]["promoted_count"] == 0


def test_operational_failure_remains_failed():
    original = _output(_failed("AAPL", "Alpaca Market Data HTTP 500"))
    output = deepcopy(original)

    changed = v4._reclassify_expected_gate_rejections(
        output,
        statistical_by_symbol={},
        robustness_by_symbol={},
        holdout_by_symbol={},
    )

    assert changed is False
    assert output == original
    assert output["status"] == "error"
    assert output["data"]["failed_symbols"] == ["AAPL"]


def test_never_reclassifies_an_item_that_claims_publication():
    output = _output(
        _failed(
            "NVDA",
            "sealed final holdout blocked promotion: sealed_final_holdout_passed",
            published=True,
        )
    )

    changed = v4._reclassify_expected_gate_rejections(
        output,
        statistical_by_symbol={},
        robustness_by_symbol={},
        holdout_by_symbol={},
    )

    assert changed is False
    assert output["data"]["items"][0]["status"] == "failed"
