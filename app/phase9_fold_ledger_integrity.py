"""Fail-closed diagnostic linkage of supplied trades to explicit OOS fold boundaries."""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

from app.phase9_trade_ledger_audit import phase9_trade_ledger_audit


def _dt(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None
    except ValueError:
        return None


def phase9_fold_ledger_integrity(
    trades: list[dict[str, Any]] | None,
    folds: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Validate exact fold/strategy join and OOS timestamp membership.

    Requires explicit timezone-aware oos_start/oos_end and fold_id. Does not
    infer boundaries from a window index or derive trades from aggregate metrics.
    """
    ledger = phase9_trade_ledger_audit(trades)
    errors: Counter[str] = Counter()
    fold_map: dict[str, dict[str, Any]] = {}
    for fold in folds or []:
        key = fold.get("fold_id")
        if key is None or str(key) == "":
            errors["fold_id_missing"] += 1
            continue
        key = str(key)
        if key in fold_map:
            errors["duplicate_fold_id"] += 1
        fold_map[key] = fold
        start, end = _dt(fold.get("oos_start")), _dt(fold.get("oos_end"))
        if start is None or end is None or start >= end:
            errors["invalid_fold_boundaries"] += 1
    for trade in trades or []:
        key = trade.get("fold_id")
        if key is None or str(key) not in fold_map:
            errors["unmatched_trade_fold"] += 1
            continue
        fold = fold_map[str(key)]
        entry, exit_ = _dt(trade.get("entry_timestamp")), _dt(trade.get("exit_timestamp"))
        start, end = _dt(fold.get("oos_start")), _dt(fold.get("oos_end"))
        if None in (entry, exit_, start, end):
            errors["unverifiable_trade_window"] += 1
        elif not (start <= entry <= exit_ <= end):
            errors["trade_outside_oos_window"] += 1
        if not trade.get("strategy_id") or not fold.get("selected_strategy_id"):
            errors["strategy_join_missing"] += 1
        elif str(trade["strategy_id"]) != str(fold["selected_strategy_id"]):
            errors["strategy_mismatch"] += 1
    # Absence of a ledger is never interpreted as proof of zero trades.
    if not trades:
        errors["trade_ledger_unavailable"] += 1
    if not folds:
        errors["fold_boundaries_unavailable"] += 1
    return {
        "schema_version": "phase9-fold-ledger-integrity.v1",
        "ledger": ledger,
        "fold_count": len(folds or []),
        "trade_count": len(trades or []),
        "join_verified": bool(trades) and bool(folds) and ledger["evidence_complete"] and not errors,
        "error_counts": dict(sorted(errors.items())),
        "diagnostic_only": True,
        "thresholds_changed": False,
        "used_for_selection": False,
        "promotion_allowed": False,
        "execution_allowed": False,
        "sealed_holdout_opened": False,
    }
