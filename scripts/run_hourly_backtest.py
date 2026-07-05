from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.main import BacktestRunAndPublishRequest, backtest_run_and_publish


DEFAULT_BARS = [
    {"timestamp": "2026-01-01T00:00:00Z", "open": 100, "high": 103, "low": 98, "close": 100, "volume": 100000},
    {"timestamp": "2026-01-02T00:00:00Z", "open": 101, "high": 105, "low": 100, "close": 104, "volume": 100000},
    {"timestamp": "2026-01-03T00:00:00Z", "open": 104, "high": 108, "low": 103, "close": 107, "volume": 100000},
    {"timestamp": "2026-01-04T00:00:00Z", "open": 107, "high": 110, "low": 105, "close": 109, "volume": 100000},
    {"timestamp": "2026-01-05T00:00:00Z", "open": 109, "high": 111, "low": 106, "close": 108, "volume": 100000},
    {"timestamp": "2026-01-06T00:00:00Z", "open": 108, "high": 112, "low": 107, "close": 111, "volume": 100000},
    {"timestamp": "2026-01-07T00:00:00Z", "open": 111, "high": 115, "low": 110, "close": 114, "volume": 100000},
    {"timestamp": "2026-01-08T00:00:00Z", "open": 114, "high": 116, "low": 111, "close": 112, "volume": 100000},
    {"timestamp": "2026-01-09T00:00:00Z", "open": 112, "high": 117, "low": 111, "close": 116, "volume": 100000},
    {"timestamp": "2026-01-10T00:00:00Z", "open": 116, "high": 120, "low": 115, "close": 119, "volume": 100000},
]


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _load_payload() -> dict:
    payload_file = os.getenv("BACKTEST_PAYLOAD_FILE")
    if payload_file:
        return json.loads(Path(payload_file).read_text(encoding="utf-8"))

    symbol = os.getenv("BACKTEST_SYMBOL", "AAPL").upper()
    return {
        "account_id": os.getenv("BACKTEST_ACCOUNT_ID", "1"),
        "run_id": os.getenv("BACKTEST_RUN_ID"),
        "skill_id": os.getenv("BACKTEST_SKILL_ID", "hourly-sma-crossover"),
        "strategy_id": os.getenv("BACKTEST_STRATEGY_ID", "hourly-sma-crossover"),
        "timeframe": os.getenv("BACKTEST_TIMEFRAME", "1d"),
        "publish_to_database": _bool_env("PUBLISH_TO_DATABASE", True),
        "symbols": [symbol],
        "initial_equity": float(os.getenv("BACKTEST_INITIAL_EQUITY", "100000")),
        "strategy": os.getenv("BACKTEST_STRATEGY", "sma_crossover"),
        "fast_window": int(os.getenv("BACKTEST_FAST_WINDOW", "2")),
        "slow_window": int(os.getenv("BACKTEST_SLOW_WINDOW", "3")),
        "fee_bps": float(os.getenv("BACKTEST_FEE_BPS", "0")),
        "slippage_bps": float(os.getenv("BACKTEST_SLIPPAGE_BPS", "0")),
        "bars": {symbol: DEFAULT_BARS},
        "metadata": {
            "trigger": os.getenv("GITHUB_EVENT_NAME", "manual"),
            "workflow": os.getenv("GITHUB_WORKFLOW", "hourly-backtest"),
            "repository": os.getenv("GITHUB_REPOSITORY", "unknown"),
            "run_id": os.getenv("GITHUB_RUN_ID", "unknown"),
            "storage_only": True,
        },
    }


def main() -> None:
    payload = _load_payload()
    response = backtest_run_and_publish(BacktestRunAndPublishRequest(**payload))
    output = response.model_dump(mode="json")
    reports_dir = Path("reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / "hourly-backtest-result.json"
    report_path.write_text(json.dumps(output, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
