#!/usr/bin/env python3
"""Export the exact nested-promotion history requirement for orchestrators.

This script intentionally has no third-party dependencies. It reads the production
runner's default constants directly from ``app/hourly_promotion_runner.py`` so a
Manager workflow never needs to duplicate the 630 research + 252 sealed-holdout
contract. Runtime environment overrides are resolved with the same names used by
the runner and emitted to ``GITHUB_ENV`` for downstream Scanner prechecks.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = REPO_ROOT / "app" / "hourly_promotion_runner.py"
SCHEMA_VERSION = "backtest-history-contract.v1"
_REQUIRED_DEFAULT_NAMES = (
    "DEFAULT_MINIMUM_BARS",
    "DEFAULT_FINAL_HOLDOUT_BARS",
    "DEFAULT_HISTORY_DAYS",
)
_SAFE_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.FloorDiv)
_SAFE_UNARYOPS = (ast.UAdd, ast.USub)


class HistoryContractError(RuntimeError):
    """Raised when the production history contract cannot be resolved safely."""


def _positive_int(value: object, *, name: str) -> int:
    try:
        resolved = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise HistoryContractError(f"{name} must be an integer") from exc
    if resolved <= 0:
        raise HistoryContractError(f"{name} must be greater than zero")
    return resolved


def _bool(value: object, *, default: bool = True) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _safe_constant_int(node: ast.AST, *, name: str) -> int:
    """Evaluate only integer literals and simple integer arithmetic from source."""

    if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
        return int(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, _SAFE_UNARYOPS):
        operand = _safe_constant_int(node.operand, name=name)
        return operand if isinstance(node.op, ast.UAdd) else -operand
    if isinstance(node, ast.BinOp) and isinstance(node.op, _SAFE_BINOPS):
        left = _safe_constant_int(node.left, name=name)
        right = _safe_constant_int(node.right, name=name)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if right == 0:
            raise HistoryContractError(
                f"production runner constant {name} divides by zero"
            )
        return left // right
    raise HistoryContractError(
        f"production runner constant {name} is not a safe integer constant expression"
    )


def _runner_defaults(path: Path = RUNNER_PATH) -> dict[str, int]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError) as exc:
        raise HistoryContractError(f"cannot read production runner defaults: {exc}") from exc

    values: dict[str, int] = {}
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        value_node = node.value
        for target in targets:
            if not isinstance(target, ast.Name) or target.id not in _REQUIRED_DEFAULT_NAMES:
                continue
            value = _safe_constant_int(value_node, name=target.id)
            values[target.id] = _positive_int(value, name=target.id)

    missing = sorted(set(_REQUIRED_DEFAULT_NAMES) - set(values))
    if missing:
        raise HistoryContractError(
            "production runner history defaults are incomplete: " + ", ".join(missing)
        )
    return values


def resolve_history_contract(
    environ: Mapping[str, str] | None = None,
    *,
    runner_path: Path = RUNNER_PATH,
) -> dict[str, object]:
    env = os.environ if environ is None else environ
    defaults = _runner_defaults(runner_path)

    if not _bool(env.get("BACKTEST_FINAL_HOLDOUT_ENABLED"), default=True):
        raise HistoryContractError(
            "nested promotion requires BACKTEST_FINAL_HOLDOUT_ENABLED=true"
        )

    research_bars = _positive_int(
        env.get("BACKTEST_NESTED_MINIMUM_BARS", defaults["DEFAULT_MINIMUM_BARS"]),
        name="BACKTEST_NESTED_MINIMUM_BARS",
    )
    holdout_bars = _positive_int(
        env.get(
            "BACKTEST_FINAL_HOLDOUT_BARS",
            defaults["DEFAULT_FINAL_HOLDOUT_BARS"],
        ),
        name="BACKTEST_FINAL_HOLDOUT_BARS",
    )
    history_days = _positive_int(
        env.get("BACKTEST_HISTORY_DAYS", defaults["DEFAULT_HISTORY_DAYS"]),
        name="BACKTEST_HISTORY_DAYS",
    )
    required_bars = research_bars + holdout_bars

    return {
        "schema_version": SCHEMA_VERSION,
        "validation_mode": "nested_promotion",
        "research_minimum_bars": research_bars,
        "sealed_holdout_bars": holdout_bars,
        "required_total_bars": required_bars,
        "history_days": history_days,
        "final_holdout_enabled": True,
        "runner_source": str(runner_path),
        "runner_defaults": {
            "research_minimum_bars": defaults["DEFAULT_MINIMUM_BARS"],
            "sealed_holdout_bars": defaults["DEFAULT_FINAL_HOLDOUT_BARS"],
            "history_days": defaults["DEFAULT_HISTORY_DAYS"],
        },
        "thresholds_relaxed": False,
    }


def write_history_contract(
    *,
    github_env_path: Path,
    output_path: Path,
    environ: Mapping[str, str] | None = None,
    runner_path: Path = RUNNER_PATH,
) -> dict[str, object]:
    contract = resolve_history_contract(environ, runner_path=runner_path)
    contract["generated_at"] = datetime.now(timezone.utc).isoformat()

    github_env_path.parent.mkdir(parents=True, exist_ok=True)
    with github_env_path.open("a", encoding="utf-8") as stream:
        stream.write(f"BACKTEST_HISTORY_REQUIRED_BARS={contract['required_total_bars']}\n")
        stream.write(f"BACKTEST_NESTED_MINIMUM_BARS={contract['research_minimum_bars']}\n")
        stream.write(f"BACKTEST_FINAL_HOLDOUT_BARS={contract['sealed_holdout_bars']}\n")
        stream.write(f"BACKTEST_HISTORY_DAYS={contract['history_days']}\n")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(contract, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return contract


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--github-env", default=os.getenv("GITHUB_ENV", ""))
    parser.add_argument(
        "--output",
        default="reports/backtest-history-contract.json",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if not str(args.github_env or "").strip():
        print("Backtest history contract failed closed: GITHUB_ENV is missing", file=sys.stderr)
        return 1
    try:
        contract = write_history_contract(
            github_env_path=Path(args.github_env),
            output_path=Path(args.output),
        )
    except HistoryContractError as exc:
        print(f"Backtest history contract failed closed: {exc}", file=sys.stderr)
        return 1

    print(
        "Resolved Backtest history contract: "
        f"research={contract['research_minimum_bars']}, "
        f"holdout={contract['sealed_holdout_bars']}, "
        f"required={contract['required_total_bars']}, "
        f"history_days={contract['history_days']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
