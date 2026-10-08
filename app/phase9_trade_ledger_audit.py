"""Phase 9: validate supplied point-in-time trade ledger, diagnostic-only.

No trades are inferred from aggregate folds. Incomplete evidence fails closed.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from math import isfinite
from typing import Any

REQUIRED = (
    "trade_id", "entry_timestamp", "exit_timestamp", "gross_pnl",
    "fees", "slippage", "impact", "net_pnl", "position_size",
    "market_regime", "regime_asof_timestamp",
)


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return result if result.tzinfo is not None and result.utcoffset() is not None else None


def phase9_trade_ledger_audit(trades: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Check arithmetic, chronology, and point-in-time regime provenance."""
    rows = trades or []
    errors: Counter[str] = Counter()
    seen: set[str] = set()
    for trade in rows:
        missing = [key for key in REQUIRED if trade.get(key) is None or trade.get(key) == ""]
        if missing:
            errors["missing_required_fields"] += 1
            continue
        trade_id = str(trade["trade_id"])
        if trade_id in seen:
            errors["duplicate_trade_id"] += 1
        seen.add(trade_id)
        entry, exit_, regime_asof = (_timestamp(trade[key]) for key in (
            "entry_timestamp", "exit_timestamp", "regime_asof_timestamp"
        ))
        if not all((entry, exit_, regime_asof)):
            errors["invalid_or_naive_timestamp"] += 1
        elif not (regime_asof <= entry <= exit_):
            errors["point_in_time_or_trade_chronology_violation"] += 1
        numbers = [trade[key] for key in (
            "gross_pnl", "fees", "slippage", "impact", "net_pnl", "position_size"
        )]
        if any(type(value) not in (int, float) or not isfinite(value) for value in numbers):
            errors["invalid_numeric_value"] += 1
            continue
        gross, fees, slippage, impact, net, size = numbers
        if size <= 0 or any(value < 0 for value in (fees, slippage, impact)):
            errors["invalid_cost_or_position"] += 1
        if abs(net - (gross - fees - slippage - impact)) > 1e-6 * max(1, abs(gross)):
            errors["net_pnl_reconciliation_failed"] += 1
    valid = bool(rows) and not errors
    return {
        "schema_version": "phase9-trade-ledger-audit.v1",
        "trade_count": len(rows),
        "evidence_complete": valid,
        "error_counts": dict(sorted(errors.items())),
        "missing_required_evidence": [] if valid else list(REQUIRED),
        "trade_level_causality_verified": False,
        "diagnostic_only": True,
        "thresholds_changed": False,
        "used_for_selection": False,
        "promotion_allowed": False,
        "execution_allowed": False,
        "sealed_holdout_opened": False,
    }
