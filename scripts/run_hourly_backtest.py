from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.data_provider import AlpacaMarketDataProvider, dataset_fingerprint
from app.main import (
    BacktestBatchRunAndPublishRequest,
    BacktestRunAndPublishRequest,
    backtest_run_and_publish,
    backtest_run_and_publish_batch,
)
from app.publisher import ENGINE_VERSION

BACKTEST_MODE_NESTED_PROMOTION = "nested_promotion"
BACKTEST_MODE_LEGACY_FIXED = "legacy_fixed"
VALID_BACKTEST_MODES = frozenset(
    {BACKTEST_MODE_NESTED_PROMOTION, BACKTEST_MODE_LEGACY_FIXED}
)
VALID_RUNTIME_ENVIRONMENTS = frozenset({"production", "research"})
RUNTIME_EVIDENCE_SCHEMA = "backtest-runtime-mode.v1"
NESTED_VALIDATION_PATH = [
    "nested_walk_forward",
    "statistical_validation",
    "robustness",
    "promotion_lifecycle",
]
LEGACY_VALIDATION_PATH = ["legacy_fixed"]


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _default_date_range() -> tuple[str, str]:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=730)
    return start.isoformat(), end.isoformat()


def _deterministic_run_id(payload: dict, fingerprint: str) -> str:
    identity = {
        "dataset_fingerprint": fingerprint,
        "symbols": payload["symbols"],
        "strategy": payload["strategy"],
        "fast_window": payload["fast_window"],
        "slow_window": payload["slow_window"],
        "fee_bps": payload["fee_bps"],
        "slippage_bps": payload["slippage_bps"],
        "risk_per_trade": payload["risk_per_trade"],
        "max_position_pct": payload["max_position_pct"],
        "stop_loss_pct": payload["stop_loss_pct"],
        "reward_risk_ratio": payload["reward_risk_ratio"],
        "use_risk_agent": payload["use_risk_agent"],
        "max_trades_per_day": payload["max_trades_per_day"],
        "emergency_halt": payload["emergency_halt"],
        "max_total_exposure_pct": payload["max_total_exposure_pct"],
        "max_open_positions": payload["max_open_positions"],
        "cash_reserve_pct": payload["cash_reserve_pct"],
        "max_new_positions_per_bar": payload["max_new_positions_per_bar"],
        "periods_per_year": payload["periods_per_year"],
        "annual_risk_free_rate": payload["annual_risk_free_rate"],
        "max_volume_participation_pct": payload["max_volume_participation_pct"],
        "market_impact_bps": payload["market_impact_bps"],
        "force_close_at_end": payload["force_close_at_end"],
        "engine_version": ENGINE_VERSION,
        "timeframe": payload["timeframe"],
    }
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode("utf-8")).hexdigest()
    return f"backtest-{digest[:24]}"


def _symbols_from_env() -> list[str]:
    raw = os.getenv("BACKTEST_SYMBOLS") or os.getenv("BACKTEST_SYMBOL", "AAPL")
    symbols = list(
        dict.fromkeys(
            item.strip().upper()
            for item in raw.split(",")
            if item.strip()
        )
    )
    if not symbols:
        raise ValueError("BACKTEST_SYMBOLS must contain at least one symbol")
    invalid = [
        symbol
        for symbol in symbols
        if re.fullmatch(r"[A-Z0-9][A-Z0-9.-]{0,19}", symbol) is None
    ]
    if invalid:
        raise ValueError(f"BACKTEST_SYMBOLS contains invalid symbols: {invalid}")
    max_symbols = int(os.getenv("BACKTEST_MAX_SYMBOLS", "10"))
    if len(symbols) > max_symbols:
        raise ValueError(
            f"BACKTEST_SYMBOLS contains {len(symbols)} symbols; "
            f"maximum is {max_symbols}"
        )
    return symbols


def _load_payload(provider=None) -> dict:
    payload_file = os.getenv("BACKTEST_PAYLOAD_FILE")
    if payload_file:
        return json.loads(Path(payload_file).read_text(encoding="utf-8"))

    symbols = _symbols_from_env()
    timeframe = os.getenv("BACKTEST_TIMEFRAME", "1d")
    default_start, default_end = _default_date_range()
    start = os.getenv("BACKTEST_START") or default_start
    end = os.getenv("BACKTEST_END") or default_end
    minimum_bars = int(os.getenv("BACKTEST_MINIMUM_BARS", "252"))
    provider = provider or AlpacaMarketDataProvider(
        api_key=os.getenv("ALPACA_API_KEY_ID", ""),
        secret_key=os.getenv("ALPACA_SECRET_KEY", ""),
        base_url=os.getenv("ALPACA_DATA_API_URL", "https://data.alpaca.markets"),
        feed=os.getenv("ALPACA_DATA_FEED", "iex"),
    )
    normalized_bars = {
        symbol: provider.fetch_bars(
            symbol=symbol,
            timeframe=timeframe,
            start=start,
            end=end,
            minimum_bars=minimum_bars,
            limit=int(os.getenv("BACKTEST_BAR_LIMIT", "10000")),
        )
        for symbol in symbols
    }
    fingerprint = dataset_fingerprint(normalized_bars)
    payload = {
        "account_id": os.getenv("BACKTEST_ACCOUNT_ID", "1"),
        "skill_id": os.getenv("BACKTEST_SKILL_ID", "hourly-sma-crossover"),
        "strategy_id": os.getenv("BACKTEST_STRATEGY_ID", "hourly-sma-crossover"),
        "timeframe": timeframe,
        "publish_to_database": _bool_env("PUBLISH_TO_DATABASE", True),
        "symbols": symbols,
        "initial_equity": float(os.getenv("BACKTEST_INITIAL_EQUITY", "100000")),
        "strategy": os.getenv("BACKTEST_STRATEGY", "sma_crossover"),
        "fast_window": int(os.getenv("BACKTEST_FAST_WINDOW", "2")),
        "slow_window": int(os.getenv("BACKTEST_SLOW_WINDOW", "3")),
        "fee_bps": float(os.getenv("BACKTEST_FEE_BPS", "0")),
        "slippage_bps": float(os.getenv("BACKTEST_SLIPPAGE_BPS", "0")),
        "risk_per_trade": float(os.getenv("BACKTEST_RISK_PER_TRADE", "0.01")),
        "max_position_pct": float(os.getenv("BACKTEST_MAX_POSITION_PCT", "0.10")),
        "stop_loss_pct": float(os.getenv("BACKTEST_STOP_LOSS_PCT", "0.03")),
        "reward_risk_ratio": float(os.getenv("BACKTEST_REWARD_RISK_RATIO", "2.0")),
        "use_risk_agent": _bool_env("BACKTEST_USE_RISK_AGENT", True),
        "max_trades_per_day": int(os.getenv("BACKTEST_MAX_TRADES_PER_DAY", "5")),
        "emergency_halt": _bool_env("BACKTEST_EMERGENCY_HALT", False),
        "max_total_exposure_pct": float(os.getenv("BACKTEST_MAX_TOTAL_EXPOSURE_PCT", "1.0")),
        "max_open_positions": int(os.getenv("BACKTEST_MAX_OPEN_POSITIONS", "25")),
        "cash_reserve_pct": float(os.getenv("BACKTEST_CASH_RESERVE_PCT", "0.0")),
        "max_new_positions_per_bar": int(os.getenv("BACKTEST_MAX_NEW_POSITIONS_PER_BAR", "25")),
        "periods_per_year": int(os.getenv("BACKTEST_PERIODS_PER_YEAR", "252")),
        "annual_risk_free_rate": float(os.getenv("BACKTEST_ANNUAL_RISK_FREE_RATE", "0.0")),
        "max_volume_participation_pct": float(os.getenv("BACKTEST_MAX_VOLUME_PARTICIPATION_PCT", "1.0")),
        "market_impact_bps": float(os.getenv("BACKTEST_MARKET_IMPACT_BPS", "0.0")),
        "force_close_at_end": _bool_env("BACKTEST_FORCE_CLOSE_AT_END", False),
        "bars": {
            symbol: [bar.model_dump(mode="json") for bar in bars]
            for symbol, bars in normalized_bars.items()
        },
        "metadata": {
            "data_source": "alpaca_market_data",
            "dataset_fingerprint": fingerprint,
            "data_start": start,
            "data_end": end,
            "bar_count": sum(len(bars) for bars in normalized_bars.values()),
            "bar_counts": {
                symbol: len(bars)
                for symbol, bars in normalized_bars.items()
            },
            "trigger": os.getenv("GITHUB_EVENT_NAME", "manual"),
            "workflow": os.getenv("GITHUB_WORKFLOW", "hourly-backtest"),
            "repository": os.getenv("GITHUB_REPOSITORY", "unknown"),
            "run_id": os.getenv("GITHUB_RUN_ID", "unknown"),
            "storage_only": True,
        },
    }
    payload["run_id"] = os.getenv("BACKTEST_RUN_ID") or _deterministic_run_id(payload, fingerprint)
    return payload


def _runtime_environment() -> str:
    event_name = os.getenv("GITHUB_EVENT_NAME", "").strip().lower()
    configured = os.getenv("BACKTEST_ENVIRONMENT")

    if event_name == "schedule":
        if configured is not None and configured.strip().lower() != "production":
            raise ValueError(
                "Scheduled hourly Backtests are production runs; "
                "BACKTEST_ENVIRONMENT cannot override them to research"
            )
        return "production"

    environment = (configured or "research").strip().lower()
    if environment not in VALID_RUNTIME_ENVIRONMENTS:
        allowed = ", ".join(sorted(VALID_RUNTIME_ENVIRONMENTS))
        raise ValueError(
            f"Unsupported BACKTEST_ENVIRONMENT={environment!r}; expected one of: {allowed}"
        )
    return environment


def _resolve_backtest_mode(environment: str | None = None) -> str:
    environment = environment or _runtime_environment()
    mode = (os.getenv("BACKTEST_MODE") or BACKTEST_MODE_NESTED_PROMOTION).strip().lower()
    if mode not in VALID_BACKTEST_MODES:
        allowed = ", ".join(sorted(VALID_BACKTEST_MODES))
        raise ValueError(f"Unsupported BACKTEST_MODE={mode!r}; expected one of: {allowed}")

    if environment == "production" and mode != BACKTEST_MODE_NESTED_PROMOTION:
        raise RuntimeError(
            "Production Backtests require BACKTEST_MODE=nested_promotion; "
            "legacy_fixed is research/manual only"
        )
    if (
        os.getenv("GITHUB_EVENT_NAME", "").strip().lower() == "schedule"
        and mode != BACKTEST_MODE_NESTED_PROMOTION
    ):
        raise RuntimeError("Scheduled hourly Backtests cannot run legacy_fixed")
    return mode


def _runtime_evidence(mode: str, environment: str) -> dict[str, Any]:
    validation_path = (
        NESTED_VALIDATION_PATH
        if mode == BACKTEST_MODE_NESTED_PROMOTION
        else LEGACY_VALIDATION_PATH
    )
    return {
        "schema_version": RUNTIME_EVIDENCE_SCHEMA,
        "backtest_mode": mode,
        "runtime_environment": environment,
        "validation_path": list(validation_path),
        "automatic_fallback_allowed": False,
        "production_legacy_allowed": False,
    }


def _attach_runtime_evidence(
    output: dict[str, Any], *, mode: str, environment: str
) -> dict[str, Any]:
    output["runtime"] = _runtime_evidence(mode, environment)
    return output


def _annotate_existing_report(
    report_path: Path, *, mode: str, environment: str
) -> None:
    if not report_path.exists():
        return
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(report, dict):
        raise RuntimeError("Hourly Backtest report root must be a JSON object")
    _attach_runtime_evidence(report, mode=mode, environment=environment)
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _log_runtime_mode(mode: str, environment: str) -> None:
    print(
        json.dumps(
            {
                "event": "backtest_runtime_mode",
                **_runtime_evidence(mode, environment),
            },
            sort_keys=True,
        )
    )


def main() -> None:
    environment = _runtime_environment()
    mode = _resolve_backtest_mode(environment)
    _log_runtime_mode(mode, environment)

    if mode == BACKTEST_MODE_NESTED_PROMOTION:
        from scripts.run_nested_hourly_backtest import main as nested_main

        report_path = Path(
            os.getenv("BACKTEST_REPORT_PATH", "reports/hourly-backtest-result.json")
        )
        try:
            nested_main()
        finally:
            _annotate_existing_report(
                report_path,
                mode=mode,
                environment=environment,
            )
        return

    payload = _load_payload()
    if len(payload["symbols"]) == 1:
        response = backtest_run_and_publish(
            BacktestRunAndPublishRequest(**payload)
        )
    else:
        batch_payload = {
            **payload,
            "batch_id": payload["run_id"],
            "run_id": None,
        }
        response = backtest_run_and_publish_batch(
            BacktestBatchRunAndPublishRequest(**batch_payload)
        )
    output = _attach_runtime_evidence(
        response.model_dump(mode="json"),
        mode=mode,
        environment=environment,
    )
    reports_dir = Path("reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / "hourly-backtest-result.json"
    report_path.write_text(json.dumps(output, indent=2, sort_keys=True), encoding="utf-8")
    if len(payload["symbols"]) > 1:
        for item in output["data"]["items"]:
            symbol = re.sub(r"[^a-z0-9]+", "-", item["symbol"].lower()).strip("-")
            item_path = reports_dir / f"hourly-backtest-{symbol}.json"
            item_path.write_text(
                json.dumps(item, indent=2, sort_keys=True),
                encoding="utf-8",
            )
    print(json.dumps(output, indent=2, sort_keys=True))

    publish_required = bool(payload.get("publish_to_database", True))
    if len(payload["symbols"]) == 1:
        if publish_required and (response.data is None or not response.data.published):
            publish_status = (
                "missing_result"
                if response.data is None
                else response.data.publish_status
            )
            raise SystemExit(
                "Single-symbol Database publish failed or was skipped: "
                f"{publish_status}. See hourly report."
            )
    elif response.data is None or not response.data.all_succeeded:
        raise SystemExit("One or more symbol Backtests failed; see batch report.")


if __name__ == "__main__":
    main()
