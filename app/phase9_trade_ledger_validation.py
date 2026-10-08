"""Phase 9: fail-closed, read-only validation of externally supplied research trade ledgers.

No order placement, promotion, strategy selection, or sealed-holdout evaluation.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Any

REQUIRED_FIELDS = (
    "strategy_id", "fold_id", "entry_time", "exit_time", "quantity",
    "gross_pnl", "fees", "slippage", "impact", "net_pnl", "market_regime",
)


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def phase9_trade_ledger_validation(
    phase8: dict[str, Any], trades: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Audit real trade evidence; never synthesize transactions from fold aggregates."""
    trades = trades or []
    invalid: list[dict[str, Any]] = []
    valid_count = 0
    for index, trade in enumerate(trades):
        errors = [f"missing:{field}" for field in REQUIRED_FIELDS
                  if trade.get(field) is None or trade.get(field) == ""]
        entry = _timestamp(trade.get("entry_time"))
        exit_ = _timestamp(trade.get("exit_time"))
        if entry is None or exit_ is None or (entry is not None and exit_ is not None and exit_ <= entry):
            errors.append("invalid_timestamp_order_or_timezone")
        numeric = ("quantity", "gross_pnl", "fees", "slippage", "impact", "net_pnl")
        for field in numeric:
            value = trade.get(field)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not isfinite(value):
                errors.append(f"invalid_numeric:{field}")
        if not errors:
            if trade["quantity"] <= 0 or any(trade[field] < 0 for field in ("fees", "slippage", "impact")):
                errors.append("invalid_quantity_or_cost")
            elif abs(trade["gross_pnl"] - trade["fees"] - trade["slippage"] - trade["impact"] - trade["net_pnl"]) > 1e-6:
                errors.append("pnl_reconciliation_failed")
        if errors:
            invalid.append({"trade_index": index, "errors": sorted(set(errors))})
        else:
            valid_count += 1
    return {
        "schema_version": "phase9-trade-ledger-validation.v1",
        "phase8_fold_count": phase8.get("fold_count", 0),
        "supplied_trade_count": len(trades),
        "valid_trade_count": valid_count,
        "invalid_trades": invalid,
        "trade_level_evidence_complete": bool(trades) and not invalid,
        "fold_coverage_verified": False,
        "point_in_time_regime_verified": False,
        "causal_conclusions_supported": False,
        "diagnostic_only": True,
        "thresholds_changed": False,
        "used_for_selection": False,
        "promotion_allowed": False,
        "execution_allowed": False,
        "sealed_holdout_opened": False,
    }
