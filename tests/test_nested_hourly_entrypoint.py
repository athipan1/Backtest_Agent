from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from scripts import run_hourly_backtest as dispatcher
from scripts import run_nested_hourly_backtest as nested


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


def selection(*, eligible=True, nested_evidence=None):
    best = None
    selected_result = None
    if eligible:
        best = SimpleNamespace(
            strategy_id="trend-following-balanced-v1",
            rank=1,
            score=0.88,
            gates={"nested_oos_window_count": True},
            effective_parameters={"strategy": "trend_following"},
        )
        selected_result = Dumpable(
            {
                "strategy": "trend_following",
                "symbols": ["AAPL"],
                "metrics": {"return_pct": 0.12},
            }
        )
    return SimpleNamespace(
        best_eligible=best,
        selected_result=selected_result,
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


class FakeRequest:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.candidates = [SimpleNamespace(strategy_id="trend-following-balanced-v1")]


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
    monkeypatch.setattr(nested, "main", lambda: calls.append("nested"))

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


def test_statistical_policy_remains_enabled_and_multiple_testing_aware():
    criteria = nested._statistical_criteria()

    assert criteria["enabled"] is True
    assert criteria["min_observations"] == 30
    assert criteria["min_trades"] == 10
    assert criteria["max_adjusted_p_value"] == 0.05
    assert criteria["min_probabilistic_sharpe_ratio"] == 0.95
    assert criteria["min_deflated_sharpe_probability"] == 0.90
    assert criteria["bootstrap_simulations"] == 500


def test_promotion_metadata_requires_exact_independent_nested_evidence():
    metadata = nested._promotion_metadata(selection())

    assert metadata["validation_profile"] == "nested_walk_forward_v2"
    assert metadata["selection_method"] == nested.SELECTION_METHOD
    assert metadata["walk_forward_required"] is True
    assert metadata["walk_forward_status"] == "completed"
    assert metadata["walk_forward_evaluated_windows"] == 4
    assert all(metadata["promotion_gates"].values())
    assert metadata["statistical_criteria"]["enabled"] is True


@pytest.mark.parametrize(
    "nested_evidence, expected",
    [
        (evidence(overlapping_test_windows=True), "independent_test_windows"),
        (evidence(latest_selection_eligible=False), "latest_selection_eligible"),
        (
            evidence(latest_selected_strategy_id="mean-reversion-balanced-v1"),
            "exact_strategy_match",
        ),
        (evidence(status="insufficient_history"), "validation is incomplete"),
        (evidence(selection_method="legacy"), "selection method mismatch"),
    ],
)
def test_promotion_metadata_fails_closed(nested_evidence, expected):
    with pytest.raises(RuntimeError, match=expected):
        nested._promotion_metadata(selection(nested_evidence=nested_evidence))


def configure_runtime(monkeypatch, *, selected, publish):
    provider = FakeProvider()
    monkeypatch.setattr(nested, "AlpacaMarketDataProvider", lambda **kwargs: provider)
    monkeypatch.setattr(nested, "dataset_fingerprint", lambda bars: "fingerprint-aapl")
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
        lambda candidate, request: SimpleNamespace(
            symbols=["AAPL"],
            bars=request.kwargs["bars"],
        ),
    )
    monkeypatch.setattr(nested, "publish_backtest_result", publish)
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
    assert output["data"]["minimum_bars"] == 630
    assert provider.fetch_calls[0]["minimum_bars"] == 630
    assert publish_calls == []


def test_eligible_strategy_publishes_manager_compatible_evidence(monkeypatch, tmp_path):
    publish_calls = []

    def publish(**kwargs):
        publish_calls.append(kwargs)
        return {
            "status": "success",
            "payload": {"run_id": kwargs["run_id"]},
            "database_response": {"status": "success"},
        }

    monkeypatch.setenv("PUBLISH_TO_DATABASE", "true")
    monkeypatch.setenv("GITHUB_RUN_ID", "123456")
    configure_runtime(monkeypatch, selected=selection(), publish=publish)

    output = nested.run_nested_hourly_backtest(
        tmp_path / "reports" / "hourly-backtest-result.json"
    )

    assert output["status"] == "success"
    assert output["correlation_id"] == "backtest-nested-123456"
    assert output["data"]["strategy_ids_by_symbol"] == {
        "AAPL": "trend-following-balanced-v1"
    }
    assert output["data"]["published_count"] == 1
    call = publish_calls[0]
    assert call["correlation_id"] == "backtest-nested-123456"
    assert call["strategy_id"] == "trend-following-balanced-v1"
    metadata = call["metadata"]
    assert metadata["validation_profile"] == "nested_walk_forward_v2"
    assert metadata["selection_method"] == nested.SELECTION_METHOD
    assert metadata["walk_forward_validation"]["evaluated_windows"] == 4
    assert all(metadata["promotion_gates"].values())
    assert metadata["statistical_criteria"]["enabled"] is True
    assert metadata["storage_only"] is True


def test_required_publish_failure_marks_symbol_failed(monkeypatch, tmp_path):
    monkeypatch.setenv("PUBLISH_TO_DATABASE", "true")
    configure_runtime(
        monkeypatch,
        selected=selection(),
        publish=lambda **kwargs: {
            "status": "skipped",
            "payload": None,
            "database_response": {"status": "skipped"},
        },
    )

    output = nested.run_nested_hourly_backtest(
        tmp_path / "reports" / "hourly-backtest-result.json"
    )

    assert output["status"] == "error"
    assert output["data"]["failed_symbols"] == ["AAPL"]
    assert "Database publish did not succeed" in output["data"]["items"][0]["error"]
