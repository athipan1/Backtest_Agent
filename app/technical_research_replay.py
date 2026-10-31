"""Research-only replay of Technical_Agent PR #53 predicates.

This module deliberately does not register a StrategyName, create a promotion
record, or expose an order endpoint. Indicators are supplied as point-in-time
observations; computing them from revised or future data is out of scope.
"""
from __future__ import annotations

from datetime import datetime
import math
from statistics import median
from typing import Any


FAMILIES = ("trend_following", "mean_reversion")
CONTRACT = "technical-research-observation.v1"


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def signal_as_of(row: dict[str, Any]) -> dict[str, bool]:
    """Predicate parity with Technical_Agent's non-binding research strategies."""
    price = _finite(row.get("close"))
    sma = _finite(row.get("sma200"))
    rsi = _finite(row.get("rsi14"))
    macd = _finite(row.get("macd"))
    signal = _finite(row.get("macd_signal"))
    valid = (
        all(value is not None for value in (price, sma, rsi, macd, signal))
        and price > 0 and sma > 0 and 0 <= rsi <= 100
    )
    return {
        "trend_following": bool(
            valid and price > sma and 50 <= rsi <= 70 and macd > signal
        ),
        "mean_reversion": bool(
            valid and price < sma and rsi < 30 and macd > signal
        ),
    }


def _instant(value: Any) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware datetimes")
    return value


def validate_pit_rows(rows: list[dict[str, Any]]) -> None:
    if len(rows) < 3:
        raise ValueError("at least three chronological bars required")
    previous = None
    for row in rows:
        timestamp = _instant(row.get("timestamp"))
        observed = _instant(row.get("indicators_as_of"))
        if observed > timestamp:
            raise ValueError("look_ahead_indicator_timestamp")
        if previous is not None and timestamp <= previous:
            raise ValueError("bars_not_strictly_chronological")
        previous = timestamp
        if _finite(row.get("open")) is None or row["open"] <= 0:
            raise ValueError("invalid_open_price")
        if not isinstance(row.get("regime"), str) or not row["regime"]:
            raise ValueError("missing_point_in_time_regime")


def _trades(
    rows: list[dict[str, Any]],
    family: str,
    start: int,
    stop: int,
    cost_bps: float,
) -> list[dict[str, Any]]:
    """Bar i signal, bar i+1 open entry, bar i+2 open exit.

    The final two observed bars are never used as signal bars. No same-bar
    execution or future-bar indicator access is permitted.
    """
    trades = []
    for i in range(start, min(stop, len(rows) - 2)):
        if not signal_as_of(rows[i])[family]:
            continue
        entry = float(rows[i + 1]["open"])
        exit_price = float(rows[i + 2]["open"])
        net = exit_price / entry - 1 - cost_bps / 10000
        trades.append({
            "signal_at": rows[i]["timestamp"].isoformat(),
            "entry_at": rows[i + 1]["timestamp"].isoformat(),
            "exit_at": rows[i + 2]["timestamp"].isoformat(),
            "regime": rows[i]["regime"],
            "gross_return": exit_price / entry - 1,
            "cost_fraction": cost_bps / 10000,
            "net_return": net,
        })
    return trades


def _metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    returns = [trade["net_return"] for trade in trades]
    gain = sum(max(x, 0) for x in returns)
    loss = sum(max(-x, 0) for x in returns)
    return {
        "trade_count": len(returns),
        "net_return_sum": sum(returns),
        "profitable_trade_rate": (
            sum(x > 0 for x in returns) / len(returns) if returns else None
        ),
        "profit_factor": gain / loss if loss else None,
    }


def nested_pit_diagnostics(
    rows: list[dict[str, Any]],
    *,
    train_bars: int = 252,
    test_bars: int = 63,
    embargo_bars: int = 2,
    cost_bps: float = 20.0,
) -> dict[str, Any]:
    """Train-select/test-observe research only; never a certification gate.

    Train windows choose a family using training data only. A test fold starts
    after the embargo; all diagnostic trades fully exit within their segment.
    """
    validate_pit_rows(rows)
    if train_bars < 3 or test_bars < 3 or embargo_bars < 2:
        raise ValueError("insufficient_train_test_or_embargo")
    if not math.isfinite(cost_bps) or cost_bps < 0:
        raise ValueError("invalid_execution_cost")
    windows = []
    for test_start in range(train_bars + embargo_bars, len(rows) - 2, test_bars):
        train_end = test_start - embargo_bars
        train_start = train_end - train_bars
        test_end = min(test_start + test_bars, len(rows))
        if test_end - test_start < 3:
            break
        scores = {
            family: _metrics(_trades(rows, family, train_start, train_end - 2, cost_bps))
            for family in FAMILIES
        }
        eligible = [
            family for family in FAMILIES
            if scores[family]["trade_count"] > 0 and
            scores[family]["net_return_sum"] > 0
        ]
        selected = max(
            eligible, key=lambda family: (scores[family]["net_return_sum"], family)
        ) if eligible else None
        trades = (
            _trades(rows, selected, test_start, test_end - 2, cost_bps)
            if selected else []
        )
        regimes = {}
        for regime in sorted({trade["regime"] for trade in trades}):
            regimes[regime] = _metrics(
                [trade for trade in trades if trade["regime"] == regime]
            )
        windows.append({
            "train_start": rows[train_start]["timestamp"].isoformat(),
            "train_end": rows[train_end - 1]["timestamp"].isoformat(),
            "test_start": rows[test_start]["timestamp"].isoformat(),
            "test_end": rows[test_end - 1]["timestamp"].isoformat(),
            "selected_family": selected,
            "train_candidate_metrics": scores,
            "test_metrics": _metrics(trades),
            "regime_attribution": regimes,
            "test_trades": trades,
            "abstained": selected is None,
        })
    net = [fold["test_metrics"]["net_return_sum"] for fold in windows
           if not fold["abstained"]]
    return {
        "contract": CONTRACT,
        "diagnostic_only": True,
        "execution_authorized": False,
        "production_certified": False,
        "sealed_holdout_opened": False,
        "passed": False,
        "reason": "requires_canonical_nested_oos_statistical_cost_risk_and_promotion_gates",
        "cost_bps_round_trip": cost_bps,
        "embargo_bars": embargo_bars,
        "fold_count": len(windows),
        "median_deployed_fold_net_return": median(net) if net else None,
        "folds": windows,
    }
