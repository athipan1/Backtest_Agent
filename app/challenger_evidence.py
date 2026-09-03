from __future__ import annotations

from typing import Any, Mapping


SCHEMA_VERSION = "backtest-challenger-evidence.v1"


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def build_challenger_evidence(selection: Mapping[str, Any]) -> dict[str, Any]:
    """Build observation-only evidence for the best rejected Backtest candidate.

    This contract is intentionally non-authoritative. It exposes why the best
    candidate missed production gates so Shadow/Performance/Learning can collect
    independent forward evidence without weakening Backtest eligibility.
    """

    payload = _dict(selection)
    best = _dict(payload.get("best_overall"))
    gates = _dict(best.get("gates"))
    failed = sorted(
        name
        for name, passed in gates.items()
        if name.startswith("candidate_oos_") and passed is False
    )
    safety_gate_names = (
        "candidate_oos_kill_switch_safety",
        "candidate_oos_window_count",
        "candidate_oos_worst_max_drawdown",
    )
    safety_passed = bool(best) and all(gates.get(name) is True for name in safety_gate_names)
    quality_passed = bool(best) and all(
        gates.get(name) is True
        for name in (
            "candidate_oos_median_profit_factor",
            "candidate_oos_profitable_window_rate",
        )
    )
    single_sharpe_near_miss = failed == ["candidate_oos_median_sharpe_ratio"]
    observation_candidate = bool(
        best and safety_passed and quality_passed and single_sharpe_near_miss
    )

    candidate_oos = _dict(best.get("candidate_oos"))
    metrics = {
        "median_sharpe_ratio": candidate_oos.get("median_sharpe_ratio"),
        "median_profit_factor": candidate_oos.get("median_profit_factor"),
        "profitable_window_rate": candidate_oos.get("profitable_window_rate"),
        "worst_max_drawdown": candidate_oos.get("worst_max_drawdown"),
        "window_count": candidate_oos.get("evaluated_windows")
        or candidate_oos.get("window_count"),
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "strategy_id": best.get("strategy_id"),
        "strategy_name": best.get("strategy") or best.get("strategy_name"),
        "rank": best.get("rank"),
        "score": best.get("score"),
        "observation_candidate": observation_candidate,
        "failed_candidate_oos_gates": failed,
        "candidate_oos_metrics": metrics,
        "disqualification_reasons": list(best.get("disqualification_reasons") or []),
        "safety": {
            "safety_gates_passed": safety_passed,
            "quality_gates_passed": quality_passed,
            "production_eligible": False,
            "risk_execution_authorized": False,
            "broker_order_authorized": False,
            "thresholds_relaxed": False,
            "requires_independent_forward_evidence": True,
        },
    }
