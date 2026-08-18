from __future__ import annotations

import json
from copy import deepcopy
from types import SimpleNamespace

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


class Dumpable:
    def __init__(self, value):
        self.value = value

    def model_dump(self, mode="json"):
        return self.value


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


def test_runtime_adapter_captures_holdout_evidence_and_rewrites_reports(tmp_path):
    result = SimpleNamespace(symbols=["NVDA"])
    request = SimpleNamespace(symbols=["NVDA"])
    statistical = Dumpable(
        {"status": "completed", "passed": True, "gates": {"all": True}}
    )
    robustness = Dumpable(
        {"status": "completed", "passed": True, "gates": {"all": True}}
    )
    holdout = Dumpable(
        {
            "enabled": True,
            "passed": False,
            "strategy_id": "sma-crossover-balanced-v1",
            "gates": {
                "minimum_return": False,
                "minimum_sharpe": True,
            },
        }
    )
    runner = None

    def original_statistical(value, *args, **kwargs):
        assert value is result
        return statistical

    def original_robustness(value, *args, **kwargs):
        assert value is request
        return robustness

    def original_holdout(*args, **kwargs):
        assert kwargs["result"] is result
        return holdout

    def original_hourly(report_path):
        runner.run_statistical_validation(result)
        runner.run_promotion_robustness(request)
        runner.evaluate_sealed_final_holdout(result=result)
        return _output(
            _failed(
                "NVDA",
                "sealed final holdout blocked promotion: "
                "sealed_final_holdout_all_gates, sealed_final_holdout_passed",
            )
        )

    runner = SimpleNamespace(
        VALIDATION_PROFILE="nested_walk_forward_v3",
        run_walk_forward_multi_strategy_backtest=object(),
        run_statistical_validation=original_statistical,
        run_promotion_robustness=original_robustness,
        evaluate_sealed_final_holdout=original_holdout,
        run_nested_hourly_backtest=original_hourly,
    )
    evidence = v4.apply_nested_validation_v4(runner)
    report_path = tmp_path / "reports" / "hourly-backtest-result.json"

    output = runner.run_nested_hourly_backtest(report_path)

    assert evidence["expected_gate_rejections_are_operational_failures"] is False
    assert output["status"] == "success"
    assert output["data"]["failed_symbols"] == []
    assert output["data"]["ineligible_symbols"] == ["NVDA"]
    item = output["data"]["items"][0]
    assert item["rejection_stage"] == "sealed_final_holdout"
    assert item["rejection_evidence"] == holdout.value
    assert item["sealed_holdout"]["status"] == "opened_rejected"
    assert item["sealed_holdout"]["passed"] is False
    assert report_path.exists()
    persisted = json.loads(report_path.read_text(encoding="utf-8"))
    assert persisted["status"] == "success"
    item_path = report_path.parent / "hourly-backtest-nvda.json"
    assert item_path.exists()
    persisted_item = json.loads(item_path.read_text(encoding="utf-8"))
    assert persisted_item["rejection_stage"] == "sealed_final_holdout"

    second = v4.apply_nested_validation_v4(runner)
    assert second["validation_profile"] == "nested_walk_forward_v4"
