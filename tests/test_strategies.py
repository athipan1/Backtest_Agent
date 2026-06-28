from app.models import PriceBar
from app.strategies import breakout_signal, mean_reversion_signal, strategy_signal, trend_following_signal


def make_bar(day: int, close: float, high: float | None = None, low: float | None = None) -> PriceBar:
    return PriceBar(
        timestamp=f"2026-01-{day:02d}T00:00:00Z",
        open=close,
        high=high if high is not None else close + 1,
        low=low if low is not None else close - 1,
        close=close,
        volume=1000,
    )


def test_trend_following_requires_momentum_confirmation():
    assert trend_following_signal([10, 11, 12, 13], fast_window=2, slow_window=3) == "buy"
    assert trend_following_signal([13, 12, 11, 10], fast_window=2, slow_window=3) == "sell"


def test_mean_reversion_buys_weakness_and_sells_strength():
    assert mean_reversion_signal([100, 100, 100, 96], slow_window=3) == "buy"
    assert mean_reversion_signal([100, 100, 100, 104], slow_window=3) == "sell"


def test_breakout_signal_uses_previous_range():
    bars = [
        make_bar(1, 10, high=11, low=9),
        make_bar(2, 11, high=12, low=10),
        make_bar(3, 12, high=13, low=11),
        make_bar(4, 14, high=15, low=13),
    ]
    assert breakout_signal(bars, slow_window=3) == "buy"

    breakdown = [
        make_bar(1, 10, high=11, low=9),
        make_bar(2, 11, high=12, low=10),
        make_bar(3, 12, high=13, low=11),
        make_bar(4, 8, high=9, low=7),
    ]
    assert breakout_signal(breakdown, slow_window=3) == "sell"


def test_strategy_signal_routes_supported_strategies():
    bars = [make_bar(1, 10), make_bar(2, 11), make_bar(3, 12), make_bar(4, 13)]
    closes = [bar.close for bar in bars]

    assert strategy_signal("sma_crossover", closes, bars, fast_window=2, slow_window=3) == "buy"
    assert strategy_signal("trend_following", closes, bars, fast_window=2, slow_window=3) == "buy"
    assert strategy_signal("breakout", closes, bars, fast_window=2, slow_window=3) == "hold"
