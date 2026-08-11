from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
        start = datetime(2021, 1, 1, tzinfo=timezone.utc)
        return [
            SimpleNamespace(
                timestamp=start + timedelta(days=index),
                close=100.0 + index,
            )
            for index in range(900)
        ]


class FakeRunRequest:
    def __init__(self, *, bars):
        self.symbols = ["AAPL"]
        self.bars = bars

    def model_copy(self, *, deep=False, update=None):
        if update and "bars" in update:
            return FakeRunRequest(bars=update["bars"])
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
        "schema_version": nested.STATISTICAL_VALIDATION_V2,
        "status": "completed",
        "passed": True,
        "observation_count": 200,
        "trade_count": 20,
        "candidate_count": 4,
        "autocorrelation_lag1": 0.21,
        "hac_standard_error": 0.0008,
        "effective_sample_size": 142.5,
        "hac_mean_positive_probability": 0.99,
        "adjusted_p_value": 0.01,
        "probabilistic_sharpe_ratio": 0.98,
        "deflated_sharpe_probability": 0.94,
        "bootstrap_method": "stationary",
        "bootstrap_block_size": 10,
        "bootstrap_annualized_return_lower": 0.02,
        "block_bootstrap_annualized_return_lower": 0.02,
        "iid_bootstrap_annualized_return_lower": 0.03,
        "gates": {
            "observation_count": True,
            "trade_count": True,
            "adjusted_p_value": True,
            "probabilistic_sharpe_ratio": True,
            "deflated_sharpe_probability": True,
            "bootstrap_lower_bound": True,
            "block_bootstrap_lower_bound": True,
            "hac_mean_confidence": True,
            "time_series_bootstrap_authority": True,
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


def holdout_evidence(**updates):
    value = {
        "enabled": True,
        "start": "2024-01-01T00:00:00+00:00",
        "end": "2024-12-31T00:00:00+00:00",
        "bar_count": 252,
        "trade_count": 20,
        "return_pct": 0.08,
        "sharpe_ratio": 1.1,
        "profit_factor": 1.4,
        "max_drawdown": -0.08,
        "dataset_fingerprint": "b" * 64,
        "strategy_id": "trend-following-balanced-v1",
        "effective_parameters_sha256": "c" * 64,
        "passed": True,
        "gates": {
            "bar_count": True,
            "minimum_trades": True,
            "minimum_return": True,
            "minimum_sharpe": True,
            "maximum_drawdown": True,
            "exact_strategy": True,
        },
        "criteria": {
            "enabled": True,
            "bars": 252,
            "min_trades": 10,
            "min_return": 0.0,
            "min_sharpe": 0.0,
            "max_drawdown_floor": -0.20,
        },
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
            effective_parameters={
                "strategy": "trend_following",
                "fast_window": 10,
                "slow_window": 30,
            },
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
        "BACKTEST_FINAL_HOLDOUT_ENABLED",
        "BACKTEST_FINAL_HOLDOUT_BARS",
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


def test_nested_defaults_support_four_independent_windows_plus_sealed_holdout():
    criteria = nested._walk_forward_criteria()
    holdout = nested._final_holdout_criteria()
    start, end = nested._default_date_range()

    assert criteria["train_bars"] == 126
    assert criteria["test_bars"] == 126
    assert criteria["step_bars"] == 126
    assert criteria["allow_overlapping_test_windows"] is False
    assert criteria["min_windows"] == 4
    assert nested.DEFAULT_MINIMUM_BARS == 630
    assert holdout.enabled is True
    assert holdout.bars == 252
    assert (datetime.fromisoformat(end) - datetime.fromisoformat(start)).days >= 1824


def test_promotion_metadata_contains_statistical_robustness_and_holdout_evidence():
    metadata = nested._promotion_metadata(
        selection(),
        statistical_evidence(),
        robustness_evidence(),
        holdout_evidence(),
        statistical_criteria=Dumpable(nested._statistical_criteria()),
    )

    assert metadata["validation_profile"] == "nested_walk_forward_v3"
    assert metadata["evidence_version"] == 3
    assert metadata["walk_forward_validation"]["evaluated_windows"] == 4
    assert metadata["statistical_schema_version"] == nested.STATISTICAL_VALIDATION_V2
    assert metadata["statistical_evidence"]["adjusted_p_value"] == 0.01
    assert metadata["robustness_validation"]["scenario_pass_rate"] == 1.0
    assert metadata["sealed_holdout"]["bar_count"] == 252
    assert metadata["sealed_holdout"]["dataset_fingerprint"] == "b" * 64
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
def test_pre_holdout_metadata_fails_closed(nested_evidence, statistical, robustness, expected):
    with pytest.raises(RuntimeError, match=expected):
        nested._pre_holdout_metadata(
            selection(nested_evidence=nested_evidence),
            statistical,
            robustness,
            statistical_criteria=Dumpable(nested._statistical_criteria()),
        )


def test_holdout_failure_blocks_promotion_metadata():
    pre = nested._pre_holdout_metadata(
        selection(),
        statistical_evidence(),
        robustness_evidence(),
        statistical_criteria=Dumpable(nested._statistical_criteria()),
    )

    with pytest.raises(RuntimeError, match="sealed final holdout blocked promotion"):
        nested._attach_holdout_evidence(
            pre,
            holdout_evidence(
                passed=False,
                gates={
                    "bar_count": True,
                    "minimum_trades": False,
                    "minimum_return": True,
                    "minimum_sharpe": True,
                    "maximum_drawdown": True,
                    "exact_strategy": True,
                },
            ),
        )


def configure_runtime(monkeypatch, *, selected, publish, promote=None, events=None):
    provider = FakeProvider()
    events = events if events is not None else []
    monkeypatch.setattr(nested, "AlpacaMarketDataProvider", lambda **kwargs: provider)
    monkeypatch.setattr(
        nested,
        "dataset_fingerprint",
        lambda bars: "a" * 64 if len(next(iter(bars.values()))) == 900 else "d" * 64,
    )
    monkeypatch.setattr(nested, "WalkForwardMultiStrategyRequest", FakeRequest)

    def select(request):
        events.append(("selection", len(request.kwargs["bars"]["AAPL"])))
        return selected

    monkeypatch.setattr(nested, "run_walk_forward_multi_strategy_backtest", select)
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

    def execute(request):
        bar_count = len(request.bars["AAPL"])
        events.append(("execute", bar_count))
        return result

    monkeypatch.setattr(nested, "run_backtest_with_risk", execute)
    monkeypatch.setattr(
        nested,
        "run_statistical_validation",
        lambda *args, **kwargs: statistical_evidence(),
    )

    def robust(request):
        events.append(("robustness", len(request.bars["AAPL"])))
        return robustness_evidence()

    monkeypatch.setattr(nested, "run_promotion_robustness", robust)

    def evaluate(**kwargs):
        events.append(("holdout_evidence", len(kwargs["bars"])))
        return holdout_evidence()

    monkeypatch.setattr(nested, "evaluate_sealed_final_holdout", evaluate)
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


def test_no_eligible_strategy_keeps_holdout_sealed(monkeypatch, tmp_path):
    publish_calls = []
    events = []
    provider = configure_runtime(
        monkeypatch,
        selected=selection(eligible=False),
        publish=lambda **kwargs: publish_calls.append(kwargs),
        events=events,
    )

    output = nested.run_nested_hourly_backtest(
        tmp_path / "reports" / "hourly-backtest-result.json"
    )

    assert output["status"] == "success"
    assert output["data"]["eligible_count"] == 0
    assert output["data"]["ineligible_count"] == 1
    assert output["data"]["no_trade_is_success"] is True
    assert provider.fetch_calls[0]["minimum_bars"] == 882
    assert events == [("selection", 648)]
    assert output["data"]["items"][0]["sealed_holdout"]["status"] == "sealed_not_opened"
    assert publish_calls == []


def test_selection_never_sees_holdout_and_holdout_opens_last(monkeypatch, tmp_path):
    events = []
    monkeypatch.setenv("PUBLISH_TO_DATABASE", "false")
    configure_runtime(
        monkeypatch,
        selected=selection(),
        publish=lambda **kwargs: pytest.fail("publish disabled"),
        events=events,
    )

    output = nested.run_nested_hourly_backtest(
        tmp_path / "reports" / "hourly-backtest-result.json"
    )

    assert output["status"] == "success"
    assert events == [
        ("selection", 648),
        ("execute", 648),
        ("robustness", 648),
        ("execute", 252),
        ("holdout_evidence", 252),
    ]
    assert sum(1 for name, _ in events if name == "selection") == 1
    assert output["data"]["items"][0]["sealed_holdout"]["passed"] is True


def test_eligible_strategy_publishes_only_after_holdout_passes(monkeypatch, tmp_path):
    publish_calls = []
    promotion_calls = []
    events = []

    def publish(**kwargs):
        events.append(("publish", 0))
        publish_calls.append(kwargs)
        return {
            "status": "success",
            "payload": {"run_id": kwargs["run_id"]},
            "database_response": {"status": "success"},
        }

    def promote(*args, **kwargs):
        events.append(("promotion", 0))
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
        events=events,
    )

    output = nested.run_nested_hourly_backtest(
        tmp_path / "reports" / "hourly-backtest-result.json"
    )

    assert output["status"] == "success"
    assert output["data"]["published_count"] == 1
    assert output["data"]["promoted_count"] == 1
    assert events.index(("holdout_evidence", 252)) < events.index(("publish", 0))
    assert events.index(("publish", 0)) < events.index(("promotion", 0))
    item = output["data"]["items"][0]
    assert item["promotion_state"] == "ROBUSTNESS_PASSED"
    metadata = publish_calls[0]["metadata"]
    assert metadata["immutable_evidence_snapshot"] is True
    assert metadata["validation_profile"] == "nested_walk_forward_v3"
    assert metadata["sealed_holdout"]["passed"] is True
    assert metadata["research_dataset_fingerprint"] == "d" * 64
    assert promotion_calls[0]["run_id"] == publish_calls[0]["run_id"]


def test_lifecycle_failure_prevents_false_green(monkeypatch, tmp_path):
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
