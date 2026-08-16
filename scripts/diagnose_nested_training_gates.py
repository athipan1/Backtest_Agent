from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from app.models import BacktestMetrics
from app.multi_strategy import StrategySelectionCriteria, evaluate_selection_gates

SCHEMA_VERSION = "nested-training-gate-diagnostics.v1"


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def load_console_payload(path: Path) -> dict[str, Any]:
    """Load either a plain JSON result or Manager's event-line + JSON console file."""

    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        raise ValueError("Backtest console is empty")
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("Backtest console JSON root must be an object")
        return payload
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        _, offset = decoder.raw_decode(raw)
        remainder = raw[offset:].lstrip()
        if not remainder:
            raise ValueError("Backtest console contains no result payload")
        payload = json.loads(remainder)
        if not isinstance(payload, dict):
            raise ValueError("Backtest result JSON root must be an object")
        return payload


def _metric_value(metrics: dict[str, Any], name: str) -> float | int | None:
    value = metrics.get(name)
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _candidate_sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
    metrics = _dict(row.get("train_metrics"))
    return (
        len(_list(row.get("failed_performance_gates"))),
        -float(_metric_value(metrics, "annualized_return") or -999.0),
        -float(_metric_value(metrics, "sharpe_ratio") or -999.0),
        -float(_metric_value(metrics, "profit_factor") or -999.0),
        -int(_metric_value(metrics, "trade_count") or 0),
        str(row.get("strategy_id") or ""),
    )


def _candidate_window_diagnostic(
    *,
    strategy_id: str,
    strategy_name: str,
    window: dict[str, Any],
    criteria: StrategySelectionCriteria,
) -> dict[str, Any]:
    raw_metrics = _dict(window.get("train_metrics"))
    metrics = BacktestMetrics.model_validate(raw_metrics)
    gates, reasons = evaluate_selection_gates(metrics, criteria)
    failed = [name for name, passed in gates.items() if not passed]
    return {
        "strategy_id": strategy_id,
        "strategy_name": strategy_name,
        "performance_gate_eligible": not failed,
        "failed_performance_gates": failed,
        "performance_gate_reasons": reasons,
        "performance_gates": gates,
        "train_metrics": {
            "trade_count": metrics.trade_count,
            "annualized_return": metrics.annualized_return,
            "sharpe_ratio": metrics.sharpe_ratio,
            "profit_factor": metrics.profit_factor,
            "max_drawdown": metrics.max_drawdown,
            "excess_return_pct": metrics.excess_return_pct,
            "kill_switch_events": metrics.kill_switch_events,
        },
    }


def diagnose_selection(selection: dict[str, Any]) -> dict[str, Any]:
    symbol = str(selection.get("symbol") or "").upper()
    criteria = StrategySelectionCriteria.model_validate(
        _dict(selection.get("selection_criteria"))
    )
    nested = _dict(selection.get("nested_walk_forward"))
    nested_windows = {
        int(row.get("window")): row
        for row in _list(nested.get("windows"))
        if isinstance(row, dict) and row.get("window") is not None
    }

    candidate_windows: dict[int, list[dict[str, Any]]] = {}
    for ranked in _list(selection.get("ranked_results")):
        if not isinstance(ranked, dict):
            continue
        strategy_id = str(ranked.get("strategy_id") or "")
        strategy_name = str(ranked.get("name") or strategy_id)
        walk_forward = _dict(ranked.get("walk_forward"))
        for window in _list(walk_forward.get("windows")):
            if not isinstance(window, dict) or window.get("window") is None:
                continue
            if not isinstance(window.get("train_metrics"), dict):
                continue
            number = int(window["window"])
            diagnostic = _candidate_window_diagnostic(
                strategy_id=strategy_id,
                strategy_name=strategy_name,
                window=window,
                criteria=criteria,
            )
            candidate_windows.setdefault(number, []).append(diagnostic)

    failed_counts: Counter[str] = Counter()
    windows: list[dict[str, Any]] = []
    unexplained_no_trade_windows: list[int] = []
    for number in sorted(set(nested_windows) | set(candidate_windows)):
        nested_window = nested_windows.get(number, {})
        candidates = sorted(candidate_windows.get(number, []), key=_candidate_sort_key)
        for candidate in candidates:
            failed_counts.update(candidate["failed_performance_gates"])
        all_failed = bool(candidates) and all(
            not candidate["performance_gate_eligible"] for candidate in candidates
        )
        decision = str(nested_window.get("decision") or "UNKNOWN")
        if decision == "NO_TRADE" and not all_failed:
            unexplained_no_trade_windows.append(number)
        windows.append(
            {
                "window": number,
                "nested_decision": decision,
                "train_start": nested_window.get("train_start"),
                "train_end": nested_window.get("train_end"),
                "test_start": nested_window.get("test_start"),
                "test_end": nested_window.get("test_end"),
                "all_candidates_failed_performance_gates": all_failed,
                "closest_candidate": candidates[0] if candidates else None,
                "candidates": candidates,
                "nested_warnings": _list(nested_window.get("warnings")),
            }
        )

    no_trade_windows = sum(row["nested_decision"] == "NO_TRADE" for row in windows)
    return {
        "symbol": symbol,
        "selection_status": selection.get("selection_status"),
        "selection_method": selection.get("selection_method"),
        "selection_criteria": criteria.model_dump(mode="json"),
        "summary": {
            "evaluated_windows": len(windows),
            "no_trade_windows": no_trade_windows,
            "trade_windows": len(windows) - no_trade_windows,
            "performance_gate_failure_counts": dict(
                sorted(failed_counts.items(), key=lambda item: (-item[1], item[0]))
            ),
            "no_trade_windows_explained_by_performance_gates": (
                no_trade_windows - len(unexplained_no_trade_windows)
            ),
            "unexplained_no_trade_windows": unexplained_no_trade_windows,
            "statistical_training_gate_evidence_recomputed": False,
        },
        "windows": windows,
    }


def diagnose_payload(payload: dict[str, Any]) -> dict[str, Any]:
    data = _dict(payload.get("data"))
    items = []
    for raw_item in _list(data.get("items")):
        item = _dict(raw_item)
        selection = _dict(item.get("selection"))
        if selection:
            items.append(diagnose_selection(selection))

    aggregate: Counter[str] = Counter()
    for item in items:
        aggregate.update(_dict(_dict(item.get("summary")).get("performance_gate_failure_counts")))

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "success",
        "mode": "diagnostic_only",
        "items": items,
        "aggregate": {
            "symbol_count": len(items),
            "performance_gate_failure_counts": dict(
                sorted(aggregate.items(), key=lambda pair: (-pair[1], pair[0]))
            ),
        },
        "limitations": [
            "Diagnostics reuse candidate walk-forward train metrics already present in the Backtest result.",
            "Statistical validation is not recomputed by this report; an unexplained NO_TRADE window may still be blocked by statistical evidence.",
        ],
        "safety": {
            "selection_thresholds_changed": False,
            "backtest_rerun_performed": False,
            "market_data_refetched": False,
            "promotion_behavior_changed": False,
        },
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Nested Training Gate Diagnostics",
        "",
        "This report explains training-window abstention from existing Backtest evidence. It does not change selection thresholds.",
        "",
    ]
    aggregate = _dict(report.get("aggregate"))
    lines.extend(["## Aggregate gate failures", ""])
    failures = _dict(aggregate.get("performance_gate_failure_counts"))
    if failures:
        for gate, count in failures.items():
            lines.append(f"- `{gate}`: {count}")
    else:
        lines.append("- No performance-gate failures found.")

    for item in _list(report.get("items")):
        if not isinstance(item, dict):
            continue
        summary = _dict(item.get("summary"))
        lines.extend(
            [
                "",
                f"## {item.get('symbol') or 'UNKNOWN'}",
                "",
                f"- Selection status: `{item.get('selection_status')}`",
                f"- NO_TRADE windows: `{summary.get('no_trade_windows', 0)}/{summary.get('evaluated_windows', 0)}`",
                f"- Explained by performance gates: `{summary.get('no_trade_windows_explained_by_performance_gates', 0)}`",
            ]
        )
        for window in _list(item.get("windows")):
            if not isinstance(window, dict):
                continue
            closest = _dict(window.get("closest_candidate"))
            failed = ", ".join(_list(closest.get("failed_performance_gates"))) or "none"
            lines.append(
                f"- Window {window.get('window')}: `{window.get('nested_decision')}`, "
                f"closest `{closest.get('strategy_id') or '-'}`, failed: {failed}"
            )

    lines.extend(
        [
            "",
            "Safety: diagnostic only; no Backtest, Risk, Investability, or Execution threshold is relaxed.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Explain nested NO_TRADE windows from existing Backtest train metrics."
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path)
    args = parser.parse_args()

    report = diagnose_payload(load_console_payload(args.input))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps(report["aggregate"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
