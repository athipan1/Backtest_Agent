"""V8 preregistration and leakage/authority regression tests."""
from copy import deepcopy

from app.adaptive_research_v8 import build_adaptive_v8_research_plan
from app.research_candidate_profiles import (
    STRATEGY_RESEARCH_V8_PROFILE_ID,
    research_profile,
)
from app.research_trial_registry import (
    build_trial_registry_snapshot,
    statistical_trial_count,
)


def _window(train_end="2026-01-10T16:00:00+00:00", test_start="2026-01-11T16:00:00+00:00"):
    return {"window": 1, "train_end": train_end, "test_start": test_start}


def _feed(label="BULL", available="2026-01-09T15:00:00Z"):
    return {
        "contract_verified": True,
        "status": "checksum_and_contract_valid",
        "historical_source_independently_audited": False,
        "observations": [{
            "symbol": "QTTB", "regime": label,
            "source_observation_id": "archive-record-1",
            "regime_asof_timestamp": "2026-01-09T14:00:00Z",
            "regime_available_at_timestamp": available,
            "dataset_fingerprint": "frozen-archive-v1",
        }],
    }


def _plan(feed, windows=None):
    return build_adaptive_v8_research_plan(
        symbol="QTTB",
        nested_selection={"windows": windows if windows is not None else [_window()]},
        historical_feed=feed,
        research_end="2026-01-31T16:00:00Z",
        cumulative_trials=22,
    )


def test_v8_is_pre_registered_and_preserves_cumulative_trial_budget():
    candidates = research_profile(STRATEGY_RESEARCH_V8_PROFILE_ID)
    ids = [candidate.strategy_id for candidate in candidates]
    assert len(ids) == len(set(ids)) == 8
    assert ids[:4] == [
        "sma-crossover-balanced-v1",
        "trend-following-balanced-v1",
        "mean-reversion-balanced-v1",
        "breakout-balanced-v1",
    ]
    assert statistical_trial_count(STRATEGY_RESEARCH_V8_PROFILE_ID) == 22
    manifest = build_trial_registry_snapshot(
        profile_id=STRATEGY_RESEARCH_V8_PROFILE_ID,
        candidate_ids=ids, dataset_fingerprint="research-only",
    )
    assert len(manifest["new_hypothesis_ids"]) == 4
    assert manifest["statistical_trial_count"] == 22
    assert all(c.fast_window < c.slow_window for c in candidates)
    assert all(c.max_position_pct <= 0.04 for c in candidates[4:])


def test_point_in_time_bull_plan_never_changes_nested_selection_or_broker_auth():
    feed = _feed()
    selection = {"windows": [_window()], "passed": False,
                 "latest_selected_strategy_id": None}
    untouched = deepcopy(selection)
    plan = build_adaptive_v8_research_plan(
        symbol="QTTB", nested_selection=selection,
        historical_feed=feed, research_end="2026-01-31T16:00:00Z",
        cumulative_trials=22,
    )
    assert selection == untouched
    fold = plan["window_plans"][0]
    assert fold["regime"] == "BULL"
    assert "trend-following-30-90-risk-v8" in fold["provisional_hypothesis_ids"]
    assert "breakout-15-55-risk-v8" in fold["provisional_hypothesis_ids"]
    assert "mean-reversion-6-25-risk-v8" not in fold["provisional_hypothesis_ids"]
    assert fold["authoritative_train_selection_changed"] is False
    assert fold["future_oos_used_to_choose_hypotheses"] is False
    assert plan["provider_independently_audited"] is False
    assert plan["regime_driven_strategy_selection_enabled"] is False
    assert plan["promotion_allowed"] is False
    assert plan["execution_allowed"] is False
    assert plan["sealed_holdout_opened"] is False


def test_future_regime_availability_does_not_leak_across_training_boundary():
    feed = _feed(available="2026-01-11T15:00:00Z")
    plan = _plan(feed)
    assert plan["window_plans"][0]["regime"] is None
    assert plan["window_plans"][0]["provisional_hypothesis_ids"] == []
    assert plan["window_plans"][0]["observation"]["reason"] == (
        "no_regime_known_at_training_cutoff"
    )


def test_stale_regime_and_duplicate_availability_abstain():
    stale = _feed(available="2025-12-31T15:00:00Z")
    assert _plan(stale)["window_plans"][0]["observation"]["reason"] == (
        "historical_regime_stale"
    )
    duplicate = _feed()
    second = deepcopy(duplicate["observations"][0])
    second["source_observation_id"] = "ambiguous-record-2"
    duplicate["observations"].append(second)
    assert _plan(duplicate)["window_plans"][0]["observation"]["reason"] == (
        "ambiguous_latest_historical_observation"
    )


def test_bear_and_high_risk_abstain_even_when_feed_claims_audit():
    for label in ("BEAR", "HIGH_RISK", "NO_TRADE"):
        feed = _feed(label)
        feed["historical_source_independently_audited"] = True
        plan = _plan(feed)
        assert plan["window_plans"][0]["decision"] == "CASH_ABSTENTION"
        assert plan["window_plans"][0]["provisional_hypothesis_ids"] == []
        assert plan["execution_allowed"] is False


def test_missing_pit_source_or_invalid_fold_cannot_propose_hypotheses():
    assert _plan({})["window_plans"][0]["provisional_hypothesis_ids"] == []
    assert _plan(_feed(), [_window(test_start="2026-01-08T00:00:00Z")])[
        "window_plans"
    ][0]["provisional_hypothesis_ids"] == []
    assert _plan(_feed(), [_window(test_start="2026-02-01T00:00:00Z")])[
        "window_plans"
    ][0]["provisional_hypothesis_ids"] == []


def test_sideways_only_suggests_reversion_without_promoting():
    fold = _plan(_feed("SIDEWAYS"))["window_plans"][0]
    assert fold["decision"] == "RESEARCH_HYPOTHESIS"
    assert fold["provisional_hypothesis_ids"] == [
        "mean-reversion-balanced-v1", "mean-reversion-6-25-risk-v8"
    ]
    assert fold["paper_execution_authorized"] is False
