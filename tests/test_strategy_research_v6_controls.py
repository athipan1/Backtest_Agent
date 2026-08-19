from __future__ import annotations

from types import SimpleNamespace

import pytest

from app import hourly_promotion_runner as promotion
from app.pre_holdout_research import (
    _candidate_return_series,
    _cost_stress_multipliers,
    _pbo_criteria_from_env,
    _run_cost_stress,
)
from app.research_overfit import PBOCriteria, run_cscv_pbo
from app.research_trial_registry import build_trial_registry_snapshot, registered_trial_ids


class FakeRequest:
    def __init__(
        self,
        *,
        fee_bps: float = 1.0,
        slippage_bps: float = 5.0,
        market_impact_bps: float = 2.0,
        force_close_at_end: bool = False,
    ) -> None:
        self.fee_bps = fee_bps
        self.slippage_bps = slippage_bps
        self.market_impact_bps = market_impact_bps
        self.force_close_at_end = force_close_at_end

    def model_copy(self, *, deep=True, update=None):
        values = {
            "fee_bps": self.fee_bps,
            "slippage_bps": self.slippage_bps,
            "market_impact_bps": self.market_impact_bps,
            "force_close_at_end": self.force_close_at_end,
        }
        values.update(update or {})
        return FakeRequest(**values)


def test_pbo_criteria_reads_fail_closed_environment(monkeypatch):
    monkeypatch.setenv("BACKTEST_RESEARCH_PBO_SLICES", "6")
    monkeypatch.setenv("BACKTEST_RESEARCH_PBO_MIN_OBSERVATIONS_PER_SLICE", "12")
    monkeypatch.setenv("BACKTEST_RESEARCH_MAX_PBO", "0.15")

    criteria = _pbo_criteria_from_env()
    assert criteria.slice_count == 6
    assert criteria.min_observations_per_slice == 12
    assert criteria.max_probability_of_backtest_overfit == 0.15


def test_pbo_criteria_rejects_odd_slice_count():
    with pytest.raises(ValueError, match="must be even"):
        PBOCriteria(slice_count=5)


def test_pbo_can_be_explicitly_disabled_for_legacy_analysis():
    result = run_cscv_pbo(
        {"a": [0.01] * 20, "b": [0.0] * 20},
        criteria=PBOCriteria(enabled=False),
    )
    assert result.status == "disabled"
    assert result.passed is True


def test_pbo_requires_multiple_candidates():
    result = run_cscv_pbo(
        {"only": [0.01] * 100},
        criteria=PBOCriteria(),
    )
    assert result.status == "insufficient_data"
    assert result.passed is False
    assert "at least two" in result.reasons[0]


def test_candidate_return_series_runs_each_explicit_candidate(monkeypatch):
    request = SimpleNamespace(
        candidates=[SimpleNamespace(strategy_id="a"), SimpleNamespace(strategy_id="b")]
    )
    calls = []
    monkeypatch.setattr(promotion, "build_run_request", lambda candidate, request: FakeRequest())
    monkeypatch.setattr(
        promotion,
        "run_backtest_with_risk",
        lambda request: calls.append(request) or SimpleNamespace(),
    )
    monkeypatch.setattr(
        "app.pre_holdout_research.equity_returns",
        lambda result: [0.01, 0.02],
    )

    series = _candidate_return_series(request)
    assert series == {"a": [0.01, 0.02], "b": [0.01, 0.02]}
    assert len(calls) == 2
    assert all(call.force_close_at_end is True for call in calls)


def test_candidate_return_series_refuses_implicit_identity(monkeypatch):
    request = SimpleNamespace(candidates=[SimpleNamespace(strategy_id=None)])
    with pytest.raises(RuntimeError, match="explicit candidate strategy_id"):
        _candidate_return_series(request)


def test_cost_stress_multiplier_parser_is_deterministic(monkeypatch):
    monkeypatch.setenv("BACKTEST_RESEARCH_COST_STRESS_MULTIPLIERS", "2,1,1.5,1")
    assert _cost_stress_multipliers() == (1.0, 1.5, 2.0)


def test_cost_stress_multiplier_parser_rejects_non_positive(monkeypatch):
    monkeypatch.setenv("BACKTEST_RESEARCH_COST_STRESS_MULTIPLIERS", "1,0")
    with pytest.raises(RuntimeError, match="positive values"):
        _cost_stress_multipliers()


def test_cost_stress_passes_only_when_every_scenario_preserves_net_edge(monkeypatch):
    monkeypatch.setenv("BACKTEST_RESEARCH_COST_STRESS_MULTIPLIERS", "1,2")
    monkeypatch.setattr(promotion, "build_run_request", lambda candidate, request: FakeRequest())
    monkeypatch.setattr(
        promotion,
        "run_backtest_with_risk",
        lambda request: SimpleNamespace(
            metrics=SimpleNamespace(return_pct=0.02, profit_factor=1.2, trade_count=20)
        ),
    )
    request = SimpleNamespace(statistical_criteria=SimpleNamespace(min_trades=10))

    evidence = _run_cost_stress(SimpleNamespace(), request)
    assert evidence["passed"] is True
    assert [row["multiplier"] for row in evidence["scenarios"]] == [1.0, 2.0]
    assert evidence["scenarios"][-1]["slippage_bps"] == 10.0


def test_cost_stress_fails_when_high_cost_scenario_loses_edge(monkeypatch):
    monkeypatch.setenv("BACKTEST_RESEARCH_COST_STRESS_MULTIPLIERS", "1,2")
    monkeypatch.setattr(promotion, "build_run_request", lambda candidate, request: FakeRequest())

    def fake_run(request):
        losing = request.slippage_bps >= 10.0
        return SimpleNamespace(
            metrics=SimpleNamespace(
                return_pct=-0.01 if losing else 0.02,
                profit_factor=0.8 if losing else 1.2,
                trade_count=20,
            )
        )

    monkeypatch.setattr(promotion, "run_backtest_with_risk", fake_run)
    request = SimpleNamespace(statistical_criteria=SimpleNamespace(min_trades=10))

    evidence = _run_cost_stress(SimpleNamespace(), request)
    assert evidence["passed"] is False
    assert evidence["scenarios"][0]["passed"] is True
    assert evidence["scenarios"][1]["passed"] is False
    assert evidence["reasons"]


def test_trial_registry_rejects_duplicate_and_incomplete_v6_declarations():
    with pytest.raises(RuntimeError, match="duplicate candidate"):
        build_trial_registry_snapshot(
            profile_id="strategy_research_v6",
            candidate_ids=["trend-following-30-120-risk-v6"] * 2,
            dataset_fingerprint="abc",
        )

    with pytest.raises(RuntimeError, match="missing preregistered"):
        build_trial_registry_snapshot(
            profile_id="strategy_research_v6",
            candidate_ids=[
                "sma-crossover-balanced-v1",
                "trend-following-30-120-risk-v6",
            ],
            dataset_fingerprint="abc",
        )


def test_trial_registry_rejects_unknown_profile():
    with pytest.raises(ValueError, match="not registered"):
        registered_trial_ids("strategy_research_v999")
