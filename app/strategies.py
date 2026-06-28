from __future__ import annotations

from typing import List, Literal, Optional

from app.engine import sma
from app.models import PriceBar

StrategyName = Literal["sma_crossover", "trend_following", "mean_reversion", "breakout"]
Signal = Literal["buy", "sell", "hold"]


def sma_crossover_signal(closes: List[float], fast_window: int, slow_window: int) -> Signal:
    fast = sma(closes, fast_window)
    slow = sma(closes, slow_window)
    if fast is None or slow is None:
        return "hold"
    if fast > slow:
        return "buy"
    if fast < slow:
        return "sell"
    return "hold"


def trend_following_signal(closes: List[float], fast_window: int, slow_window: int) -> Signal:
    fast = sma(closes, fast_window)
    slow = sma(closes, slow_window)
    if fast is None or slow is None or len(closes) < 2:
        return "hold"
    momentum_up = closes[-1] > closes[-2]
    momentum_down = closes[-1] < closes[-2]
    if fast > slow and momentum_up:
        return "buy"
    if fast < slow and momentum_down:
        return "sell"
    return "hold"


def mean_reversion_signal(closes: List[float], slow_window: int) -> Signal:
    baseline = sma(closes, slow_window)
    if baseline is None or baseline <= 0:
        return "hold"
    distance = (closes[-1] - baseline) / baseline
    if distance <= -0.02:
        return "buy"
    if distance >= 0.02:
        return "sell"
    return "hold"


def breakout_signal(bars: List[PriceBar], slow_window: int) -> Signal:
    if len(bars) <= slow_window:
        return "hold"
    previous_window = bars[-slow_window - 1 : -1]
    previous_high = max(bar.high for bar in previous_window)
    previous_low = min(bar.low for bar in previous_window)
    latest_close = bars[-1].close
    if latest_close > previous_high:
        return "buy"
    if latest_close < previous_low:
        return "sell"
    return "hold"


def strategy_signal(
    strategy: StrategyName,
    closes: List[float],
    bars: List[PriceBar],
    fast_window: int,
    slow_window: int,
) -> Signal:
    if strategy == "sma_crossover":
        return sma_crossover_signal(closes, fast_window, slow_window)
    if strategy == "trend_following":
        return trend_following_signal(closes, fast_window, slow_window)
    if strategy == "mean_reversion":
        return mean_reversion_signal(closes, slow_window)
    if strategy == "breakout":
        return breakout_signal(bars, slow_window)
    return "hold"
