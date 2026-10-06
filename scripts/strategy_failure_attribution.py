from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def _family(row: dict[str, Any]) -> str:
    strategy = str(row.get("strategy") or "").strip()
    if strategy:
        return strategy
    strategy_id = str(row.get("strategy_id") or "unknown")
    for prefix in ("sma-crossover", "trend-following", "mean-reversion", "breakout"):
        if strategy_id.startswith(prefix):
            return prefix.replace("-", "_")
    return "unknown"


def build_failure_attribution(report: dict[str, Any]) -> dict[str, Any]:
    data = report.get("data") or {}
    gate_counts: Counter[str] = Counter()
    family_counts: dict[str, Counter[str]] = defaultdict(Counter)
    rows: list[dict[str, Any]] = []

    for item in data.get("items") or []:
        symbol = item.get("symbol")
        selection = item.get("selection") or {}
        for candidate in selection.get("ranked_results") or []:
            nested = candidate.get("nested_walk_forward") or candidate.get("walk_forward") or {}
            failed_gates = [
                name for name, passed in (nested.get("gates") or {}).items()
                if passed is False
            ]
            if not failed_gates:
                failed_gates = list(candidate.get("disqualification_reasons") or [])
            family = _family(candidate)
            for reason in failed_gates:
                gate_counts[str(reason)] += 1
                family_counts[family][str(reason)] += 1
            rows.append({
                "symbol": symbol,
                "strategy_id": candidate.get("strategy_id"),
                "strategy_family": family,
                "eligible": candidate.get("eligible"),
                "failed_gates": failed_gates,
                "profitable_window_rate": nested.get("profitable_window_rate"),
                "median_sharpe_ratio": nested.get("median_sharpe_ratio"),
                "median_profit_factor": nested.get("median_profit_factor"),
                "worst_max_drawdown": nested.get("worst_max_drawdown"),
                "evaluated_windows": nested.get("evaluated_windows"),
            })

    statistical_failures = []
    for item in data.get("items") or []:
        evidence = item.get("statistical_evidence") or {}
        if evidence and evidence.get("passed") is False:
            statistical_failures.append({
                "symbol": item.get("symbol"),
                "strategy_id": item.get("selected_strategy_id"),
                "failed_gates": [
                    name for name, passed in (evidence.get("gates") or {}).items()
                    if passed is False
                ],
                "adjusted_p_value": evidence.get("adjusted_p_value"),
                "probabilistic_sharpe_ratio": evidence.get("probabilistic_sharpe_ratio"),
                "deflated_sharpe_probability": evidence.get("deflated_sharpe_probability"),
                "bootstrap_annualized_return_lower": evidence.get("bootstrap_annualized_return_lower"),
                "hac_mean_positive_probability": evidence.get("hac_mean_positive_probability"),
                "trade_count": evidence.get("trade_count"),
            })

    return {
        "schema_version": "research-strategy-failure-attribution.v1",
        "candidate_count": len(rows),
        "failure_gate_counts": dict(gate_counts.most_common()),
        "failure_gate_counts_by_family": {
            family: dict(counts.most_common()) for family, counts in sorted(family_counts.items())
        },
        "candidate_rows": rows,
        "statistical_failures": statistical_failures,
        "diagnostic_only": True,
        "thresholds_changed": False,
        "used_for_selection": False,
        "promotion_allowed": False,
        "execution_allowed": False,
        "sealed_holdout_opened": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Attribute Strategy Research failures without changing gates.")
    parser.add_argument("report", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    result = build_failure_attribution(report)
    rendered = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
