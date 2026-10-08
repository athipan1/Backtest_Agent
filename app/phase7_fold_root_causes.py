"""Phase 7: diagnostic-only root-cause attribution of nested OOS folds.

Consumes the sealed Phase 6 diagnostic payload; never changes selection authority.
"""
from __future__ import annotations

from collections import Counter
from typing import Any


def phase7_fold_root_causes(phase6: dict[str, Any]) -> dict[str, Any]:
    """Classify observed failure modes without inventing missing trade-level evidence."""
    rows = phase6.get("candidate_rows") or []
    windows = phase6.get("nested_windows") or []
    gate_counts: Counter[str] = Counter()
    for row in rows:
        gate_counts.update(row.get("nested_failed_gates") or [])

    fold_rows: list[dict[str, Any]] = []
    for window in windows:
        trade_count = window.get("oos_trade_count")
        sharpe = window.get("oos_sharpe_ratio")
        profit_factor = window.get("oos_profit_factor")
        result = window.get("oos_return_pct")
        flags = []
        if window.get("train_selection_eligible") is False:
            flags.append("training_selection_ineligible")
        if window.get("capital_deployed") is False:
            flags.append("no_capital_deployed")
        if isinstance(trade_count, (int, float)) and trade_count == 0:
            flags.append("zero_trades")
        if isinstance(sharpe, (int, float)) and sharpe < 0:
            flags.append("negative_oos_sharpe")
        if isinstance(profit_factor, (int, float)) and profit_factor < 1:
            flags.append("profit_factor_below_one")
        if isinstance(result, (int, float)) and result < 0:
            flags.append("negative_oos_return")
        fold_rows.append({
            "window": window.get("window"),
            "selected_strategy_id": window.get("selected_strategy_id"),
            "decision": window.get("decision"),
            "oos_trade_count": trade_count,
            "oos_return_pct": result,
            "oos_sharpe_ratio": sharpe,
            "oos_profit_factor": profit_factor,
            "observed_flags": flags,
        })

    missing_trade_level = True
    return {
        "schema_version": "phase7-fold-root-cause.v1",
        "nested_gate_failure_counts": dict(sorted(gate_counts.items())),
        "fold_rows": fold_rows,
        "candidate_count": len(rows),
        "fold_count": len(fold_rows),
        "trade_level_causality_verified": not missing_trade_level,
        "unverified_hypotheses": [
            "signal_timing", "exit_logic", "position_sizing",
            "market_regime_dependence", "gross_vs_net_cost_impact",
        ],
        "diagnostic_only": True,
        "thresholds_changed": False,
        "used_for_selection": False,
        "promotion_allowed": False,
        "execution_allowed": False,
        "sealed_holdout_opened": False,
    }
