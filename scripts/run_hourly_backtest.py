from __future__ import annotations

import json
import os
import re
import sys
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.main import (
    BacktestBatchRunAndPublishRequest,
    BacktestRunAndPublishRequest,
    backtest_run_and_publish,
    backtest_run_and_publish_batch,
)
from app.data_provider import AlpacaMarketDataProvider, dataset_fingerprint
from app.publisher import ENGINE_VERSION


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


def main() -> None:
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
    output = response.model_dump(mode="json")
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
    if len(payload["symbols"]) > 1 and not response.data.all_succeeded:
        raise SystemExit("One or more symbol Backtests failed; see batch report.")


if __name__ == "__main__":
    main()
