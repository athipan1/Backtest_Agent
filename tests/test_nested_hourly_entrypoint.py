from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from app import hourly_promotion_runner as nested
from scripts import run_hourly_backtest as dispatcher
from scripts import run_nested_hourly_backtest as nested_script


class Dumpable:
    def __init__(self, value):
        self.value = value

    def model_dump(self, mode="python"):
        return self.value


class FakeProvider:
    def __init__(self, **kwargs):
        self.fetch_calls = []

    def fetch_bars(self, **kwargs):
        self.fetch_calls.append(kwargs)
        return [SimpleNamespace(timestamp="2024-01-01", close=100.0)] * 700


class FakeRunRequest:
    def __init__(self, *, bars):
        self.symbols = ["AAPL"]
        self.bars = bars

    def model_copy(self, *, deep=False, update=None):
        return self


class FakeRequest:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.candidates = [SimpleNamespace(strategy_id="trend-following-balanced-v1")]
        self.periods_per_year = kwargs["periods_per_year"]
        self.statistical_criteria = Dumpable(kwargs["statistical_criteria"])


def evidence(**updates):
    value = {
        "status": "completed",
        "selection_method": nested.SELECTION_METHOD,
        "passed": True,
        "stability_score": 0.91,
        "evaluated_windows": 4,
        "train_eligible_window_rate": 0.75,
        "profitable_window_rate": 0.75,
        "median_sharpe_ratio": 1.1,
        "median_profit_factor": 1.4,
        "worst_max_drawdown": -0.12,
        "overlapping_test_windows": False,
        "latest_selected_strategy_id": "trend-following-balanced-v1",
        "latest_selection_eligible": True,
        "total_kill_switch_events": 0,
        "gates": {
            "window_count": True,
            "train_eligible_window_rate": True,
            "profitable_window_rate": True,
            "median_sharpe_ratio": True,
            "median_profit_factor": True,
            "worst_max_drawdown": True,
            "kill_switch_safety": True,
        },
        "windows": [],
    }
    value.update(updates)
    return value


def statistical_evidence(**updates):
    value = {
        "status": "completed",
        "passed": True,
        "observation_count": 200,
        "trade_count": 20,
        "candidate_count": 4,
        "adjusted_p_value": 0.01,
        "probabilistic_sharpe_ratio": 0.98,
        "deflated_sharpe_probability": 0.94,
        "bootstrap_annualized_return_lower": 0.02,
        "gates": {
            "observation_count": True,
            "trade_count": True,
            "adjusted_p_value": True,
            "probabilistic_sharpe_ratio": True,
            "deflated_sharpe_probability": True,
            "bootstrap_lower_bound": True,
        },
        "reasons": [],
    }
    value.update(updates)
    return Dumpable(value)


def robustness_evidence(**updates):
    value = {
        "status": "completed",
        "passed": True,
        "scenario_pass_rate": 1.0,
        "catastrophic_loss": False,
        "criteria": {"min_scenario_pass_rate": 0.8},
        "gates": {
            "parameter_perturbation": True,
            "fee_stress": True,
            "spread_stress": True,
            "slippage_stress": True,
            "liquidity_stress": True,
            "drawdown_stress": True,
            "minimum_scenario_pass_rate": True,
            "no_catastrophic_loss": True,
            "finite_metrics": True,
        },
        "failure_reasons": [],
    }
    value.update(updates)
    return Dumpable(value)


def selection(*, eligible=True, nested_evidence=None):
    best = None
    if eligible:
        best = SimpleNamespace(
            strategy_id="trend-following-balanced-v1",
            rank=1,
            score=0.88,
            effective_parameters={"strategy": "trend_following"},
        )
    return SimpleNamespace(
        best_eligible=best,
        nested_walk_forward=Dumpable(nested_evidence or evidence()),
        walk_forward_criteria=Dumpable(nested._walk_forward_criteria()),
        selection_criteria=Dumpable({"min_trades": 10}),
        candidate_source="balanced_v1",
        model_dump=lambda mode="python": {
            "selection_status": (
                "eligible_strategy_found" if eligible else "no_eligible_strategy"
            )
        },
    )


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for name in [
        "BACKTEST_WALK_FORWARD_GATE_REQUIRED",
        "BACKTEST_NESTED_SELECTION_ENABLED",
        "BACKTEST_START",
        "BACKTEST_END",
        "BACKTEST_NESTED_MINIMUM_BARS",
        "PUBLISH_TO_DATABASE",
        "GITHUB_RUN_ID",
    ]:
        monkeypatch.delenv(name, raising=False)


def test_dispatcher_routes_required_validation_to_nested_runner(monkeypatch):
    calls = []
    monkeypatch.setenv("BACKTEST_WALK_FORWARD_GATE_REQUIRED", "true")
    monkeypatch.setattr(nested_script, "main", lambda: calls.append("nested"))

    dispatcher.main()

    assert calls == ["nested"]


def test_nested_defaults_support_four_independent_windows():
    criteria = nested._walk_forward_criteria()
    start, end = nested._default_date_range()

    assert criteria["train_bars"] == 126
    assert criteria["test_bars"] == 126
    assert criteria["step_bars"] == 126
    assert criteria["allow_overlapping_test_windows"] is False
    assert criteria["min_windows"] == 4
    assert nested.DEFAULT_MINIMUM_BARS == 630
    assert (datetime.fromisoformat(end) - datetime.fromisoformat(start)).days >= 1824


def test_promotion_metadata_contains_numeric_statistical_and_robustness_evidence():
    metadata = nested._promotion_metadata(
        selection(),
        statistical_evidence(),
        robustness_evidence(),
        statistical_criteria=Dumpable(nested._statistical_criteria()),
    )

    assert metadata["validation_profile"] == "nested_walk_forward_v2"
    assert metadata["walk_forward_validation"]["evaluated_windows"] == 4
    assert metadata["statistical_evidence"]["adjusted_p_value"] == 0.01
    assert metadata["statistical_evidence"]["probabilistic_sharpe_ratio"] == 0.98
    assert metadata["statistical_evidence"]["deflated_sharpe_probability"] == 0.94
    assert metadata["statistical_evidence"]["bootstrap_annualized_return_lower"] == 0.02
    assert metadata["robustness_validation"]["scenario_pass_rate"] == 1.0
    assert all(metadata["promotion_gates"].values())
    assert all(metadata["selection_gates"].values())


@pytest.mark.parametrize(
    "nested_evidence, statistical, robustness, expected",
    [
        (evidence(overlapping_test_windows=True), statistical_evidence(), robustness_evidence(), "independent_test_windows"),
        (evidence(status="insufficient_history"), statistical_evidence(), robustness_evidence(), "validation is incomplete"),
        (evidence(), statistical_evidence(passed=False), robustness_evidence(), "statistical validation did not pass"),
        (evidence(), statistical_evidence(), robustness_evidence(passed=False, failure_reasons=["fee_stress"]), "robustness validation did not pass"),
    ],
)
def test_promotion_metadata_fails_closed(nested_evidence, statistical, robustness, expected):
    with pytest.raises(RuntimeError, match=expected):
        nested._promotion_metadata(
            selection(nested_evidence=nested_evidence),
            statistical,
            robustness,
            statistical_criteria=Dumpable(nested._statistical_criteria()),
        )


def configure_runtime(monkeypatch, *, selected, publish, promote=None):
    provider = FakeProvider()
    monkeypatch.setattr(nested, "AlpacaMarketDataProvider", lambda **kwargs: provider)
    monkeypatch.setattr(nested, "dataset_fingerprint", lambda bars: "a" * 64)
    monkeypatch.setattr(nested, "WalkForwardMultiStrategyRequest", FakeRequest)
    monkeypatch.setattr(
        nested,
        "run_walk_forward_multi_strategy_backtest",
        lambda request: selected,
    )
    monkeypatch.setattr(
        nested,
        "resolve_strategy_id",
        lambda candidate, request: candidate.strategy_id,
    )
    monkeypatch.setattr(
        nested,
        "build_run_request",
        lambda candidate, request: FakeRunRequest(bars=request.kwargs["bars"]),
    )
    result = Dumpable(
        {
            "strategy": "trend_following",
            "symbols": ["AAPL"],
            "metrics": {"return_pct": 0.12},
        }
    )
    monkeypatch.setattr(nested, "run_backtest_with_risk", lambda request: result)
    monkeypatch.setattr(
        nested,
        "run_statistical_validation",
        lambda *args, **kwargs: statistical_evidence(),
    )
    monkeypatch.setattr(
        nested,
        "run_promotion_robustness",
        lambda request: robustness_evidence(),
    )
    monkeypatch.setattr(nested, "publish_backtest_result", publish)
    monkeypatch.setattr(nested, "DatabaseAgentClient", lambda: SimpleNamespace())
    monkeypatch.setattr(
        nested,
        "create_and_advance_backtest_promotion",
        promote
        or (
            lambda *args, **kwargs: {
                "promotion_id": "promotion-1",
                "state": "ROBUSTNESS_PASSED",
                "version": 4,
            }
        ),
    )
    monkeypatch.setattr(nested, "_symbols_from_env", lambda: ["AAPL"])
    return provider


def test_no_eligible_strategy_is_safe_success(monkeypatch, tmp_path):
    publish_calls = []
    provider = configure_runtime(
        monkeypatch,
        selected=selection(eligible=False),
        publish=lambda **kwargs: publish_calls.append(kwargs),
    )

    output = nested.run_nested_hourly_backtest(
        tmp_path / "reports" / "hourly-backtest-result.json"
    )

    assert output["status"] == "success"
    assert output["data"]["eligible_count"] == 0
    assert output["data"]["ineligible_count"] == 1
    assert output["data"]["no_trade_is_success"] is True
    assert provider.fetch_calls[0]["minimum_bars"] == 630
    assert publish_calls == []


def test_eligible_strategy_publishes_then_reaches_robustness(monkeypatch, tmp_path):
    publish_calls = []
    promotion_calls = []

    def publish(**kwargs):
        publish_calls.append(kwargs)
        return {
            "status": "success",
            "payload": {"run_id": kwargs["run_id"]},
            "database_response": {"status": "success"},
        }

    def promote(*args, **kwargs):
        promotion_calls.append(kwargs)
        return {
            "promotion_id": "promotion-1",
            "state": "ROBUSTNESS_PASSED",
            "version": 4,
        }

    monkeypatch.setenv("PUBLISH_TO_DATABASE", "true")
    monkeypatch.setenv("GITHUB_RUN_ID", "123456")
    configure_runtime(
        monkeypatch,
        selected=selection(),
        publish=publish,
        promote=promote,
    )

    output = nested.run_nested_hourly_backtest(
        tmp_path / "reports" / "hourly-backtest-result.json"
    )

    assert output["status"] == "success"
    assert output["data"]["published_count"] == 1
    assert output["data"]["promoted_count"] == 1
    assert output["data"]["maximum_backtest_owned_state"] == "ROBUSTNESS_PASSED"
    item = output["data"]["items"][0]
    assert item["promotion_state"] == "ROBUSTNESS_PASSED"
    metadata = publish_calls[0]["metadata"]
    assert metadata["immutable_evidence_snapshot"] is True
    assert metadata["statistical_evidence"]["passed"] is True
    assert metadata["robustness_validation"]["passed"] is True
    assert promotion_calls[0]["run_id"] == publish_calls[0]["run_id"]


def test_publish_or_lifecycle_failure_prevents_false_green(monkeypatch, tmp_path):
    monkeypatch.setenv("PUBLISH_TO_DATABASE", "true")
    configure_runtime(
        monkeypatch,
        selected=selection(),
        publish=lambda **kwargs: {
            "status": "success",
            "payload": {"run_id": kwargs["run_id"]},
            "database_response": {"status": "success"},
        },
        promote=lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("promotion transition failed")
        ),
    )

    output = nested.run_nested_hourly_backtest(
        tmp_path / "reports" / "hourly-backtest-result.json"
    )

    assert output["status"] == "error"
    assert output["data"]["failed_symbols"] == ["AAPL"]
    assert output["data"]["published"] is False
    assert "promotion transition failed" in output["data"]["items"][0]["error"]
