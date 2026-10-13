"""Research-only point-in-time regime planning for Strategy v8.

This planner does not run or alter a Backtest, filter nested validation
candidates, grant promotion, or touch the sealed holdout. It deliberately
abstains unless a checksum-validated, uniquely time-joined historical
observation was available by the TRAIN end of each historical fold.
Independent provider authenticity remains a separate required attestation.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Mapping

from app.research_candidate_profiles import strategy_research_v8_candidates

SCHEMA_VERSION = "adaptive-research-v8-plan.v1"
MAX_OBSERVATION_AGE = timedelta(days=7)
REGIME_FAMILIES: dict[str, tuple[str, ...]] = {
    "BULL": ("trend_following", "sma_crossover", "breakout"),
    "UPTREND": ("trend_following", "sma_crossover", "breakout"),
    "SIDEWAYS": ("mean_reversion",),
    "RANGE": ("mean_reversion",),
    "BEAR": (),
    "HIGH_RISK": (),
    "NO_TRADE": (),
}
CONTROL_IDS = frozenset(
    candidate.strategy_id for candidate in strategy_research_v8_candidates()[:4]
)


def _time(raw: Any) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        result = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return result if result.tzinfo is not None and result.utcoffset() is not None else None


def _observed_regime(
    feed: Mapping[str, Any], symbol: str, train_end: datetime
) -> tuple[str | None, dict[str, Any]]:
    if feed.get("contract_verified") is not True:
        return None, {"reason": "checksum_pit_feed_unverified"}
    matches: list[tuple[datetime, datetime, dict[str, Any]]] = []
    for row in feed.get("observations") or []:
        if not isinstance(row, dict) or row.get("symbol") != symbol:
            continue
        available = _time(row.get("regime_available_at_timestamp"))
        asof = _time(row.get("regime_asof_timestamp"))
        if available is None or asof is None or asof > available:
            return None, {"reason": "invalid_historical_availability"}
        if available <= train_end:
            matches.append((available, asof, row))
    if not matches:
        return None, {"reason": "no_regime_known_at_training_cutoff"}
    matches.sort(key=lambda value: (value[0], value[1]))
    latest = matches[-1][0]
    if sum(item[0] == latest for item in matches) != 1:
        return None, {"reason": "ambiguous_latest_historical_observation"}
    if train_end - latest > MAX_OBSERVATION_AGE:
        return None, {"reason": "historical_regime_stale"}
    row = matches[-1][2]
    label = str(row.get("regime") or "").upper().strip()
    if label not in REGIME_FAMILIES:
        return None, {"reason": "unsupported_historical_regime"}
    return label, {
        "reason": "point_in_time_observation_only",
        "available_at": row["regime_available_at_timestamp"],
        "asof": row["regime_asof_timestamp"],
        "observation_id": row.get("source_observation_id"),
        "dataset_fingerprint": row.get("dataset_fingerprint"),
    }


def build_adaptive_v8_research_plan(
    *,
    symbol: str,
    nested_selection: Any,
    historical_feed: Mapping[str, Any] | None,
    research_end: str,
    cumulative_trials: int,
) -> dict[str, Any]:
    """Make non-binding per-fold strategy-family research hypotheses.

    The selection used to calculate existing nested-OOS results is NEVER
    modified; the plan is written afterwards and is not fed back to selection.
    """
    feed = historical_feed if isinstance(historical_feed, Mapping) else {}
    nested = (
        nested_selection.model_dump(mode="json")
        if hasattr(nested_selection, "model_dump")
        else dict(nested_selection or {})
    )
    windows = nested.get("windows") or []
    candidates = strategy_research_v8_candidates()
    cutoff = _time(research_end)
    plans: list[dict[str, Any]] = []
    for window in windows:
        fold = window if isinstance(window, dict) else {}
        train_end = _time(fold.get("train_end"))
        test_start = _time(fold.get("test_start"))
        eligible_time = (
            cutoff is not None and train_end is not None
            and test_start is not None and train_end < test_start
            and train_end <= cutoff and test_start <= cutoff
        )
        label, observation = (
            _observed_regime(feed, symbol.upper(), train_end)
            if eligible_time else (None, {"reason": "fold_timing_unverified"})
        )
        families = REGIME_FAMILIES.get(label, ())
        proposed = [
            candidate.strategy_id for candidate in candidates
            if candidate.strategy in families
        ] if label is not None else []
        plans.append({
            "fold": fold.get("window"),
            "train_end": fold.get("train_end"),
            "test_start": fold.get("test_start"),
            "regime": label,
            "observation": observation,
            "provisional_hypothesis_ids": proposed,
            "control_ids": sorted(CONTROL_IDS),
            "decision": "CASH_ABSTENTION" if label in {"BEAR", "HIGH_RISK", "NO_TRADE"} else (
                "RESEARCH_HYPOTHESIS" if proposed else "NO_VERIFIED_REGIME"
            ),
            "authoritative_train_selection_changed": False,
            "future_oos_used_to_choose_hypotheses": False,
            "paper_execution_authorized": False,
        })
    return {
        "schema_version": SCHEMA_VERSION,
        "symbol": symbol.upper(),
        "mode": "post_hoc_preholdout_diagnostic_only",
        "historical_feed_status": feed.get("status", "not_configured"),
        "historical_feed_contract_verified": feed.get("contract_verified") is True,
        "provider_independently_audited": feed.get(
            "historical_source_independently_audited"
        ) is True,
        "regime_driven_strategy_selection_enabled": False,
        "required_external_attestation_missing": feed.get(
            "historical_source_independently_audited"
        ) is not True,
        "cumulative_statistical_trials": cumulative_trials,
        "planned_cost_stress_multipliers": [1.0, 1.5, 2.0],
        "cost_stress_reexecuted_by_this_planner": False,
        "window_plans": plans,
        "observation_only": True,
        "candidate_policy_changed": False,
        "promotion_allowed": False,
        "execution_allowed": False,
        "sealed_holdout_opened": False,
    }
