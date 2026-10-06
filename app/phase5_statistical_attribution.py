from __future__ import annotations

from typing import Any


def _check(value: Any, *, minimum: float | None = None, maximum: float | None = None) -> bool | None:
    if value is None:
        return None
    numeric = float(value)
    if minimum is not None:
        return numeric >= minimum
    if maximum is not None:
        return numeric <= maximum
    return None


def phase5_statistical_failure_attribution(
    *,
    parameter_stability: dict[str, Any],
    statistical_evidence: dict[str, Any] | None,
    selected_strategy_id: str | None,
) -> dict[str, Any]:
    """Attribute statistical blockers only after a stable parameter family is observed.

    This is evidence-only. It cannot alter selection, thresholds, promotion,
    execution, or sealed-holdout authority.
    """
    stable_families = sorted(
        family
        for family, evidence in (parameter_stability.get("families") or {}).items()
        if evidence.get("plateau_observed") is True
    )
    evidence = statistical_evidence or {}
    criteria = evidence.get("criteria") or {}
    checks: dict[str, Any] = {}

    mappings = (
        ("adjusted_p_value", "adjusted_p_value", None, "max_adjusted_p_value"),
        ("probabilistic_sharpe_ratio", "probabilistic_sharpe_ratio", "min_probabilistic_sharpe_ratio", None),
        ("deflated_sharpe_ratio", "deflated_sharpe_ratio", "min_deflated_sharpe_ratio", None),
        ("bootstrap_lower_bound", "bootstrap_lower_bound", "min_bootstrap_lower_bound", None),
        ("block_bootstrap_lower_bound", "block_bootstrap_lower_bound", "min_block_bootstrap_lower_bound", None),
        ("hac_positive_probability", "hac_positive_probability", "min_hac_positive_probability", None),
    )
    for name, field, minimum_key, maximum_key in mappings:
        value = evidence.get(field)
        minimum = criteria.get(minimum_key) if minimum_key else None
        maximum = criteria.get(maximum_key) if maximum_key else None
        passed = _check(value, minimum=minimum, maximum=maximum)
        checks[name] = {
            "value": value,
            "minimum": minimum,
            "maximum": maximum,
            "passed": passed,
        }

    failed_checks = sorted(name for name, check in checks.items() if check["passed"] is False)
    return {
        "schema_version": "phase5-stability-statistical-attribution.v1",
        "selected_strategy_id": selected_strategy_id,
        "stable_parameter_families": stable_families,
        "stable_family_observed": bool(stable_families),
        "statistical_evidence_present": bool(statistical_evidence),
        "checks": checks,
        "failed_checks": failed_checks,
        "diagnostic_only": True,
        "thresholds_changed": False,
        "used_for_selection": False,
        "promotion_allowed": False,
        "execution_allowed": False,
        "sealed_holdout_opened": False,
    }
