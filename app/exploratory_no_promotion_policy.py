from __future__ import annotations

from typing import Any, Mapping

EXPLORATORY_BUCKET = "exploratory"
POLICY_SCHEMA = "exploratory-no-promotion.v1"
BLOCK_REASON = "exploratory_research_only_no_production_promotion"


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def apply_exploratory_no_promotion_policy(runner_module: Any) -> dict[str, Any]:
    """Make exploratory Backtests observation-only even when metrics look strong.

    The exploratory bucket exists to discover which strategy family/configuration
    deserves independent forward evidence. It must never become a shortcut around
    Manager's production classifier. Ranked metrics remain visible for research,
    while selected production output is removed before the hourly trade gate.
    """

    original_select = runner_module.run_walk_forward_multi_strategy_backtest

    def observation_only_select(request: Any):
        result = original_select(request)
        symbols = getattr(request, "symbols", None)
        symbol = str(symbols[0] if symbols else "").strip().upper()
        policy = _mapping(
            getattr(runner_module, "STRATEGY_BUCKET_CANDIDATE_POLICY", {})
        )
        symbol_buckets = _mapping(policy.get("symbol_buckets"))
        if str(symbol_buckets.get(symbol) or "").strip().lower() != EXPLORATORY_BUCKET:
            return result

        ranked = []
        for item in list(getattr(result, "ranked_results", []) or []):
            gates = dict(getattr(item, "gates", {}) or {})
            gates["production_classification"] = False
            reasons = list(getattr(item, "disqualification_reasons", []) or [])
            if BLOCK_REASON not in reasons:
                reasons.append(BLOCK_REASON)
            ranked.append(
                item.model_copy(
                    update={
                        "eligible": False,
                        "gates": gates,
                        "disqualification_reasons": reasons,
                    }
                )
            )

        warnings = list(getattr(result, "warnings", []) or [])
        if BLOCK_REASON not in warnings:
            warnings.append(BLOCK_REASON)
        best_overall = ranked[0] if ranked else getattr(result, "best_overall", None)
        return result.model_copy(
            update={
                "selection_status": "no_eligible_strategy",
                "eligible_count": 0,
                "ranked_results": ranked,
                "best_overall": best_overall,
                "best_eligible": None,
                "selected_result": None,
                "warnings": warnings,
            }
        )

    runner_module.run_walk_forward_multi_strategy_backtest = observation_only_select
    policy = {
        "schema_version": POLICY_SCHEMA,
        "bucket": EXPLORATORY_BUCKET,
        "observation_only": True,
        "production_promotion_authorized": False,
        "risk_execution_authorized": False,
        "broker_order_authorized": False,
        "thresholds_relaxed": False,
    }
    setattr(runner_module, "EXPLORATORY_NO_PROMOTION_POLICY", policy)
    return policy
