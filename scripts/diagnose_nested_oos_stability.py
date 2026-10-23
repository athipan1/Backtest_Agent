"""Read-only nested OOS stability diagnostics. Never authorizes a trade."""
import argparse
import json
from pathlib import Path


def diagnose(windows, minimum_positive_fraction=0.60):
    if not isinstance(windows, list) or not windows:
        raise ValueError("windows must be a non-empty list")
    rows = []
    for index, window in enumerate(windows):
        if not isinstance(window, dict) or "net_return" not in window:
            raise ValueError(f"window {index} requires net_return")
        value = window["net_return"]
        if isinstance(value, bool) or not isinstance(value, (float, int)):
            raise ValueError(f"window {index} net_return must be numeric")
        import math
        if not math.isfinite(value):
            raise ValueError(f"window {index} net_return must be finite")
        rows.append({"index": index, "strategy": window.get("strategy", "unknown"),
                     "net_return": value, "positive": value > 0})
    positive = sum(row["positive"] for row in rows)
    import math
    required = math.ceil(minimum_positive_fraction * len(rows))
    return {"research_only": True, "trading_eligible": False,
            "positive_windows": positive, "total_windows": len(rows),
            "required_positive_windows": required,
            "shortfall": max(0, required - positive),
            "passes_positive_fraction_diagnostic": positive >= required,
            "windows": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="JSON file containing windows list")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    report = diagnose(payload["windows"])
    rendered = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
