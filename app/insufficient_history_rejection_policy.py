from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


POLICY_SCHEMA = "insufficient-history-rejection-policy.v1"
REJECTION_STAGE = "historical_data"

# These patterns intentionally match only deterministic data-sufficiency failures.
# Network/API/auth failures, malformed bars, contract errors, publishing failures,
# and all other exceptions remain operational failures and keep the workflow red.
_INSUFFICIENT_HISTORY_PATTERNS = (
    re.compile(
        r"^[A-Z0-9][A-Z0-9.-]{0,19} returned (?P<observed>\d+) bars; "
        r"at least (?P<required>\d+) are required$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^Need at least (?P<required>\d+) bars for nested walk-forward promotion; "
        r"received (?P<observed>\d+)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^insufficient history for sealed final holdout: "
        r"observed=(?P<observed>\d+), required=(?P<required>\d+), "
        r"research=\d+, holdout=\d+$",
        re.IGNORECASE,
    ),
)


def _history_counts(error: str) -> tuple[int, int] | None:
    normalized = str(error or "").strip()
    for pattern in _INSUFFICIENT_HISTORY_PATTERNS:
        match = pattern.fullmatch(normalized)
        if match is None:
            continue
        observed = int(match.group("observed"))
        required = int(match.group("required"))
        if observed >= required:
            return None
        return observed, required
    return None


def _rewrite_reports(report_path: Path, output: dict[str, Any]) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(output, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    data = output.get("data")
    if not isinstance(data, dict):
        return
    for item in data.get("items") or []:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "unknown").lower()
        safe_symbol = re.sub(r"[^a-z0-9]+", "-", symbol).strip("-") or "unknown"
        (report_path.parent / f"hourly-backtest-{safe_symbol}.json").write_text(
            json.dumps(item, indent=2, sort_keys=True),
            encoding="utf-8",
        )


def _refresh_summary(output: dict[str, Any]) -> None:
    data = output.get("data")
    if not isinstance(data, dict):
        return
    items = data.get("items")
    if not isinstance(items, list):
        return

    eligible = [
        item.get("symbol")
        for item in items
        if isinstance(item, dict) and item.get("status") == "eligible_strategy_found"
    ]
    ineligible = [
        item.get("symbol")
        for item in items
        if isinstance(item, dict) and item.get("status") == "no_eligible_strategy"
    ]
    failed = [
        item.get("symbol")
        for item in items
        if isinstance(item, dict) and item.get("status") == "failed"
    ]
    published_count = sum(
        1 for item in items if isinstance(item, dict) and item.get("published") is True
    )
    promoted_count = sum(
        1 for item in items if isinstance(item, dict) and item.get("promoted") is True
    )
    publish_required = data.get("promotion_lifecycle_required") is True
    all_succeeded = not failed
    all_eligible_published = published_count == len(eligible)
    all_eligible_promoted = promoted_count == len(eligible) if publish_required else True
    publication_complete = (
        all_succeeded and all_eligible_published and all_eligible_promoted
    )

    data.update(
        {
            "eligible_symbols": eligible,
            "ineligible_symbols": ineligible,
            "failed_symbols": failed,
            "eligible_count": len(eligible),
            "ineligible_count": len(ineligible),
            "published_count": published_count,
            "promoted_count": promoted_count,
            "published": publication_complete,
            "publish_status": (
                "success"
                if publication_complete
                else "partial_failure"
                if eligible or ineligible
                else "failed"
            ),
            "all_succeeded": all_succeeded,
            "selection_complete": all_succeeded,
            "no_trade_is_success": True,
        }
    )
    output["status"] = "success" if all_succeeded else "error"
    output["error"] = (
        None
        if all_succeeded
        else "One or more nested walk-forward Backtests failed operationally."
    )


def _reclassify_insufficient_history(output: dict[str, Any]) -> bool:
    data = output.get("data")
    if not isinstance(data, dict):
        return False
    items = data.get("items")
    if not isinstance(items, list):
        return False

    changed = False
    for item in items:
        if not isinstance(item, dict) or item.get("status") != "failed":
            continue
        if item.get("published") is True or item.get("promoted") is True:
            continue
        reason = str(item.get("error") or "").strip()
        counts = _history_counts(reason)
        if counts is None:
            continue
        observed, required = counts
        item.update(
            {
                "status": "no_eligible_strategy",
                "selected_strategy_id": None,
                "published": False,
                "promoted": False,
                "publish_status": "skipped",
                "selection": None,
                "sealed_holdout": {
                    "enabled": True,
                    "status": "sealed_not_opened",
                },
                "rejection_stage": REJECTION_STAGE,
                "rejection_reason": reason,
                "rejection_code": "insufficient_history",
                "history_bars_observed": observed,
                "history_bars_required": required,
                "error": None,
            }
        )
        changed = True

    if changed:
        _refresh_summary(output)
    return changed


def apply_insufficient_history_rejection_policy(runner_module: Any) -> dict[str, Any]:
    """Convert only deterministic insufficient-history failures into NO_TRADE.

    The adapter is deliberately narrow. Every non-history operational error remains
    a failed symbol, preserving fail-closed behavior for market-data outages,
    malformed evidence, contract drift, Database failures, and promotion failures.
    """

    if getattr(runner_module, "_INSUFFICIENT_HISTORY_POLICY_INSTALLED", False):
        return {
            "schema_version": POLICY_SCHEMA,
            "installed": True,
            "fail_closed": True,
        }

    original_hourly = runner_module.run_nested_hourly_backtest

    def run_hourly_with_history_rejection(report_path: Path) -> dict[str, Any]:
        output = original_hourly(report_path)
        if _reclassify_insufficient_history(output):
            _rewrite_reports(report_path, output)
        return output

    runner_module.run_nested_hourly_backtest = run_hourly_with_history_rejection
    runner_module._INSUFFICIENT_HISTORY_POLICY_INSTALLED = True
    runner_module.INSUFFICIENT_HISTORY_REJECTION_POLICY = {
        "schema_version": POLICY_SCHEMA,
        "installed": True,
        "rejection_code": "insufficient_history",
        "outcome": "NO_TRADE",
        "fail_closed": True,
    }
    return dict(runner_module.INSUFFICIENT_HISTORY_REJECTION_POLICY)
