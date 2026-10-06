from __future__ import annotations

from collections import Counter
from typing import Any


def phase6_nested_oos_failure_attribution(
    *,
    selection: Any,
    parameter_stability: dict[str, Any],
) -> dict[str, Any]:
    """Explain nested-OOS rejection without changing any promotion gate."""
    stable_families = {
        family
        for family, evidence in (parameter_stability.get("families") or {}).items()
        if evidence.get("plateau_observed") is True
    }
    rows: list[dict[str, Any]] = []
    gate_counts: Counter[str] = Counter()
    latest_selection_failures = 0

    for candidate in getattr(selection, "ranked_results", []) or []:
        family = str(getattr(candidate, "strategy", "") or "")
        gates = dict(getattr(candidate, "gates", {}) or {})
        nested_failed = sorted(
            name for name, passed in gates.items()
            if name.startswith("nested_oos_") and passed is False
        )
        latest_passed = gates.get("latest_training_selection")
        if latest_passed is False:
            latest_selection_failures += 1
        for name in nested_failed:
            gate_counts[name] += 1
        walk = getattr(candidate, "walk_forward", None)
        rows.append({
            "strategy_id": getattr(candidate, "strategy_id", None),
            "strategy_family": family,
            "stable_family_observed": family in stable_families,
            "eligible": bool(getattr(candidate, "eligible", False)),
            "nested_failed_gates": nested_failed,
            "latest_training_selection_passed": latest_passed,
            "candidate_oos_profitable_window_rate": getattr(walk, "profitable_window_rate", None),
            "candidate_oos_median_sharpe_ratio": getattr(walk, "median_sharpe_ratio", None),
            "candidate_oos_median_profit_factor": getattr(walk, "median_profit_factor", None),
            "candidate_oos_worst_max_drawdown": getattr(walk, "worst_max_drawdown", None),
            "candidate_oos_evaluated_windows": getattr(walk, "evaluated_windows", None),
            "disqualification_reasons": list(getattr(candidate, "disqualification_reasons", []) or []),
        })

    nested = getattr(selection, "nested_walk_forward", None)
    nested_windows = []
    for window in getattr(nested, "windows", []) or []:
        metrics = getattr(window, "metrics", None)
        nested_windows.append({
            "window": getattr(window, "window", None),
            "decision": getattr(window, "decision", None),
            "selected_strategy_id": getattr(window, "selected_strategy_id", None),
            "train_selection_eligible": getattr(window, "train_selection_eligible", None),
            "capital_deployed": getattr(window, "capital_deployed", None),
            "profitable": getattr(window, "profitable", None),
            "oos_return_pct": getattr(metrics, "return_pct", None) if metrics else None,
            "oos_sharpe_ratio": getattr(metrics, "sharpe_ratio", None) if metrics else None,
            "oos_profit_factor": getattr(metrics, "profit_factor", None) if metrics else None,
            "oos_max_drawdown": getattr(metrics, "max_drawdown", None) if metrics else None,
            "oos_trade_count": getattr(metrics, "trade_count", None) if metrics else None,
        })

    return {
        "schema_version": "phase6-nested-oos-failure-attribution.v1",
        "stable_parameter_families": sorted(stable_families),
        "nested_selection_passed": bool(getattr(nested, "passed", False)) if nested else False,
        "nested_gate_failure_counts": dict(gate_counts.most_common()),
        "latest_training_selection_failure_count": latest_selection_failures,
        "candidate_rows": rows,
        "nested_windows": nested_windows,
        "diagnostic_only": True,
        "thresholds_changed": False,
        "used_for_selection": False,
        "promotion_allowed": False,
        "execution_allowed": False,
        "sealed_holdout_opened": False,
    }
