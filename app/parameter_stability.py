from __future__ import annotations

from collections import defaultdict
from typing import Any


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def parameter_stability_diagnostics(
    *,
    candidates: list[Any],
    ranked_results: list[Any],
) -> dict[str, Any]:
    """Measure local parameter plateaus without influencing selection.

    A family is observationally stable only when at least two configurations
    have OOS evidence and the family median is positive on return, Sharpe and
    profit factor. This deliberately does not create a promotion gate.
    """
    candidate_by_id = {
        str(candidate.strategy_id): candidate
        for candidate in candidates
        if getattr(candidate, "strategy_id", None)
    }
    families: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in ranked_results:
        strategy_id = str(getattr(result, "strategy_id", ""))
        candidate = candidate_by_id.get(strategy_id)
        if candidate is None:
            continue
        metrics = getattr(result, "metrics", None)
        if metrics is None:
            continue
        families[str(candidate.strategy)].append(
            {
                "strategy_id": strategy_id,
                "fast_window": candidate.fast_window,
                "slow_window": candidate.slow_window,
                "return_pct": metrics.return_pct,
                "sharpe_ratio": metrics.sharpe_ratio,
                "profit_factor": metrics.profit_factor,
                "max_drawdown": metrics.max_drawdown,
                "trade_count": metrics.trade_count,
                "eligible": bool(result.eligible),
            }
        )

    family_rows: dict[str, Any] = {}
    for family, rows in sorted(families.items()):
        returns = [float(row["return_pct"]) for row in rows if row["return_pct"] is not None]
        sharpes = [float(row["sharpe_ratio"]) for row in rows if row["sharpe_ratio"] is not None]
        profit_factors = [
            float(row["profit_factor"]) for row in rows if row["profit_factor"] is not None
        ]
        median_return = _median(returns)
        median_sharpe = _median(sharpes)
        median_profit_factor = _median(profit_factors)
        plateau_observed = (
            len(rows) >= 2
            and median_return is not None
            and median_return > 0
            and median_sharpe is not None
            and median_sharpe > 0
            and median_profit_factor is not None
            and median_profit_factor > 1.0
        )
        family_rows[family] = {
            "configuration_count": len(rows),
            "median_return_pct": median_return,
            "median_sharpe_ratio": median_sharpe,
            "median_profit_factor": median_profit_factor,
            "plateau_observed": plateau_observed,
            "configurations": rows,
        }

    return {
        "schema_version": "parameter-stability-diagnostic.v1",
        "diagnostic_only": True,
        "thresholds_changed": False,
        "used_for_selection": False,
        "promotion_allowed": False,
        "execution_allowed": False,
        "sealed_holdout_opened": False,
        "families": family_rows,
    }
